"""Deterministic full-stack test. No live API, DNS, or HTTP requests.

Uses the real OpenAI adapter, agent prompts, native dispatch, search/retrieval
adapters, independent refetch, state machine, SQLite, ledger, and artifacts.
Only the remote SDK/HTTP transports and DNS are mocked.
"""
import copy
import io
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from src.llm.provider import OpenAIProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from src.tools.retrieval import fetch_url

URL = 'https://evidence.example/research'
PASSAGE = 'The measured value is 12 units and the processing fee is 2 units.'
ISSUE = dict(id='A1', severity='MAJOR', affected_claim_or_section='C1',
             description='Net value omits the fee.', evidence=PASSAGE,
             required_correction='Calculate 12 - 2 and report 10 units.',
             verification_method='Check the calculation and cited passage.', status='OPEN')


def report(net):
    return dict(executive_summary=f'Net value is {net} units.',
                findings=[dict(id='F1', title='Net value', text=f'12 - 2 = {net} units.', claim_ids=['C1'])],
                claims=[dict(id='C1', text=f'Net value is {net} units.', classification='ESTIMATED', source_ids=['S1'])],
                sources=[dict(id='S1', url=URL, title='Measurements', passage=PASSAGE)],
                limitations=[], unresolved_dependencies=[])


def function(name, args, cid):
    return dict(type='function_call', call_id=cid, name=name, arguments=json.dumps(args))


class ResearchSDK:
    def __init__(self, *, transient=False, token_limit=6000):
        self.responses = SimpleNamespace(create=self.create)
        self.roles = Counter()
        self.requests = []
        self.transient = transient
        self.token_limit = token_limit

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        assert request['max_output_tokens'] == self.token_limit
        system = request['instructions'].lower()
        role = next(r for r, phrase in [('creator', 'prompt creator'), ('evaluator', 'prompt evaluator'),
                                       ('executor', 'research executor'), ('auditor', 'execution auditor')]
                    if phrase in system)
        self.roles[role] += 1
        n = self.roles[role]
        user = request['input']
        if role == 'creator':
            payload = copy.deepcopy(default_stub_behavior()['creator'])
            payload['execution_prompt'] = 'Search for measurements, fetch the original source, and calculate net value.'
            if n == 2:
                assert 'explicitly subtract the processing fee' in user
                payload['acceptance_criteria'] = ['Subtract the processing fee.']
        elif role == 'evaluator':
            payload = dict(decision='REVISE' if n == 1 else 'APPROVE',
                           required_revisions=['explicitly subtract the processing fee'] if n == 1 else [])
        elif role == 'auditor':
            assert 'verified sources [\'S1\']' in user
            assert PASSAGE in user
            assert 'INDEPENDENTLY FETCHED SOURCE CONTEXT' in user
            assert 'UNTRUSTED DATA' in user
            if n == 1:
                assert 'Net value is 12 units.' in user
                payload = dict(decision='CORRECTIONS_REQUIRED', issues=[ISSUE], rationale='Fee omitted.')
            else:
                assert 'PREVIOUS AUDIT ISSUES' in user and 'A1' in user
                assert 'Net value is 10 units.' in user
                payload = dict(decision='APPROVE', issues=[{**ISSUE, 'status': 'RESOLVED'}], rationale='Calculation corrected.')
        else:
            text = json.dumps(user)
            if self.transient and n == 2:
                raise TimeoutError('request timed out')
            # Retry of the failed turn must retain the completed search output.
            stage = n - int(self.transient and n > 2)
            if stage == 1:
                output = [function('web_search', {'query': 'measured value processing fee', 'max_results': 2}, 'search')]
            elif stage == 2:
                assert URL in text and PASSAGE in text and 'UNTRUSTED DATA' in text
                output = [function('fetch_page', {'url': URL}, 'fetch')]
            elif stage == 3:
                assert PASSAGE in text and 'function_call_output' in text
                output = [function('submit_report', report(12), 'report1')]
            elif stage == 4:
                assert 'CORRECTION TASK' in text and '12 - 2' in text
                output = [function('calculate', {'expression': '12 - 2'}, 'calc')]
            else:
                assert stage == 5 and '12 - 2 = 10' in text
                output = [function('submit_report', report(10), 'report2')]
            return SimpleNamespace(output=output, usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                                   id=f'resp-{len(self.requests)}', status='completed')
        return SimpleNamespace(output_text=json.dumps(payload),
                               usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               id=f'resp-{len(self.requests)}', status='completed')


