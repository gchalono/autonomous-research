"""Targeted policy compatibility tests; synthetic prices do not verify live rates."""

from tests.policy_fixtures import reviewed_fixture
import concurrent.futures,copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.storage.spending import SpendingGuard,SpendingBlocked,POLICY_PATH,LEDGER_PATH
from src.llm.provider import OpenAIProvider
DRAFT=Path(__file__).with_name('canonical_budget_policy.draft.json')


def synthetic_policy():
    return reviewed_fixture({'currency':'USD','expires_at':'2099-01-01T00:00:00+00:00',
      'evidence':'SYNTHETIC FIXTURE ONLY, not official or account-specific pricing',
      'openai':{'fixture-model':{'max_input_tokens':1000,'max_output_tokens':100,'max_request_bytes':4000,
       'input_token_overhead':256,'input_bound_mode':'utf8_text','input_usd_per_million':300,'output_usd_per_million':1000}},
      'tavily':{'basic_search_max_usd':.1,'usd_per_credit':.1}})

@pytest.fixture
def fixture_policy(tmp_path,monkeypatch):
    import src.storage.spending as module
    def make(data=None):
        path=tmp_path/'isolated-policy.json';ledger=tmp_path/'isolated-ledger.db'
        data=synthetic_policy() if data is None else data
        path.write_text(json.dumps(data));monkeypatch.setattr(module,'POLICY_PATH',path);monkeypatch.setattr(module,'LEDGER_PATH',ledger)
        guard=SpendingGuard.default();guard.initialize()  # isolated synthetic ledger ONLY
        return guard,path,ledger
    return make


def response():
    return SimpleNamespace(id='fixture',model='fixture-model',service_tier='default',output_text='{}',
                          usage=SimpleNamespace(input_tokens=1,output_tokens=1))

def adapter(g,send):
    p=object.__new__(OpenAIProvider);p.guard=g;p.fallback_model=None
    p.client=SimpleNamespace(responses=SimpleNamespace(create=send));return p

def invoke(g,send=None,**kwargs):
    return g.invoke_openai(send or (lambda **kw:response()),dict(model='fixture-model',input='q',**kwargs))


def test_P01_canonical_complete_policy_loading_is_blocked(fixture_policy,evidence):
    data=json.loads(DRAFT.read_text())
    with pytest.raises(SpendingBlocked) as err:SpendingGuard(DRAFT.with_suffix('.db'),data)
    g,path,ledger=fixture_policy()
    assert SpendingGuard.default().digest==g.digest
    evidence.update(expected='canonical complete reviewed policy accepted in isolation',actual_draft_rejection=str(err.value),synthetic_loader='accepted, does not validate live policy')
    pytest.skip('BLOCKED: canonical draft has no authoritative rates/bounds; synthetic loader compatibility only')


def test_P02_missing_pricing(fixture_policy,evidence):
    data=synthetic_policy();del data['openai']['fixture-model']['input_usd_per_million']
    with pytest.raises(SpendingBlocked):fixture_policy(data)
    evidence.update(expected='missing price prevents policy loading before dispatch',rejected_at='production loader')


def test_P03_unknown_model(fixture_policy,evidence):
    g,_,_=fixture_policy()
    with pytest.raises(SpendingBlocked):g.invoke_openai(lambda **kw:pytest.fail('unknown model'),{'model':'unapproved','input':'q'})
    evidence.update(expected='unapproved model never dispatches',requests=g.snapshot()['requests'])
    assert g.snapshot()['requests']==[]


def test_P04_unknown_endpoint(fixture_policy,evidence):
    from openai import OpenAI,DefaultHttpxClient,_base_client
    g,_,_=fixture_policy();h=_base_client.httpx2;calls=[]
    sdk=OpenAI(api_key='offline-not-a-credential',base_url='https://example.com/v1',max_retries=0,
      http_client=DefaultHttpxClient(follow_redirects=False,transport=h.MockTransport(lambda req:calls.append(req))))
    try:
        with pytest.raises(SpendingBlocked):g.invoke_openai(sdk.responses.create,{'model':'fixture-model','input':'q'})
    finally:sdk.close()
    evidence.update(expected='unapproved endpoint blocked before SDK transport',calls=len(calls))
    assert calls==[]


def test_P05_oversized_input(fixture_policy,evidence):
    g,_,_=fixture_policy()
    with pytest.raises(SpendingBlocked):invoke(g,lambda **kw:pytest.fail('oversized dispatch'),instructions='x'*1001)
    evidence.update(expected='reject before dispatch',requests=g.snapshot()['requests'])
    assert g.snapshot()['requests']==[]


def test_P06_output_limit(fixture_policy,evidence):
    g,_,_=fixture_policy();calls=[]
    with pytest.raises(SpendingBlocked):invoke(g,lambda **kw:pytest.fail('override'),max_output_tokens=99999)
    invoke(g,lambda **kw:calls.append(kw['max_output_tokens']) or response())
    evidence.update(expected='caller cannot override; actual guarded request capped',output_caps=calls)
    assert calls==[100]


