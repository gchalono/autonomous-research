"""Offline adversarial transport tests. All prices and responses are synthetic."""

from tests.policy_fixtures import reviewed_fixture
import concurrent.futures
import copy
import json
import multiprocessing
import os
from types import SimpleNamespace

import pytest

from src.llm.provider import OpenAIProvider
from src.storage.spending import SpendingGuard, SpendingBlocked


def policy():
    return reviewed_fixture({'currency': 'USD', 'expires_at': '2099-01-01T00:00:00+00:00', 'evidence': 'SYNTHETIC OFFLINE TEST FIXTURE, not live price evidence',
            'openai': {'test-model': {'max_input_tokens': 1000, 'max_output_tokens': 100,
                'max_request_bytes': 4000, 'input_usd_per_million': 100,
                'output_usd_per_million': 1000}},
            'tavily': {'basic_search_max_usd': .1, 'usd_per_credit': .1}})


@pytest.fixture
def guard(tmp_path, monkeypatch):
    g = SpendingGuard(tmp_path / 'budget.db', policy())
    g.initialize()
    import src.storage.spending as module
    policy_path = tmp_path / 'policy.json'
    policy_path.write_text(json.dumps(policy()))
    monkeypatch.setattr(module, 'LEDGER_PATH', g.path)
    monkeypatch.setattr(module, 'POLICY_PATH', policy_path)
    return g


def response(i=10, o=10, text='{}'):
    return SimpleNamespace(model='test-model', service_tier='default', usage=SimpleNamespace(input_tokens=i, output_tokens=o),
                           output_text=text, output=[], id='offline-response')


def provider(g, send):
    p = object.__new__(OpenAIProvider)
    p.guard = g
    p.client = SimpleNamespace(responses=SimpleNamespace(create=send))
    p.fallback_model = None
    return p


def request(g, send, model='test-model', **kwargs):
    return g.invoke_openai(send, dict(model=model, input='text', **kwargs))


def reserve_worker(path, data):
    try:
        SpendingGuard(path, data).reserve('openai', 'test-model', .6)
        return True
    except SpendingBlocked:
        return False


def crash_worker(path, data):
    SpendingGuard(path, data).reserve('openai', 'test-model', .6)
    os._exit(17)


def test_concurrent_process_requests_cannot_reuse_balance(guard):
    ctx = multiprocessing.get_context('spawn')
    with concurrent.futures.ProcessPoolExecutor(4, mp_context=ctx) as pool:
        results = list(pool.map(reserve_worker, [str(guard.path)] * 8, [policy()] * 8))
    assert results.count(True) == 1
    assert sum(x['reserved_micro_usd'] for x in guard.snapshot()['requests']) == 600000


def test_concurrent_transports_serialize_fail_closed(guard):
    import threading
    started, release = threading.Event(), threading.Event()
    calls = []
    def send(**kw):
        calls.append(kw)
        started.set()
        assert release.wait(5)
        return response()
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        first = pool.submit(request, guard, send)
        assert started.wait(5)
        try:
            with pytest.raises(SpendingBlocked, match='unreconciled'):
                request(SpendingGuard(guard.path, policy()), send)
        finally:
            release.set()
        first.result()
    assert len(calls) == 1


@pytest.mark.parametrize('i,o', [(1001, 10), (10, 101), (1000000, 1000000)])
def test_unexpected_large_tokens_freeze_before_output_processing(guard, i, o):
    p = provider(guard, lambda **kw: response(i, o))
    with pytest.raises(SpendingBlocked):
        p.complete('s', 'u', {}, 'test-model')
    assert guard.snapshot()['blocked']
    assert guard.snapshot()['requests'][0]['reported_micro_usd'] is not None
    with pytest.raises(SpendingBlocked):
        request(guard, lambda **kw: pytest.fail('must not call'))


def test_retry_loop_timeout_makes_only_one_transport_attempt(guard):
    calls = []
    def timeout(**kw):
        calls.append(kw)
        raise TimeoutError('synthetic timeout')
    for _ in range(20):
        with pytest.raises(SpendingBlocked):
            request(guard, timeout)
    assert len(calls) == 1
    assert guard.snapshot()['requests'][0]['state'] == 'uncertain'
    assert guard.snapshot()['requests'][0]['reported_micro_usd'] is None


@pytest.mark.parametrize('usage', [None, SimpleNamespace(input_tokens=1),
                                  SimpleNamespace(input_tokens=-1, output_tokens=1)])
def test_missing_or_invalid_usage_freezes_session(guard, usage):
    with pytest.raises(SpendingBlocked, match='usage'):
        request(guard, lambda **kw: SimpleNamespace(usage=usage))
    assert guard.snapshot()['blocked']