def install_transports(monkeypatch):
    import urllib.request
    import socket
    calls = Counter()
    monkeypatch.setenv('TAVILY_API_KEY', 'offline-test-placeholder')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])

    def search(req, timeout=30):
        assert req.full_url == 'https://api.tavily.com/search'
        calls['search'] += 1
        return io.BytesIO(json.dumps({'results': [{'url': URL, 'title': 'Measurements', 'content': PASSAGE}]}).encode())

    def fetch(req, timeout=30):
        assert req.full_url == URL
        calls['fetch'] += 1
        return io.BytesIO(f'<title>Measurements</title><p>{PASSAGE}</p>'.encode())

    monkeypatch.setattr(urllib.request, 'urlopen', search)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: SimpleNamespace(open=fetch))
    return calls


def test_full_native_workflow_with_revision_correction_and_resume(settings, store, monkeypatch):
    calls = install_transports(monkeypatch)
    sdk = ResearchSDK(transient=True)
    provider = object.__new__(OpenAIProvider)
    provider.client = sdk
    settings.tavily_cost_per_search = 0.01
    engine = Orchestrator(settings, store, client=provider, fetch_fn=fetch_url)
    pid = engine.create_project('Determine net value after processing fees using cited evidence.')
    interrupted = engine.run(pid)
    assert interrupted['state'] == 'EXECUTING' and 'transient_error' in interrupted
    assert calls['search'] == 1
    # Reconstruct the engine and DB connection, as a new CLI process would.
    from src.storage.database import Store
    store.close()
    resumed_store = Store(store.db_path)
    try:
        engine = Orchestrator(settings, resumed_store, client=provider, fetch_fn=fetch_url)
        result = engine.run(pid)
        assert result['state'] == 'COMPLETED' and result['terminal_status'] == 'COMPLETED_APPROVED'
        assert result['prompt_revisions'] == 1 and result['corrections'] == 1
        assert calls == {'search': 1, 'fetch': 3}  # executor + two independent audits
        assert sdk.roles == {'creator': 2, 'evaluator': 2, 'executor': 6, 'auditor': 2}
        tools = resumed_store.list_tool_calls(pid)
        assert [t['tool'] for t in tools] == ['web_search', 'fetch_page', 'calculate']
        assert all(t['ok'] for t in tools)
        assert resumed_store.list_issues(pid)[0]['status'] == 'RESOLVED'
        events = [e['event'] for e in resumed_store.list_events(pid)]
        assert 'prompt_revised' in events and 'correction_finished' in events
        root = Path(result['artifact_dir'])
        final = (root / 'final_report.md').read_text()
        assert 'Net value is 10 units.' in final and 'COMPLETED_APPROVED' in final
        assert 'Net value is 12 units.' not in final and '(CONFIRMED)' in final
        audit = json.loads((root / 'audit_report.json').read_text())
        assert audit['decision'] == 'APPROVE' and audit['issues'][0]['status'] == 'RESOLVED'
        assert audit == resumed_store.load_output(pid, 'audit_1')
        assert len(engine.ledger.entries) == 12  # 11 successful model responses + search
        assert engine.ledger.total_spent == round(resumed_store.get_project(pid)['spent_usd'], 6)
        requests = len(sdk.requests)
        engine.run(pid)
        assert len(sdk.requests) == requests  # terminal resume incurs no additional requests
    finally:
        resumed_store.close()


def test_bounded_live_runner_with_mocked_transports(tmp_path, monkeypatch, capsys):
    """Exercise the runnable validation command without making a live call."""
    from scripts import validate_live
    calls = install_transports(monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('AR_PROJECTS_ROOT', str(tmp_path / 'live-runner'))
    sdk = ResearchSDK(token_limit=4000)
    provider = object.__new__(OpenAIProvider)
    provider.client = sdk
    provider.max_output_tokens = 4000
    monkeypatch.setattr(validate_live, 'OpenAIProvider', lambda **kwargs: provider)
    monkeypatch.setattr(validate_live, 'load_dotenv', lambda: None)
    assert validate_live.main(['--authorize-paid-run', '--model', 'test-model',
                               '--input-usd-per-million', '1', '--output-usd-per-million', '2',
                               '--search-usd-per-call', '.01']) == 0
    summary = json.loads(capsys.readouterr().out)
    assert all(summary['checks'].values())
    assert summary['status']['state'] == 'COMPLETED'
    assert calls == {'search': 1, 'fetch': 3}
    assert summary['ledger']['spent_usd'] < 1
