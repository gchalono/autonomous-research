"""Offline regressions for defects confirmed in the engineering audit."""
import copy
import io
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.auditor import verify_sources
from src.agents.common import AgentOutputError, call_agent
from src.agents.executor import _capped_items, run_execution_native
from src.llm.provider import LLMError, OpenAIProvider, StubProvider, default_stub_behavior
from src.models.contracts import ExecutionReport, ExecutorStep, PromptEvaluation, VerificationStatus
from src.orchestration.engine import BudgetExhausted, Orchestrator
from src.orchestration.states import InvalidTransitionError, State, validate_transition
from src.storage import artifacts
from src.storage.ledger import ValidationLedger
from src.tools.computation import safe_evaluate
from src.tools.retrieval import PublicRedirectHandler, fetch_url, validate_public_url
from tests.conftest import fake_fetch, fake_registry
from tests.test_tool_protocol import ScriptedNativeClient, VALID_REPORT, fn_call, submit


def engine_for(settings, store, behavior=None):
    return Orchestrator(settings, store, client=StubProvider(behavior or default_stub_behavior()),
                        registry=fake_registry(), fetch_fn=fake_fetch)


@pytest.mark.parametrize('status', ['OPEN', 'IN_PROGRESS', 'UNRESOLVED'])
def test_previous_issue_cannot_disappear_in_approval(settings, store, status):
    behavior = default_stub_behavior()
    issue = dict(id='A1', severity='MAJOR', affected_claim_or_section='C1', description='Unsupported claim',
                 required_correction='Fix it', status=status)
    behavior['auditor'] = lambda n, u: dict(decision='CORRECTIONS_REQUIRED' if n == 1 else 'APPROVE',
                                           issues=[issue] if n == 1 else [])
    engine = engine_for(settings, store, behavior)
    pid = engine.create_project('Objective')
    result = engine.run(pid)
    assert result['state'] == 'COMPLETED_WITH_LIMITATIONS'
    audit = store.load_output(pid, 'audit_2')
    assert audit['decision'] == 'CORRECTIONS_REQUIRED'
    assert audit['issues'][0]['status'] == status
    assert 'Decision: CORRECTIONS_REQUIRED' in engine.report_text(pid)
    task = store.load_output(pid, 'correction_1')
    assert task['issue_ids'] == ['A1']


def test_deterministic_issue_resolves_only_after_evidence_fixed(settings, store):
    behavior = default_stub_behavior()
    base = behavior['executor']
    def execute(n, user):
        step = base(n, user)
        if step['report'] and 'CORRECTION TASK' not in user:
            step = copy.deepcopy(step)
            step['report']['claims'][0]['source_ids'] = ['missing']
        return step
    behavior['executor'] = execute
    engine = engine_for(settings, store, behavior)
    pid = engine.create_project('Objective')
    result = engine.run(pid)
    assert result['state'] == 'COMPLETED' and result['corrections'] == 1
    issues = store.list_issues(pid)
    assert len(issues) == 2 and all(i['status'] == 'RESOLVED' for i in issues)
    assert store.load_output(pid, 'audit_0')['decision'] == 'CORRECTIONS_REQUIRED'


def test_verification_checks_complete_passage():
    report = ExecutionReport.model_validate(VALID_REPORT)
    report.sources[0].passage = 'a' * 60 + ' fabricated conclusion'
    statuses = verify_sources(report, lambda url: ('title', 'a' * 60 + ' actual conclusion'))
    assert statuses['S1'] == VerificationStatus.NOT_FOUND


def test_first_request_and_search_obey_budgets(settings, store):
    engine = engine_for(settings, store)
    pid = engine.create_project('Objective', budget_usd=0)
    result = engine.run(pid)
    assert result['state'] == 'BUDGET_EXHAUSTED' and engine.client.calls == {}
    assert engine.ledger.total_spent == 0
    pid = engine.create_project('Search', budget_usd=0.01)
    settings.tavily_cost_per_search = 0.02
    with pytest.raises(BudgetExhausted, match='tool preflight'):
        engine._tool_runner(pid)(engine.registry.get('web_search'), {'query': 'x'})
    assert store.list_tool_calls(pid) == []