def test_P07_retry_after_unknown_completion(fixture_policy,evidence):
    g,_,_=fixture_policy();calls=[]
    def timeout(**kw):calls.append(True);raise TimeoutError()
    for _ in range(2):
        with pytest.raises(SpendingBlocked):invoke(g,timeout)
    evidence.update(expected='ambiguous outcome retains exposure; retry denied',calls=len(calls),snapshot=g.snapshot())
    assert len(calls)==1


def test_P08_cumulative_ceiling(fixture_policy,evidence):
    g,_,_=fixture_policy()
    for _ in range(2):invoke(g)  # synthetic maximum $0.40 each
    with pytest.raises(SpendingBlocked):invoke(g,lambda **kw:pytest.fail('excess allowance'))
    evidence.update(expected='third $0.40 rejected against $1 shared allowance',snapshot=g.snapshot())
    assert sum(r['reserved_micro_usd'] for r in g.snapshot()['requests'])==800000


def test_P09_concurrent_capacity(fixture_policy,evidence):
    g,_,_=fixture_policy()
    def attempt(_):
        try:invoke(g);return True
        except SpendingBlocked:return False
    with concurrent.futures.ThreadPoolExecutor(8) as pool:outcomes=list(pool.map(attempt,range(16)))
    snap=g.snapshot();evidence.update(expected='atomic admission stays within $1',accepted=sum(outcomes),snapshot=snap)
    assert 1<=sum(outcomes)<=2 and sum(r['reserved_micro_usd'] for r in snap['requests'])<=1000000


def test_P10_unknown_billing_option(fixture_policy,evidence):
    g,_,_=fixture_policy()
    with pytest.raises(SpendingBlocked):invoke(g,lambda **kw:pytest.fail('unpriced hosted tool'),tools=[{'type':'web_search'}])
    with pytest.raises(SpendingBlocked):invoke(g,lambda **kw:pytest.fail('override'),extra_body={'service_tier':'priority'})
    evidence.update(expected='unpriced operation rejected',requests=g.snapshot()['requests'])
    assert g.snapshot()['requests']==[]


def test_P11_unapproved_fallback(fixture_policy,evidence):
    g,_,_=fixture_policy()
    p=adapter(g,lambda **kw:pytest.fail('unknown fallback dispatched'))
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'unapproved-fallback')
    evidence.update(expected='alternate model requires its own entry',requests=g.snapshot()['requests'])
    assert g.snapshot()['requests']==[]


def test_P12_missing_or_corrupt_policy(fixture_policy,evidence):
    g,path,_=fixture_policy();p=adapter(None,lambda **kw:pytest.fail('bad policy dispatch'))
    path.unlink()
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'fixture-model')
    path.write_text('{corrupt json')
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'fixture-model')
    evidence.update(expected='missing/corrupt file blocks without initialization',requests=g.snapshot()['requests'])
    assert g.snapshot()['requests']==[]


def test_P13_draft_inactive(evidence):
    before=(POLICY_PATH.exists(),LEDGER_PATH.exists())
    with pytest.raises(SpendingBlocked):SpendingGuard(LEDGER_PATH,json.loads(DRAFT.read_text()))
    after=(POLICY_PATH.exists(),LEDGER_PATH.exists())
    evidence.update(expected='reading draft creates no live policy/allowance',before=before,after=after)
    assert after==before==(False,False)


def test_P14_new_run_cannot_reset_pool(fixture_policy,evidence):
    g,_,_=fixture_policy();calls=[]
    for n in range(3):
        p=adapter(None,lambda **kw:calls.append(True) or response())
        try:p.complete('s',f'run-{n}',{},'fixture-model')
        except SpendingBlocked:pass
    evidence.update(expected='new caller/run label shares existing canonical allowance',calls=len(calls),snapshot=g.snapshot())
    assert len(calls)==2 and len(g.snapshot()['requests'])==2


def test_P15_documented_maximum_cost_is_blocked(fixture_policy,evidence):
    g,_,_=fixture_policy();invoke(g)
    g.invoke_tavily(lambda:{'usage':{'credits':1}})
    snap=g.snapshot();assert [r['reserved_micro_usd'] for r in snap['requests']]==[400000,100000]
    evidence.update(expected='each production maximum covers documented official bound',synthetic_arithmetic_micro_usd=[400000,100000],official_production_bounds='unavailable')
    pytest.skip('BLOCKED: no official production rates/units/input contracts; synthetic arithmetic is not provider evidence')


@pytest.mark.parametrize('unsupported_field',[{'unapproved_policy_field':True},{'policy_schema_version':999}])
def test_Q01_unknown_policy_fields_or_versions_rejected(tmp_path,unsupported_field,evidence):
    data=synthetic_policy();data.update(unsupported_field)
    evidence.update(expected='strict policy loader rejects unknown fields/version',injected_fields=unsupported_field)
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never-initialized.db',data)
