"""Inactive mini-only policy checks using supplied public rates and mock sends."""
import copy
import json
import socket
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.llm.provider import OpenAIProvider
from src.storage.policy import load_policy_file, validate_policy, PolicyError
from src.storage.spending import SpendingGuard, SpendingBlocked, digest, micros, token_cost, POLICY_PATH, LEDGER_PATH

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / 'policy_v5/canonical_budget_policy.draft.json'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs): raise AssertionError('real network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    import src.storage.spending as module
    # This test-only copy simulates approval of the supplied public schedule.
    # Neither this state nor its temporary ledger is a production activation.
    d = copy.deepcopy(load_policy_file(DRAFT))
    d.update(state='reviewed', expires_at='2099-01-01T00:00:00+00:00')
    p, ledger = tmp_path/'policy.json', tmp_path/'ledger.sqlite3'
    p.write_text(json.dumps(d))
    monkeypatch.setattr(module, 'POLICY_PATH', p)
    monkeypatch.setattr(module, 'LEDGER_PATH', ledger)
    g = SpendingGuard.default(); g.initialize()
    return g


def test_draft_only_mini_and_no_active_allowance(tmp_path):
    before = (POLICY_PATH.exists(), LEDGER_PATH.exists())
    d = load_policy_file(DRAFT)
    assert d['state'] == 'draft' and d['budget_micro_usd'] == 1_000_000
    assert d['max_concurrent_requests'] == 1 and d['max_sdk_retries'] == 0
    assert set(d['openai']) == {'gpt-5.4-mini'} and d['tavily'] is None
    assert d['max_individual_reservation_micro_usd'] == d['max_aggregate_reserved_micro_usd'] == 330634
    identity = json.loads((ROOT/'policy_v5/draft_identity.json').read_text())
    assert identity['effective_guard_policy_sha256'] == digest(d)
    assert identity['activation_ready'] is False and identity['eligible_live_operations'] == []
    with pytest.raises(PolicyError): load_policy_file(DRAFT, usable=True)
    with pytest.raises(SpendingBlocked): SpendingGuard(tmp_path/'must-not-exist.sqlite3', d)
    assert not (tmp_path/'must-not-exist.sqlite3').exists()
    assert before == (POLICY_PATH.exists(), LEDGER_PATH.exists()) == (False, False)


def test_empty_policy_still_rejects_even_with_review_metadata():
    d = load_policy_file(DRAFT)
    d.update(openai={}, state='reviewed', evidence='Synthetic empty-policy test',
             expires_at='2099-01-01T00:00:00+00:00')
    with pytest.raises(PolicyError, match='no supported operation'):
        validate_policy(d, usable=True)


def test_supplied_rates_reserve_full_context_plus_reasoning_and_uplift():
    e = json.loads((ROOT/'policy_v7/followup/user_supplied_pricing.json').read_text())['openai']['gpt-5.4-mini']
    d = load_policy_file(DRAFT); p = d['openai']['gpt-5.4-mini']
    assert Fraction(p['input_usd_per_million']) == Fraction(e['input_usd_per_million'])*Fraction('1.10')
    assert Fraction(p['output_usd_per_million']) == Fraction(e['output_usd_per_million'])*Fraction('1.10')
    assert p['provider_context_tokens'] == p['max_input_tokens'] == e['context_tokens'] == 400000
    assert p['input_bound_mode'] == 'provider_context'
    assert p['max_output_tokens'] == 128 <= e['maximum_output_tokens']
    assert token_cost(400000, Fraction('0.825'), 128, Fraction('4.95')) == Fraction('0.3306336')
    assert micros(Fraction('0.3306336')) == 330634


def test_actual_adapter_one_attempt_and_no_refund(isolated):
    g = isolated; calls = []
    def send(**kw):
        calls.append(kw)
        assert kw['max_output_tokens'] == 128 and kw['service_tier'] == 'default'
        return SimpleNamespace(model='gpt-5.4-mini', service_tier='default', output_text='{"ok":true}',
                               usage=SimpleNamespace(input_tokens=399872, output_tokens=128))
    p = object.__new__(OpenAIProvider)
    p.guard = g; p.fallback_model = None
    p.client = SimpleNamespace(responses=SimpleNamespace(create=send))
    schema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    assert p.complete('Return JSON.', 'Return {"ok":true}.', schema, 'gpt-5.4-mini')[0] == {'ok':True}
    with pytest.raises(SpendingBlocked):
        p.complete('Return JSON.', 'another attempt', {}, 'gpt-5.4-mini')
    assert len(calls) == 1
    row = g.snapshot()['requests'][0]
    assert row['reserved_micro_usd'] == 330634 and row['reported_micro_usd'] == 330528


def test_terra_and_tavily_cannot_dispatch(isolated):
    g = isolated
    with pytest.raises(SpendingBlocked):
        g.invoke_openai(lambda **kw: pytest.fail('terra dispatch'), {'model':'gpt-5.6-terra','input':'q'})
    with pytest.raises(SpendingBlocked):
        g.invoke_tavily(lambda: pytest.fail('Tavily dispatch'))
    assert not g.snapshot()['requests']


@pytest.mark.parametrize('option', [
    {'tools':[{'type':'web_search'}]},
    {'prompt_cache_options':{'ttl':'12h'}},
    {'service_tier':'priority'},
    {'max_output_tokens':129},
    {'input':'x'*4097},
])
def test_unpriced_or_oversized_options_rejected(isolated, option):
    with pytest.raises(SpendingBlocked):
        isolated.invoke_openai(lambda **kw: pytest.fail('unsupported dispatch'),
                               {'model':'gpt-5.4-mini','input':'q',**option})
    assert not isolated.snapshot()['requests']


def test_terra_full_context_exceeds_one_dollar_even_without_cache():
    assert token_cost(1050000,Fraction('4'),128,Fraction('18')) == Fraction('4.202304')
    d = load_policy_file(DRAFT)
    p = copy.deepcopy(d['openai']['gpt-5.4-mini'])
    p.update(max_input_tokens=1050000,provider_context_tokens=1050000,
             input_usd_per_million='4',output_usd_per_million='18')
    d['openai']={'gpt-5.6-terra':p}
    d['max_individual_reservation_micro_usd']=d['max_aggregate_reserved_micro_usd']=1000000
    with pytest.raises(PolicyError,match='model maximum exceeds'):
        validate_policy(d)