def test_cancellation_checked_between_parallel_calls(settings, store):
    from src.tools.base import ToolResult
    engine = engine_for(settings, store)
    pid = engine.create_project('Objective')
    client = ScriptedNativeClient([[fn_call('web_search', {'query': 'first'}, 'a'),
                                    fn_call('web_search', {'query': 'second'}, 'b')]])
    client.complete = engine.client.complete
    engine.client = client
    tool = engine.registry.get('web_search')
    def cancel_after_first(args):
        engine.cancel(pid)
        return ToolResult(ok=True, output='result')
    tool.run = cancel_after_first
    result = engine.run(pid)
    assert result['state'] == 'CANCELLED'
    assert len(store.list_tool_calls(pid)) == 1


def test_runtime_guard_during_execution_is_valid_transition(settings, store):
    engine = engine_for(settings, store)
    pid = engine.create_project('Objective')
    store.transition(pid, 'CREATED', 'EXECUTING', 'test fixture')
    settings.max_runtime_s = 0
    result = engine.run(pid)
    assert result['state'] == 'FAILED' and 'runtime limit' in result['failure_reason']


def test_mixed_submit_and_tools_requires_another_turn():
    client = ScriptedNativeClient([[submit(VALID_REPORT), fn_call('calculate', {'expression': '2+2'}, 'b')],
                                   [submit(VALID_REPORT)]])
    run_execution_native(client, 'model', ['spec'], fake_registry())
    assert len(client.calls) == 2
    assert 'ERROR' in json.dumps(client.calls[1][1])


def test_latest_native_result_is_never_dropped():
    round_items = [fn_call('fetch_page', {'url': 'https://example.com'}, 'a'),
                   {'type': 'function_call_output', 'call_id': 'a', 'output': 'x' * 1000}]
    items = _capped_items({'role': 'user', 'content': 'spec'}, [round_items], max_chars=100)
    assert items[-2:] == round_items


def test_malformed_then_invalid_gets_only_one_total_repair():
    class Client:
        n = 0
        def complete(self, *args):
            self.n += 1
            if self.n == 1:
                raise LLMError('non-JSON')
            return {'decision': 'invalid'}, 100, 50
    client = Client()
    with pytest.raises(AgentOutputError):
        call_agent(client, 'model', 'system', 'user', PromptEvaluation)
    assert client.n == 2


def test_json_fallback_supplies_schema_and_accounts_malformed_responses():
    requests, charges = [], []
    def create(**kwargs):
        requests.append(kwargs)
        if kwargs['text']['format']['type'] == 'json_schema':
            raise ValueError('unsupported schema')
        assert 'Required JSON schema:' in kwargs['input'] and 'required_revisions' in kwargs['input']
        return SimpleNamespace(output_text='not json', usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               status='completed', id='resp-bad')
    provider = object.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    provider.request_cost_cb = lambda m, i, o, preflight=False: charges.append((m, i, o, preflight))
    with pytest.raises(LLMError, match='non-JSON'):
        provider.complete('system', 'user', PromptEvaluation.model_json_schema(), 'model')
    assert len([c for c in charges if c[-1]]) == 2
    assert [c for c in charges if not c[-1]] == [('model', 100, 50, False)]


def test_non_schema_400_does_not_retry_as_json_mode():
    count = []
    def create(**kwargs):
        count.append(kwargs)
        raise ValueError('400 invalid parameter: input')
    provider = object.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with pytest.raises(LLMError):
        provider.complete('system', 'user', {}, 'model')
    assert len(count) == 1


def test_provider_budget_control_does_not_become_api_error():
    provider = object.__new__(OpenAIProvider)
    def reject(*args, **kwargs):
        raise BudgetExhausted('no budget')
    provider.request_cost_cb = reject
    provider.client = None
    with pytest.raises(BudgetExhausted):
        provider.complete('system', 'user', {}, 'model')


def test_fallback_model_charged_at_actual_model():
    charges = []
    def create(**kwargs):
        if kwargs['model'] == 'missing':
            raise ValueError('model not found')
        return SimpleNamespace(output_text='{}', id='r', usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    provider = object.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    provider.fallback_model = 'fallback'
    provider.request_cost_cb = lambda m, i, o, preflight=False: charges.append((m, preflight))
    provider.complete('system', 'user', {}, 'missing')
    assert charges == [('missing', True), ('fallback', True), ('fallback', False)]


def test_sdk_automatic_retries_disabled(monkeypatch):
    import openai
    captured = {}
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: captured.update(kwargs))
    OpenAIProvider(api_key='offline-placeholder', timeout_s=7, max_output_tokens=123)
    assert captured['max_retries'] == 0 and captured['timeout'] == 7