def test_unknown_model_pricing_never_calls_transport(guard):
    with pytest.raises(SpendingBlocked, match='pricing'):
        request(guard, lambda **kw: pytest.fail('unpriced call'), model='unknown')
    assert guard.snapshot()['requests'] == []


def test_budget_exhaustion_uses_retained_maxima_not_lower_reported_usage(guard):
    for _ in range(5):
        request(guard, lambda **kw: response(0, 0))  # $0.20 reservation each
    with pytest.raises(SpendingBlocked, match='exhausted'):
        request(guard, lambda **kw: pytest.fail('sixth call'))
    rows = guard.snapshot()['requests']
    assert sum(x['reserved_micro_usd'] for x in rows) == 1000000
    assert all(x['reported_micro_usd'] == 0 for x in rows)


@pytest.mark.parametrize('native', [False, True])
def test_provider_fallback_and_schema_retry_stop_on_uncertain_charge(guard, native):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs['model'])
        raise RuntimeError('400 schema rejected; model does not exist')
    p = provider(guard, fail)
    p.fallback_model = 'unpriced-fallback'
    with pytest.raises(SpendingBlocked):
        if native:
            p.create_tool_response('s', ['u'], [], 'test-model')
        else:
            p.complete('s', 'u', {}, 'test-model')
    assert calls == ['test-model']
    assert len(guard.snapshot()['requests']) == 1


def test_different_candidate_pricing_gets_its_own_reservation(guard, monkeypatch):
    p = policy()
    p['openai']['expensive'] = dict(p['openai']['test-model'], input_usd_per_million=900)
    # A new policy cannot be substituted into an existing session.
    with pytest.raises(SpendingBlocked, match='mismatch'):
        request(SpendingGuard(guard.path, p), lambda **kw: response())
    g = SpendingGuard(guard.path.with_name('other.db'), p)
    g.initialize()
    import src.storage.spending as module
    policy_path = guard.path.with_name('other-policy.json')
    policy_path.write_text(json.dumps(p))
    monkeypatch.setattr(module, 'LEDGER_PATH', g.path)
    monkeypatch.setattr(module, 'POLICY_PATH', policy_path)
    request(g, lambda **kw: response())
    with pytest.raises(SpendingBlocked, match='exhausted'):
        request(g, lambda **kw: pytest.fail('fallback exceeds remaining'), model='expensive')


def test_crash_and_recovery_preserve_pending_exposure(guard):
    ctx = multiprocessing.get_context('spawn')
    proc = ctx.Process(target=crash_worker, args=(str(guard.path), policy()))
    proc.start(); proc.join(10)
    assert proc.exitcode == 17
    reopened = SpendingGuard(guard.path, policy())
    assert reopened.snapshot()['requests'][0]['reserved_micro_usd'] == 600000
    with pytest.raises(SpendingBlocked, match='unreconciled'):
        request(reopened, lambda **kw: pytest.fail('crash reset allowance'))
    with pytest.raises(FileExistsError):
        reopened.initialize()


def test_external_charge_above_estimate_records_breach_and_blocks(guard):
    rid = guard.reserve('openai', 'test-model', .2)
    with pytest.raises(SpendingBlocked, match='exceeds reservation'):
        guard.begin_dispatch(rid)
        guard.finish(rid, actual='1.20', usage={'external_charge': 'synthetic'})
    snap = guard.snapshot()
    assert snap['requests'][0]['reported_micro_usd'] == 1200000
    # The guard detects this; it cannot undo a hypothetical $1.20 provider bill.
    with pytest.raises(SpendingBlocked):
        guard.reserve('tavily', 'basic', .01)


@pytest.mark.parametrize('broken', ['missing', 'corrupt', 'empty'])
def test_bad_ledger_never_resets_allowance(guard, broken):
    guard.path.unlink()
    if broken == 'corrupt': guard.path.write_bytes(b'not a sqlite file')
    if broken == 'empty': guard.path.write_bytes(b'')
    with pytest.raises(SpendingBlocked, match='ledger'):
        request(guard, lambda **kw: pytest.fail('bad ledger'))


def test_openai_cap_applies_to_both_request_paths_and_usage_precedes_json(guard):
    calls = []
    def send(**kwargs):
        calls.append(kwargs)
        return response(text='{}')
    p = provider(guard, send)
    p.complete('sys', 'input', {}, 'test-model')
    p.create_tool_response('sys', ['input'], [], 'test-model')
    assert all(x['max_output_tokens'] == 100 for x in calls)
    assert all(x['service_tier'] == 'default' for x in calls)
    assert all(x['reported_micro_usd'] == 11000 for x in guard.snapshot()['requests'])
    p._sdk.responses.create = lambda **kw: response(text='bad json')
    from src.llm.provider import LLMError
    with pytest.raises(LLMError, match='non-JSON'):
        p.complete('sys', 'input', {}, 'test-model')
    assert guard.snapshot()['requests'][-1]['state'] == 'reported'


