"""Second implementation review: fault injection beyond A01-A20."""
import json,sqlite3
from decimal import Decimal,localcontext
from fractions import Fraction
from types import SimpleNamespace
import pytest
from src.storage.spending import SpendingGuard,SpendingBlocked,micros,token_cost
from audit_v4.test_v4_adversarial import lab,guard,policy,reply,make_provider,api_response,assert_reserved


def test_R01_request_snapshot_prevents_toctou(guard,monkeypatch,evidence):
    original={'model':'v4-model','input':[{'role':'user','content':'original'}]}
    reserve=guard.reserve;seen=[]
    def mutate(*args):
        rid=reserve(*args)
        original['input'][0]['content']='mutated after reservation'
        return rid
    monkeypatch.setattr(guard,'reserve',mutate)
    guard.invoke_openai(lambda **kw:seen.append(kw['input'][0]['content']) or reply(),original)
    evidence.update(expected='wire payload uses validated deep snapshot',seen=seen)
    assert seen==['original']


def test_R02_reservation_cannot_be_reused(guard,evidence):
    rid=guard.reserve('openai','v4-model',.4);guard.begin_dispatch(rid)
    with pytest.raises(SpendingBlocked):guard.begin_dispatch(rid)
    guard.finish(rid,.001015,{'input_tokens':1,'output_tokens':1})
    with pytest.raises(SpendingBlocked):guard.begin_dispatch(rid)
    with pytest.raises(SpendingBlocked):guard.finish(rid,.001015,{'input_tokens':1,'output_tokens':1})
    evidence.update(expected='one legal dispatch transition and settlement',snapshot=guard.snapshot())


def test_R03_failed_before_dispatch_retains_allowance(guard,evidence):
    for _ in range(2):
        rid=guard.reserve('openai','v4-model',.4);guard.fail_before_dispatch(rid)
    with pytest.raises(SpendingBlocked):guard.reserve('openai','v4-model',.4)
    evidence.update(expected='local pre-send failures distinguished, no automatic refund',snapshot=guard.snapshot())
    assert all(r['state']=='failed_before_dispatch' for r in guard.snapshot()['requests'])


def test_R04_extreme_reported_cost_preserved_without_integer_overflow(guard,evidence):
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:reply(10**30,10**30)).complete('s','u',{},'v4-model')
    snap=guard.snapshot();usage=json.loads(snap['requests'][0]['usage'])
    evidence.update(expected='out-of-range discrepancy preserved as string; further spending frozen',snapshot=snap)
    assert snap['blocked'] and snap['requests'][0]['reported_micro_usd'] is None
    assert int(usage['estimated_micro_usd_out_of_range'])>2**63-1


def test_R05_exact_ceiling_arithmetic_is_context_independent(evidence):
    with localcontext() as ctx:
        ctx.prec=2
        assert micros(token_cost(1,Decimal('1.000000000000000000000000000001'),0,Decimal('1')))==2
        assert micros(Fraction(1,10**40))==1
    evidence.update(expected='exact rational math, never round a positive fraction down',micro_values=[2,1])


def test_R06_actual_constructor_disables_redirects_and_retries(guard,monkeypatch,evidence):
    import openai
    from openai import _base_client
    h=_base_client.httpx2;real=openai.DefaultHttpxClient;calls=[]
    def send(req):assert_reserved(guard,'openai');calls.append(True);return api_response(h)
    monkeypatch.setattr(openai,'DefaultHttpxClient',lambda **kwargs:real(transport=h.MockTransport(send),**kwargs))
    p=openai_provider=__import__('src.llm.provider',fromlist=['OpenAIProvider']).OpenAIProvider(api_key='offline-not-a-credential',guard=guard)
    try:
        assert p._sdk.max_retries==0 and not p._sdk._client.follow_redirects
        p.complete('s','u',{},'v4-model')
    finally:p._sdk.close()
    evidence.update(expected='factory defaults are safe, not just manually injected SDKs',calls=len(calls))
    assert len(calls)==1