@pytest.mark.parametrize('contents', ['{broken', '{"entries": [{"cost_usd": -1}]}',
                                     '{"entries": [{"cost_usd": NaN}]}'])
def test_corrupt_ledger_fails_closed(tmp_path, contents):
    path = tmp_path / 'ledger.json'
    path.write_text(contents)
    with pytest.raises((ValueError, KeyError)):
        ValidationLedger(str(path), 1)
    assert path.read_text() == contents


def test_stale_ledger_instances_do_not_lose_spend(tmp_path):
    path = str(tmp_path / 'ledger.json')
    first, second = ValidationLedger(path, 3), ValidationLedger(path, 3)
    first.record('p', 'openai', 'm', 0.1, 'call')
    second.record('p', 'openai', 'm', 0.2, 'call')
    assert first.total_spent == second.total_spent == 0.3


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://localhost/', 'http://127.0.0.1/',
                                 'http://169.254.169.254/', 'https://user:pass@example.com/',
                                 'http://[::1]/', 'http://example.com:8080/'])
def test_private_or_non_http_source_rejected(url, monkeypatch):
    def resolve(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (host, 80))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_redirect_cannot_reach_local_file():
    import urllib.request
    with pytest.raises(ValueError):
        PublicRedirectHandler().redirect_request(urllib.request.Request('https://example.com'),
                                                None, 302, 'Found', {}, 'file:///etc/passwd')


def test_artifact_writes_confined_even_through_symlink(tmp_path):
    root = tmp_path / 'projects'
    outside = tmp_path / 'outside'
    outside.mkdir()
    root.mkdir()
    (root / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        artifacts.write_text(str(root), '../escape', 'x', 'bad')
    with pytest.raises(ValueError):
        artifacts.write_text(str(root), 'escape', 'x', 'bad')
    with pytest.raises(ValueError):
        artifacts.write_text(str(root), 'p', '../../x', 'bad')
    assert not list(outside.iterdir())


@pytest.mark.parametrize('expr', ['10 ** 1000000000', '9 ** (9 ** 9)', '1+' * 300 + '1'])
def test_computation_resource_exhaustion_rejected(expr):
    with pytest.raises(ValueError):
        safe_evaluate(expr)


def test_software_event_cannot_move_to_arbitrary_state():
    with pytest.raises(InvalidTransitionError):
        validate_transition(State.EXECUTING, State.COMPLETED, 'cancel')


def test_transition_counters_and_event_rollback_together(settings, store):
    engine = engine_for(settings, store)
    pid = engine.create_project('objective')
    store.conn.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'crash'); END")
    with pytest.raises(Exception, match='crash'):
        store.transition(pid, 'CREATED', 'PROMPT_REVISION', 'test', counters={'prompt_revisions': 1})
    project = store.get_project(pid)
    assert project['state'] == 'CREATED' and project['prompt_revisions'] == 0


@pytest.mark.parametrize('stored_first', [True, False])
def test_spend_reconciles_after_partial_write(settings, store, stored_first):
    engine = engine_for(settings, store)
    pid = engine.create_project('objective')
    if stored_first:
        store.add_spend(pid, 0.05)
    else:
        engine.ledger.record(pid, 'openai', 'm', 0.05, 'call')
    engine._reconcile_spend()
    assert engine.ledger.total_spent == store.get_project(pid)['spent_usd'] == 0.05
    engine._reconcile_spend()
    assert engine.ledger.total_spent == 0.05


def test_readiness_commands_require_explicit_paid_authorization(monkeypatch):
    from scripts import validate_live, smoke_live
    monkeypatch.setattr(validate_live, 'OpenAIProvider', lambda **kw: pytest.fail('must not create provider'))
    with pytest.raises(SystemExit) as result:
        validate_live.main(['--model', 'm', '--input-usd-per-million', '1',
                            '--output-usd-per-million', '1', '--search-usd-per-call', '.01'])
    assert result.value.code == 2
    monkeypatch.setattr('sys.argv', ['smoke_live.py'])
    with pytest.raises(SystemExit) as result:
        smoke_live.main()
    assert result.value.code == 2


def test_invalid_budget_environment_fails_closed(monkeypatch):
    from src.config import Settings
    for value in ['bad', 'nan', '-1', 'inf']:
        monkeypatch.setenv('AR_BUDGET_USD', value)
        with pytest.raises(ValueError):
            Settings.from_env()


