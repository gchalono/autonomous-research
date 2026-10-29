"""V7 contract checks. Every rate/response is synthetic; no live allowance."""
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import OpenAI, DefaultHttpxClient, _base_client
from src.llm.provider import OpenAIProvider
from src.storage.policy import load_policy_file, load_policy_text, PolicyError
from src.storage.spending import SpendingGuard, SpendingBlocked
from tests.policy_fixtures import reviewed_fixture

DRAFT = Path(__file__).resolve().parents[1] / 'policy_v5/canonical_budget_policy.draft.json'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('V7 offline test attempted a real socket connection')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


def synthetic_policy():
    return reviewed_fixture({
        'currency': 'USD', 'expires_at': '2099-01-01T00:00:00+00:00',
        'evidence': 'SYNTHETIC TEST RATES ONLY; not verified provider prices',
        'openai': {model: {
            'max_input_tokens': 1000, 'max_output_tokens': 100,
            'max_request_bytes': 4000, 'input_token_overhead': 256,
            'input_bound_mode': 'utf8_text', 'input_usd_per_million': '300',
            'output_usd_per_million': '1000',
        } for model in ('gpt-5.4-mini', 'gpt-5.6-terra')},
        'tavily': {'basic_search_max_usd': '0.1', 'usd_per_credit': '0.1'},
    })


@pytest.fixture
def lab(tmp_path, monkeypatch):
    import src.storage.spending as spending
    policy_path, ledger = tmp_path / 'policy.json', tmp_path / 'ledger.sqlite3'
    monkeypatch.setattr(spending, 'POLICY_PATH', policy_path)
    monkeypatch.setattr(spending, 'LEDGER_PATH', ledger)
    def build(data=None):
        policy_path.write_text(json.dumps(synthetic_policy() if data is None else data))
        g = SpendingGuard.default()
        g.initialize()
        return g
    return build


def response():
    return SimpleNamespace(model='gpt-5.4-mini', service_tier='default',
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def invoke(g, send=None, **kwargs):
    return g.invoke_openai(send or (lambda **kw: response()),
                           {'model': 'gpt-5.4-mini', 'input': 'q', **kwargs})


def adapter(g, sdk):
    p = object.__new__(OpenAIProvider)
    p.guard, p._sdk, p.fallback_model = g, sdk, None
    return p


def test_P01_bounded_operation_serializes_through_installed_sdk(lab):
    """Actual SDK construction/HTTP serialization, with a mock HTTP transport."""
    g = lab()
    h = _base_client.httpx2
    calls = []
    def send(req):
        body = json.loads(req.content)
        calls.append(body)
        assert str(req.url) == 'https://api.openai.com/v1/responses'
        assert body['max_output_tokens'] == 100 and body['service_tier'] == 'default'
        return h.Response(200, json={
            'id': 'offline', 'object': 'response', 'created_at': 0,
            'status': 'completed', 'model': body['model'], 'service_tier': 'default',
            'output': [{'type': 'message', 'id': 'offline-message', 'role': 'assistant',
                        'status': 'completed', 'content': [{'type': 'output_text',
                        'text': '{}', 'annotations': []}]}],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2,
                      'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                      'output_tokens_details': {'reasoning_tokens': 0}},
        })
    sdk = OpenAI(api_key='offline-sentinel-not-a-credential', max_retries=0,
                 http_client=DefaultHttpxClient(follow_redirects=False, transport=h.MockTransport(send)))
    try:
        p = adapter(g, sdk)
        assert p.complete('s', 'u', {'type': 'object', 'properties': {}}, 'gpt-5.4-mini')[0] == {}
        p.create_tool_response('s', [{'role': 'user', 'content': 'u'}],
                               [{'type': 'function', 'name': 'offline_function',
                                 'parameters': {'type': 'object', 'properties': {}}}], 'gpt-5.6-terra')
    finally:
        sdk.close()
    assert len(calls) == 2
    assert sum(r['reserved_micro_usd'] for r in g.snapshot()['requests']) == 800000


def test_P02_unknown_model(lab):
    g = lab()
    with pytest.raises(SpendingBlocked): invoke(g, model='unknown')
    assert not g.snapshot()['requests']


def test_P03_unsupported_endpoint(lab):
    g = lab()
    h = _base_client.httpx2
    sdk = OpenAI(api_key='offline-sentinel-not-a-credential', base_url='https://example.com/v1', max_retries=0,
                 http_client=DefaultHttpxClient(follow_redirects=False, transport=h.MockTransport(lambda r: pytest.fail('dispatch'))))
    try:
        with pytest.raises(SpendingBlocked): invoke(g, sdk.responses.create)
    finally:
        sdk.close()
    assert not g.snapshot()['requests']


def test_P04_missing_pricing(lab):
    p = synthetic_policy(); del p['openai']['gpt-5.4-mini']['input_usd_per_million']
    with pytest.raises(SpendingBlocked): lab(p)


def test_P05_unverified_pricing(lab):
    p = synthetic_policy(); p['openai']['gpt-5.4-mini']['pricing_status'] = 'UNVERIFIED'
    with pytest.raises(SpendingBlocked): lab(p)


def test_P06_input_exceeds_bound(lab):
    g = lab()
    with pytest.raises(SpendingBlocked): invoke(g, input='x' * 1001)
    assert not g.snapshot()['requests']


def test_P07_output_exceeds_bound(lab):
    g = lab()
    with pytest.raises(SpendingBlocked): invoke(g, max_output_tokens=101)
    assert not g.snapshot()['requests']


def test_P08_nonzero_sdk_retry_policy_rejected(lab):
    p = synthetic_policy(); p['max_sdk_retries'] = 1
    with pytest.raises(SpendingBlocked): lab(p)


def test_P09_uncovered_fallback(lab):
    g = lab()
    p = adapter(g, SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: pytest.fail('dispatch'))))
    with pytest.raises(SpendingBlocked): p.complete('s', 'u', {}, 'uncovered-fallback')
    assert not g.snapshot()['requests']