def test_R07_unreviewed_sdk_endpoint_rejected(guard,evidence):
    from openai import OpenAI,DefaultHttpxClient,_base_client
    h=_base_client.httpx2;calls=[]
    sdk=OpenAI(api_key='offline-not-a-credential',base_url='https://example.com/v1',max_retries=0,
       http_client=DefaultHttpxClient(follow_redirects=False,transport=h.MockTransport(lambda req:calls.append(req) or api_response(h))))
    try:
        with pytest.raises(SpendingBlocked,match='endpoint'):guard.invoke_openai(sdk.responses.create,{'model':'v4-model','input':'q'})
    finally:sdk.close()
    evidence.update(expected='pricing bound cannot authorize a different endpoint',calls=len(calls))
    assert calls==[]


@pytest.mark.parametrize('mode',['missing_contract','provider_context','malformed_evidence'])
def test_R08_hidden_context_requires_reviewed_bound(lab,mode,evidence):
    data=policy()
    if mode in {'provider_context','malformed_evidence'}:
        p=data['openai']['v4-model'];p.update(input_bound_mode='provider_context',provider_context_tokens=20000,context_evidence='synthetic full-context contract' if mode=='provider_context' else True)
    if mode=='malformed_evidence':
        with pytest.raises(SpendingBlocked):lab(data)
        evidence.update(expected='malformed context evidence rejected before usable policy')
        return
    g=lab(data);calls=[]
    kwargs={'model':'v4-model','input':[{'type':'reasoning','id':'offline','summary':[]}]}
    if mode!='provider_context':
        with pytest.raises(SpendingBlocked):g.invoke_openai(lambda **kw:calls.append(kw) or reply(),kwargs)
        assert calls==[]
    else:
        g.invoke_openai(lambda **kw:calls.append(kw) or reply(),kwargs);assert len(calls)==1
    evidence.update(expected='opaque reasoning only with explicit full provider context bound',mode=mode,calls=len(calls))


@pytest.mark.parametrize('field',['model','service_tier'])
def test_R09_unknown_returned_billing_identity_is_not_priced_as_requested(guard,field,evidence):
    def send(**kw):
        r=reply();setattr(r,field,'unpriced');return r
    with pytest.raises(SpendingBlocked):make_provider(guard,send).complete('s','u',{},'v4-model')
    snap=guard.snapshot()
    evidence.update(expected='preserve unknown cost, not falsely reconcile at requested price',snapshot=snap)
    assert snap['requests'][0]['reported_micro_usd'] is None and snap['blocked']


def test_R10_seeded_reservation_sequences(guard,evidence):
    rng=__import__('random').Random(47219);accepted=0
    for _ in range(100):
        amount=rng.randint(1,200000)
        try:rid=guard.reserve('openai','v4-model',Fraction(amount,1000000))
        except SpendingBlocked:continue
        guard.fail_before_dispatch(rid);accepted+=amount
        assert accepted<=1000000
    evidence.update(expected='100 deterministic fault-free admissions retain aggregate cap',reserved_micro_usd=accepted,snapshot=guard.snapshot())


def test_R11_duplicate_reservation_identifier_rolls_back(guard,monkeypatch,evidence):
    import src.storage.spending as module
    rid=guard.reserve('openai','v4-model',.1);guard.fail_before_dispatch(rid)
    before=guard.snapshot()
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex=rid))
    with pytest.raises(SpendingBlocked):guard.reserve('openai','v4-model',.1)
    evidence.update(expected='duplicate identifier cannot overwrite exposure',snapshot=guard.snapshot())
    assert guard.snapshot()==before


def test_R12_reported_usage_must_match_derived_cost(guard,evidence):
    make_provider(guard,lambda **kw:reply()).complete('s','u',{},'v4-model')
    with sqlite3.connect(guard.path) as db:db.execute('UPDATE requests SET actual=0')
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:pytest.fail('inconsistent cost')).complete('s','u',{},'v4-model')
    evidence.update(expected='valid-looking monetary field cannot contradict usage',snapshot=guard.snapshot())
    assert guard.snapshot()['integrity_error']