def test_unbounded_request_or_hosted_tool_rejected(guard):
    with pytest.raises(SpendingBlocked, match='envelope'):
        guard.invoke_openai(lambda **kw: pytest.fail('large input'),
                            {'model':'test-model','input':'x'*5000})
    with pytest.raises(SpendingBlocked, match='hosted'):
        request(guard, lambda **kw: pytest.fail('hosted tool'), tools=[{'type':'web_search'}])
    assert guard.snapshot()['requests'] == []


@pytest.mark.parametrize('data', [{'results': []}, {'usage': None}, {'usage': []}, {'usage': {'credits': 2}},
                                  {'usage': {'credits': float('nan')}}])
def test_tavily_missing_or_excess_credit_usage_freezes(guard, data):
    with pytest.raises(SpendingBlocked):
        guard.invoke_tavily(lambda: data)
    assert guard.snapshot()['blocked']


def test_tavily_and_openai_share_one_allowance(guard):
    for _ in range(9):
        guard.invoke_tavily(lambda: {'usage': {'credits': 1}, 'results': []})
    with pytest.raises(SpendingBlocked, match='exhausted'):
        request(guard, lambda **kw: pytest.fail('cross-provider overspend'))
    assert sum(x['reserved_micro_usd'] for x in guard.snapshot()['requests']) == 900000


def test_tavily_timeout_reservation_not_released(guard):
    def timeout(): raise TimeoutError()
    with pytest.raises(SpendingBlocked): guard.invoke_tavily(timeout)
    assert guard.snapshot()['requests'][0]['reserved_micro_usd'] == 100000
    with pytest.raises(SpendingBlocked): guard.invoke_tavily(lambda: pytest.fail('retry'))


def test_sdk_retries_disabled(monkeypatch, guard):
    import openai
    calls = []
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: calls.append(kwargs) or SimpleNamespace())
    OpenAIProvider(api_key='offline-not-a-credential', guard=guard)
    assert calls[0]['max_retries'] == 0


def test_missing_live_policy_blocks_without_transport(monkeypatch, tmp_path):
    import src.storage.spending as spending
    monkeypatch.setattr(spending, 'POLICY_PATH', tmp_path / 'missing.json')
    p = provider(None, lambda **kw: pytest.fail('missing policy must not call provider'))
    with pytest.raises(SpendingBlocked, match='BLOCKED_COST_ENFORCEMENT'):
        p.complete('s', 'u', {}, 'test-model')


def test_tool_does_not_swallow_budget_block_or_fallback(monkeypatch, guard):
    from src.tools.search import web_search_tool
    monkeypatch.setenv('TAVILY_API_KEY', 'offline-not-a-credential')
    monkeypatch.setattr(SpendingGuard, 'default', classmethod(lambda cls: guard))
    monkeypatch.setattr('src.tools.search._open_tavily', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr('src.tools.search._search_duckduckgo', lambda *a: pytest.fail('provider fallback'))
    with pytest.raises(SpendingBlocked):
        web_search_tool().invoke({'query': 'q'})
    assert guard.snapshot()['blocked']


def test_orchestrator_preserves_blocked_reason(settings, store, guard):
    from src.orchestration.engine import Orchestrator
    p = provider(guard, lambda **kw: pytest.fail('unpriced model'))
    engine = Orchestrator(settings, store, client=p)
    pid = engine.create_project('offline objective')
    result = engine.run(pid)
    assert result['state'] == 'FAILED'
    assert 'BLOCKED_COST_ENFORCEMENT' in result['failure_reason']


@pytest.mark.parametrize('expiry', [None, 'invalid', '2020-01-01T00:00:00+00:00', '2099-01-01'])
def test_unreviewed_or_expired_cost_policy_blocks(tmp_path, expiry):
    data = policy()
    data['expires_at'] = expiry
    with pytest.raises(SpendingBlocked, match='review'):
        SpendingGuard(tmp_path / 'blocked.db', data)


def test_unknown_tavily_price_makes_no_request(tmp_path):
    data = policy()
    del data['tavily']
    with pytest.raises(SpendingBlocked):
        SpendingGuard(tmp_path / 'budget.db', data)
    assert not (tmp_path / 'budget.db').exists()