def test_P10_cumulative_reservations(lab):
    g = lab(); invoke(g); invoke(g)
    with pytest.raises(SpendingBlocked): invoke(g)
    assert sum(r['reserved_micro_usd'] for r in g.snapshot()['requests']) == 800000


def test_P11_concurrent_reservation_is_atomic(lab):
    g = lab(); barrier = threading.Barrier(8)
    def reserve(_):
        barrier.wait(timeout=5)
        try: return g.reserve('openai', 'gpt-5.4-mini', '0.4')
        except SpendingBlocked: return None
    with ThreadPoolExecutor(8) as pool: results = list(pool.map(reserve, range(8)))
    assert sum(r is not None for r in results) == 1
    assert sum(r['reserved_micro_usd'] for r in g.snapshot()['requests']) == 400000


def test_P12_unpriced_tool_and_search(lab):
    p = synthetic_policy(); p['tavily'] = None; g = lab(p)
    with pytest.raises(SpendingBlocked): invoke(g, tools=[{'type': 'web_search'}])
    with pytest.raises(SpendingBlocked): g.invoke_tavily(lambda: pytest.fail('search dispatch'))
    assert not g.snapshot()['requests']


def test_P13_malformed_or_unsupported_policy():
    for text in ('{broken', '{"policy_schema_version":999}', '[]'):
        with pytest.raises(PolicyError): load_policy_text(text, usable=True)


def test_P14_canonical_draft_stays_inactive(tmp_path):
    import src.storage.spending as spending
    before = (spending.POLICY_PATH.exists(), spending.LEDGER_PATH.exists())
    assert load_policy_file(DRAFT)['state'] == 'draft'
    with pytest.raises(PolicyError): load_policy_file(DRAFT, usable=True)
    with pytest.raises(SpendingBlocked): SpendingGuard(tmp_path/'must-not-exist.db', json.loads(DRAFT.read_text()))
    assert not (tmp_path/'must-not-exist.db').exists()
    assert before == (spending.POLICY_PATH.exists(), spending.LEDGER_PATH.exists()) == (False, False)


def test_P15_invalid_request_through_actual_adapter_and_search(lab, monkeypatch):
    import src.tools.search as search
    g = lab(); calls = []
    p = adapter(g, SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(kw))))
    with pytest.raises(SpendingBlocked): p.complete('s', 'u', {}, 'unknown')
    monkeypatch.setattr(search, '_open_tavily', lambda *a, **k: pytest.fail('Tavily dispatch'))
    with pytest.raises(SpendingBlocked): search._search_tavily('q', 21)
    assert calls == [] and not g.snapshot()['requests']


def test_P01b_tavily_actual_builder_is_basic_and_usage_enabled(lab, monkeypatch):
    import src.tools.search as search
    g = lab(); captured = []
    class MockResponse:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'usage': {'credits': 1}, 'results': []}).encode()
    def send(req, timeout):
        captured.append(json.loads(req.data))
        assert req.full_url == 'https://api.tavily.com/search' and timeout == 30
        return MockResponse()
    monkeypatch.setenv('TAVILY_API_KEY', 'offline-sentinel-not-a-credential')
    monkeypatch.setattr(search, '_open_tavily', send)
    assert search._search_tavily('offline query', 8) == []
    assert captured == [{'query': 'offline query', 'max_results': 8,
                         'search_depth': 'basic', 'include_usage': True}]
    assert g.snapshot()['requests'][0]['reserved_micro_usd'] == 100000