def test_list_multiplication_cannot_exhaust_memory():
    with pytest.raises(ValueError):
        safe_evaluate('[1] * 1000000000')


def test_oversized_page_rejected_before_parsing(monkeypatch):
    import src.tools.retrieval as retrieval
    monkeypatch.setattr(retrieval, 'validate_public_url', lambda url: None)
    monkeypatch.setattr(retrieval.urllib.request, 'build_opener', lambda *a: SimpleNamespace(
        open=lambda *a, **k: io.BytesIO(b'x' * (retrieval._MAX_BYTES + 1))))
    with pytest.raises(ValueError, match='size limit'):
        fetch_url('https://example.com')


def test_provenance_gap_blocks_approval(settings, store):
    behavior = default_stub_behavior()
    behavior['executor'] = lambda n, u: dict(done=True, report=VALID_REPORT)
    settings.max_corrections = 0
    engine = engine_for(settings, store, behavior)
    result = engine.run(engine.create_project('objective'))
    assert result['state'] == 'COMPLETED_WITH_LIMITATIONS'
    assert any('fetch history' in i['description'] for i in store.list_issues(result['project_id']))


def test_predictable_temp_symlink_cannot_escape(tmp_path):
    outside = tmp_path / 'outside'
    outside.write_text('keep')
    dest = tmp_path / 'report.md'
    Path(str(dest) + '.tmp').symlink_to(outside)
    artifacts.atomic_write(str(dest), 'new report')
    assert outside.read_text() == 'keep' and dest.read_text() == 'new report'


def test_incomplete_response_still_records_cost():
    charges = []
    provider = object.__new__(OpenAIProvider)
    provider.request_cost_cb = lambda m, i, o, preflight=False: charges.append((i, o, preflight))
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        id='r', usage=SimpleNamespace(input_tokens=100, output_tokens=6000), status='incomplete')))
    with pytest.raises(LLMError, match='incomplete'):
        provider.complete('system', 'user', {}, 'model')
    assert charges[-1] == (100, 6000, False)


def test_approved_report_with_dependencies_is_limited(settings, store):
    behavior = default_stub_behavior()
    base = behavior['executor']
    def execute(n, user):
        step = copy.deepcopy(base(n, user))
        if step.get('report'):
            step['report']['unresolved_dependencies'] = ['Official pricing data unavailable.']
        return step
    behavior['executor'] = execute
    engine = engine_for(settings, store, behavior)
    result = engine.run(engine.create_project('objective'))
    assert result['state'] == 'COMPLETED_WITH_LIMITATIONS'
    assert 'Official pricing data unavailable.' in engine.report_text(result['project_id'])


def test_duplicate_source_identity_blocks(settings, store):
    behavior = default_stub_behavior()
    base = behavior['executor']
    def execute(n, user):
        step = copy.deepcopy(base(n, user))
        if step.get('report'):
            step['report']['sources'] *= 2
        return step
    behavior['executor'] = execute
    settings.max_corrections = 0
    engine = engine_for(settings, store, behavior)
    result = engine.run(engine.create_project('objective'))
    assert result['state'] == 'COMPLETED_WITH_LIMITATIONS'
    assert any('duplicate source' in i['description'] for i in store.list_issues(result['project_id']))


def test_full_reexecution_cannot_reuse_old_fetch_history(settings, store):
    behavior = default_stub_behavior()
    base = behavior['executor']
    def execute(n, user):
        if 'FULL RE-EXECUTION' in user:
            return dict(done=True, report=VALID_REPORT)
        return base(n, user)
    issue = dict(id='A1', severity='MAJOR', affected_claim_or_section='all',
                 description='methodology invalid', required_correction='Restart research', status='OPEN')
    behavior['executor'] = execute
    behavior['auditor'] = lambda n, u: dict(decision='CORRECTIONS_REQUIRED' if n == 1 else 'APPROVE',
                                           issues=[{**issue, 'status': 'OPEN' if n == 1 else 'RESOLVED'}])
    settings.max_corrections = 1
    engine = engine_for(settings, store, behavior)
    result = engine.run(engine.create_project('objective'))
    assert result['state'] == 'COMPLETED_WITH_LIMITATIONS'
    assert any('fetch history' in i['description'] and i['status'] == 'OPEN'
               for i in store.list_issues(result['project_id']))
