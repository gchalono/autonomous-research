"""Independent audit regressions. All model, HTTP and DNS traffic is mocked."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.llm.provider import OpenAIProvider, StubProvider, default_stub_behavior
from src.models.contracts import ExecutionReport, VerificationStatus
from src.orchestration.claim_check import analyze_claim_support
from src.orchestration.engine import Orchestrator
from src.storage.database import Store
from src.tools.retrieval import fetch_url
from tests.test_workflow_e2e import ResearchSDK, install_transports


@pytest.mark.parametrize('classification', ['INFERRED', 'ESTIMATED', 'PARTIALLY_SUPPORTED', 'CONTRADICTED'])
def test_unconfirmed_evidence_cannot_support_derivation(classification):
    report = ExecutionReport.model_validate(default_stub_behavior()['executor'](1, 'TOOL RESULT [fetch_page]')['report'])
    report.claims[0].classification = classification
    issues = analyze_claim_support(report, {'S1': VerificationStatus.UNREACHABLE}, [])
    assert any(i.severity.value in ('MAJOR', 'CRITICAL') for i in issues)


def test_usage_survives_missing_run_log(settings, store, monkeypatch):
    engine = Orchestrator(settings, store)
    pid = engine.create_project('Usage durability')
    monkeypatch.setattr(engine, '_log', lambda *a: None)
    engine._cost_cb(pid)('test-model', 123, 45)
    entry = engine.ledger.entries[-1]
    assert entry['input_tokens'] == 123 and entry['output_tokens'] == 45


def test_scenario_b_incorrect_research_is_corrected(settings, store, monkeypatch):
    calls = install_transports(monkeypatch)
    provider = object.__new__(OpenAIProvider)
    provider.client = ResearchSDK()
    engine = Orchestrator(settings, store, client=provider, fetch_fn=fetch_url)
    result = engine.run(engine.create_project('Net value after the processing fee'))
    assert result['state'] == 'COMPLETED' and result['corrections'] == 1
    assert 'Net value is 10 units.' in engine.report_text(result['project_id'])
    assert store.list_issues(result['project_id'])[0]['status'] == 'RESOLVED'
    assert calls == {'search': 1, 'fetch': 3}


def test_scenario_c_crash_after_tool_commit_before_transcript_checkpoint(settings, store, monkeypatch):
    """A process interruption at the local commit boundary, not a model timeout."""
    calls = install_transports(monkeypatch)
    provider = object.__new__(OpenAIProvider)
    sdk = provider.client = ResearchSDK()
    settings.tavily_cost_per_search = .01
    engine = Orchestrator(settings, store, client=provider, fetch_fn=fetch_url)
    pid = engine.create_project('Net value after the processing fee')
    save = store.save_output
    def interrupt(project_id, key, payload):
        pending = payload.get('pending')
        if key == 'execution_0_checkpoint' and pending and pending['outputs']:
            raise KeyboardInterrupt('simulated process interruption after completed search')
        save(project_id, key, payload)
    monkeypatch.setattr(store, 'save_output', interrupt)
    with pytest.raises(KeyboardInterrupt):
        engine.run(pid)
    spend_before = engine.ledger.total_spent
    assert calls['search'] == 1 and len(store.list_tool_calls(pid)) == 1
    db_path = store.db_path
    store.close()
    reopened = Store(db_path)
    try:
        resumed = Orchestrator(settings, reopened, client=provider, fetch_fn=fetch_url)
        result = resumed.run(pid)
        assert result['state'] == 'COMPLETED'
        assert calls['search'] == 1
        assert len([t for t in reopened.list_tool_calls(pid) if t['tool'] == 'web_search']) == 1
        assert resumed.ledger.total_spent > spend_before
        assert len([e for e in resumed.ledger.entries if e['kind'] == 'search_call']) == 1
        assert resumed.ledger.total_spent == round(reopened.get_project(pid)['spent_usd'], 6)
    finally:
        reopened.close()


def test_pure_arithmetic_uses_observed_calculator_evidence():
    report = ExecutionReport.model_validate({
        'executive_summary': '2 + 3 = 5',
        'claims': [{'id': 'C1', 'text': '2 + 3 = 5', 'classification': 'ESTIMATED',
                    'calculation_expressions': ['2 + 3']}],
    })
    history = [{'tool': 'calculate', 'ok': True, 'arguments_json': '{"expression":"2 + 3"}'}]
    assert analyze_claim_support(report, {}, history) == []
    assert any(i.severity.value == 'MAJOR' for i in analyze_claim_support(report, {}, []))


def test_scenario_a_bounded_success_through_real_sdk_http_contract(tmp_path, monkeypatch, capsys):
    """Real SDK serialization/DTO parsing; only HTTP/DNS/model answers mocked."""
    import io
    import socket
    import urllib.request
    import openai
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    from collections import Counter
    from scripts import validate_live
    from src.models.contracts import PromptSpec, PromptEvaluation, AuditReport
    from tests.test_workflow_e2e import function

    url = validate_live.SOURCE_URL
    passage = '``None`` is the sole instance of the :data:`~types.NoneType` type.'
    report = ExecutionReport.model_validate(dict(
        executive_summary='None is the sole instance of NoneType; 2 + 3 = 5.',
        findings=[dict(id='F1', title='Python fact', text='None is the sole instance of NoneType.', claim_ids=['C1']),
                  dict(id='F2', title='Arithmetic', text='2 + 3 = 5', claim_ids=['C2'])],
        claims=[dict(id='C1', text='None is the sole instance of NoneType.', classification='VERIFIED', source_ids=['S1']),
                dict(id='C2', text='2 + 3 = 5', classification='ESTIMATED', calculation_expressions=['2 + 3'])],
        sources=[dict(id='S1', url=url, title='Built-in constants', passage=passage)]
    )).model_dump(mode='json')
    requests = []
    roles, network = Counter(), Counter()
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('TAVILY_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('AR_PROJECTS_ROOT', str(tmp_path / 'bounded'))
    monkeypatch.setattr(validate_live, 'load_dotenv', lambda: None)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])

    def search(req, timeout=30):
        assert req.full_url == 'https://api.tavily.com/search'
        network['search'] += 1
        return io.BytesIO(json.dumps({'results': [{'url': url, 'title': 'Constants', 'content': passage}]}).encode())
    def fetch(req, timeout=30):
        assert req.full_url == url
        network['fetch'] += 1
        return io.BytesIO(('Built-in Constants\n' + passage).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', search)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: SimpleNamespace(open=fetch))

    reasoning = dict(id='rs_1', type='reasoning', summary=[], encrypted_content='opaque-test-reasoning', status='completed')
    def transport(request):
        assert request.method == 'POST' and request.url.path == '/v1/responses'
        body = json.loads(request.content)
        requests.append(body)
        assert body['model'] == 'offline-model' and body['max_output_tokens'] == 4000
        system = body['instructions'].lower()
        role = next(r for r in ('creator', 'evaluator', 'executor', 'auditor') if
                    {'creator':'prompt creator', 'evaluator':'prompt evaluator',
                     'executor':'research executor', 'auditor':'execution auditor'}[r] in system)
        roles[role] += 1
        n = roles[role]
        if role == 'executor':
            for tool in body['tools']:
                assert tool['strict'] is True and tool['parameters']['additionalProperties'] is False
            if n == 1:
                item = function('web_search', {'query':'CPython constants NoneType', 'max_results':2}, 's')
            elif n == 2:
                assert any(i.get('encrypted_content') == 'opaque-test-reasoning' for i in body['input'])
                assert any(i.get('call_id') == 's' and 'UNTRUSTED DATA' in i.get('output', '') for i in body['input'])
                item = function('fetch_page', {'url':url}, 'f')
            elif n == 3:
                assert passage in json.dumps(body['input'])
                item = function('calculate', {'expression':'2 + 3'}, 'c')
            else:
                assert n == 4 and '2 + 3 = 5' in json.dumps(body['input'])
                item = function('submit_report', report, 'done')
            output = ([reasoning] if n == 1 else []) + [{**item, 'id':f'fc_{n}', 'status':'completed'}]
        else:
            assert body['text']['format']['type'] == 'json_schema'
            if role == 'creator':
                payload = PromptSpec.model_validate(default_stub_behavior()['creator']).model_dump(mode='json')
                payload.update(objective=validate_live.OBJECTIVE, execution_prompt=validate_live.OBJECTIVE)
            elif role == 'evaluator':
                payload = PromptEvaluation(decision='APPROVE').model_dump(mode='json')
            else:
                assert 'OBSERVED CALCULATOR RESULTS' in body['input'] and '2 + 3 = 5' in body['input']
                assert passage in body['input'] and "verified sources ['S1']" in body['input']
                payload = AuditReport(decision='APPROVE', rationale='Fact and arithmetic match evidence.').model_dump(mode='json')
            output = [dict(id=f'msg_{len(requests)}', type='message', role='assistant', status='completed',
                           content=[dict(type='output_text', text=json.dumps(payload), annotations=[])])]
        response = dict(id=f'resp_{len(requests)}', created_at=1.0, model='offline-model', object='response',
                        status='completed', output=output, parallel_tool_calls=True, tool_choice='auto', tools=body.get('tools', []),
                        usage=dict(input_tokens=100, output_tokens=50, total_tokens=150,
                                   input_tokens_details={'cached_tokens':0, 'cache_write_tokens':0}, output_tokens_details={'reasoning_tokens':10}))
        return httpx.Response(200, json=response)

    sdk = openai.OpenAI(api_key='offline-placeholder', max_retries=0,
                        http_client=openai.DefaultHttpxClient(transport=httpx.MockTransport(transport)),
                        _strict_response_validation=True)
    provider = object.__new__(OpenAIProvider)
    provider.client, provider.max_output_tokens = sdk, 4000
    monkeypatch.setattr(validate_live, 'OpenAIProvider', lambda **kw: provider)
    try:
        assert validate_live.main(['--authorize-paid-run', '--model','offline-model',
                                  '--input-usd-per-million','1','--output-usd-per-million','2',
                                  '--search-usd-per-call','.01']) == 0
        summary = json.loads(capsys.readouterr().out)
        assert all(summary['checks'].values())
        assert roles == {'creator':1,'evaluator':1,'executor':4,'auditor':1}
        assert network == {'search':1,'fetch':3}  # free preflight, executor, independent auditor
        ledger = json.loads((tmp_path/'bounded'/'validation_ledger.json').read_text())
        usage = [e for e in ledger['entries'] if e['kind'] == 'llm_call']
        assert sum(e['input_tokens'] for e in usage) == 700
        assert sum(e['output_tokens'] for e in usage) == 350
        assert all(e['response_id'] for e in usage)
        assert sum(e['observed_usage']['output_tokens_details']['reasoning_tokens'] for e in usage) == 70
    finally:
        sdk.close()


def test_request_and_tool_caps_survive_resume(settings, store):
    from src.orchestration.engine import RunFailed
    from tests.conftest import fake_registry, fake_fetch
    settings.max_model_requests = 1
    engine = Orchestrator(settings, store, client=StubProvider(default_stub_behavior()),
                          registry=fake_registry(), fetch_fn=fake_fetch)
    pid = engine.create_project('One request only')
    result = engine.run(pid)
    assert result['state'] == 'FAILED' and sum(engine.client.calls.values()) == 1
    assert 'model request limit' in result['failure_reason']
    assert engine.run(pid)['state'] == 'FAILED'
    assert sum(engine.client.calls.values()) == 1
    settings.max_tool_calls = 1
    pid = engine.create_project('One tool only')
    runner = engine._tool_runner(pid)
    runner(engine.registry.get('web_search'), {'query': 'first'})
    with pytest.raises(RunFailed, match='tool-call limit'):
        runner(engine.registry.get('web_search'), {'query': 'second'})
    assert len(store.list_tool_calls(pid)) == 1


def test_source_preflight_blocks_paid_requests(tmp_path, monkeypatch, capsys):
    from scripts import validate_live
    import socket
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('TAVILY_API_KEY', 'offline-placeholder')
    monkeypatch.setenv('AR_PROJECTS_ROOT', str(tmp_path / 'preflight'))
    monkeypatch.setattr(validate_live, 'load_dotenv', lambda: None)
    def unavailable(url):
        raise socket.gaierror('offline DNS failure')
    monkeypatch.setattr(validate_live, 'fetch_url', unavailable)
    monkeypatch.setattr(validate_live, 'OpenAIProvider', lambda **kw: pytest.fail('No paid client permitted'))
    with pytest.raises(SystemExit) as result:
        validate_live.main(['--authorize-paid-run', '--model','offline-model',
                            '--input-usd-per-million','1','--output-usd-per-million','2',
                            '--search-usd-per-call','.01'])
    assert result.value.code == 2
    assert 'Free source preflight failed (gaierror)' in capsys.readouterr().err
    assert not (tmp_path / 'preflight').exists()


@pytest.mark.parametrize('native', [False, True])
def test_successful_http_response_validation_error_is_not_retried_as_schema_rejection(native):
    from src.llm.provider import LLMError
    requests = []
    class ResponseValidationError(Exception):
        status_code = 200
    def create(**kwargs):
        requests.append(kwargs)
        raise ResponseValidationError('Data returned by API invalid for expected schema')
    provider = object.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    with pytest.raises(LLMError):
        if native:
            provider.create_tool_response('system', [], [], 'model')
        else:
            provider.complete('system', 'user', {}, 'model')
    assert len(requests) == 1
