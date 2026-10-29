"""Independent strict-schema and authorization tests; prices are synthetic."""
import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.storage.policy import PolicyError,validate_policy,load_policy_text,load_policy_file
from src.storage.spending import SpendingGuard,SpendingBlocked,digest
from src.llm.provider import OpenAIProvider


def valid_policy():
    return {
      'policy_schema_version':1,'state':'reviewed','experiment_id':'bounded-live-experiment-1',
      'currency':'USD','monetary_precision':6,'budget_micro_usd':1000000,
      'max_individual_reservation_micro_usd':500000,'max_aggregate_reserved_micro_usd':900000,
      'max_concurrent_requests':1,'max_sdk_retries':0,
      'evidence':'SYNTHETIC OFFLINE REVIEW DECLARATION; not actual verified provider rates',
      'expires_at':'2099-01-01T00:00:00+00:00',
      'pricing_references':{'openai':['https://openai.com/api/pricing/'],'tavily':['https://docs.tavily.com/documentation/api-credits']},
      'openai':{'v6-model':{'max_input_tokens':2000,'max_output_tokens':100,'max_request_bytes':3000,
           'input_token_overhead':256,'input_bound_mode':'utf8_text',
           'input_usd_per_million':'100','output_usd_per_million':'1000','pricing_status':'VERIFIED_OFFICIAL'}},
      'tavily':{'basic_search_max_usd':'0.1','usd_per_credit':'0.1','max_credits_per_search':1,'pricing_status':'VERIFIED_OFFICIAL'}}


def response():
    return SimpleNamespace(id='offline',output_text='{}',model='v6-model',service_tier='default',
                          usage=SimpleNamespace(input_tokens=1,output_tokens=1))

def adapter(g,send):
    p=object.__new__(OpenAIProvider);p.guard=g;p.fallback_model=None
    p.client=SimpleNamespace(responses=SimpleNamespace(create=send));return p

@pytest.fixture
def lab(tmp_path,monkeypatch):
    import src.storage.spending as module
    path=tmp_path/'policy.json';ledger=tmp_path/'ledger.db'
    monkeypatch.setattr(module,'POLICY_PATH',path);monkeypatch.setattr(module,'LEDGER_PATH',ledger)
    def build(data=None,initialize=True):
        data=valid_policy() if data is None else data
        path.write_text(json.dumps(data));g=SpendingGuard.default()
        if initialize:g.initialize()
        return g,path,ledger
    return build


def test_V01_supported_version(lab,evidence):
    g,path,ledger=lab(initialize=False)
    assert validate_policy(json.loads(path.read_text()),usable=True)['policy_schema_version']==1
    assert not ledger.exists()
    evidence.update(expected='valid supported policy accepted without activation',ledger_exists=ledger.exists())


@pytest.mark.parametrize('value',[2,999,'1','v1',1.0,True,None])
def test_V02_future_or_invalid_version(value,tmp_path,evidence):
    d=valid_policy();d['policy_schema_version']=value
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='reject unsupported/version type before any ledger or dispatch',value=value)


def test_V03_missing_version(tmp_path,evidence):
    d=valid_policy();del d['policy_schema_version']
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='legacy format rejected explicitly, no silent default')


def test_V04_unknown_root(tmp_path,evidence):
    d=valid_policy();d['future_billable_feature']=True
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='unknown root field rejected')


@pytest.mark.parametrize('target',['openai','tavily','references'])
def test_V05_unknown_nested(target,tmp_path,evidence):
    d=valid_policy()
    parent={'openai':d['openai']['v6-model'],'tavily':d['tavily'],'references':d['pricing_references']}[target]
    parent['unknown_field']=1
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='nested extra fields rejected',target=target)


def test_V06_misspelled_constraint(tmp_path,evidence):
    d=valid_policy();d['max_indvidual_reservation_micro_usd']=d.pop('max_individual_reservation_micro_usd')
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='misspelled safety field cannot become a default')


def test_V07_missing_budget(tmp_path,evidence):
    d=valid_policy();del d['budget_micro_usd']
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='required budget field rejected')


@pytest.mark.parametrize('field,value',[('budget_micro_usd','1000000'),('max_concurrent_requests',True),('max_sdk_retries',0.0),('openai',[]),('evidence',None)])
def test_V08_wrong_type(field,value,tmp_path,evidence):
    d=valid_policy();d[field]=value
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='strict type rejection',field=field)


@pytest.mark.parametrize('value',[-1,0,float('nan'),float('inf'),'Infinity',1000001])
def test_V09_invalid_budget(value,tmp_path,evidence):
    d=valid_policy();d['budget_micro_usd']=value
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='budget must be positive integer not above $1',value=str(value))


@pytest.mark.parametrize('value',[2,8,'6',True,6.0])
def test_V10_precision(value,tmp_path,evidence):
    d=valid_policy();d['monetary_precision']=value
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='only integer micro-USD precision supported',value=value)


@pytest.mark.parametrize('change',[{'budget_micro_usd':400000},{'max_individual_reservation_micro_usd':950000},{'max_individual_reservation_micro_usd':200000}])
def test_V11_contradictory_limits(change,tmp_path,evidence):
    d=valid_policy();d.update(change)
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='reject cap relationships or an operation maximum above individual cap',change=change)


def test_V11b_declared_limits_are_actually_enforced(lab,evidence):
    g,_,_=lab()
    with pytest.raises(SpendingBlocked):g.reserve('openai','v6-model','0.6')
    p=adapter(g,lambda **kw:response())
    for _ in range(3):p.complete('s','u',{},'v6-model')
    with pytest.raises(SpendingBlocked):g.invoke_tavily(lambda:pytest.fail('aggregate exceeds policy limit'))
    snap=g.snapshot();assert sum(r['reserved_micro_usd'] for r in snap['requests'])==900000
    evidence.update(expected='per-policy individual and aggregate ceilings, not only global $1',snapshot=snap)


@pytest.mark.parametrize('change',[{'max_sdk_retries':1},{'max_concurrent_requests':2},{'max_search_calls':1},{'max_tool_calls':2},{'max_application_retries':5}])
def test_V12_unsupported_constraint(change,tmp_path,evidence):
    d=valid_policy();d.update(change)
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='reject constraints not implemented by guard',change=change)


def test_V13_unknown_endpoint_or_model(lab,evidence):
    g,_,_=lab();calls=[];p=adapter(g,lambda **kw:calls.append(kw) or response())
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'unapproved-model')
    with pytest.raises(SpendingBlocked):p.client.chat.completions.create()
    d=valid_policy();d['openai']['v6-model']['endpoint']='https://unapproved.example/'
    with pytest.raises(SpendingBlocked):SpendingGuard(g.path,d)
    assert calls==[];evidence.update(expected='zero unknown operation/model sends',calls=len(calls))


@pytest.mark.parametrize('change',[{'input_usd_per_million':None},{'input_usd_per_million':'NaN'},{'input_usd_per_million':0},{'input_usd_per_million':0.1},{'pricing_status':'UNVERIFIED'},{'pricing_status':'PARTIALLY_VERIFIED'}])
def test_V14_unknown_or_unverified_price(change,tmp_path,evidence):
    d=valid_policy();d['openai']['v6-model'].update(change)
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='unverified/malformed rates cannot make usable policy',change=change)


def test_V14b_reference_and_unit_relations(tmp_path,evidence):
    d=valid_policy();d['pricing_references']['openai']=[]
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    d=valid_policy();d['pricing_references']['openai']=['https://unrelated.example/pricing']
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    d=valid_policy();d['tavily']['max_credits_per_search']=2
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',d)
    evidence.update(expected='provider-appropriate references and search-cost units are required')


@pytest.mark.parametrize('text',['{broken','[]','{"policy_schema_version":1,"policy_schema_version":999}','{"unknown":NaN}'])
def test_V15_malformed_policy(text,tmp_path,evidence):
    path=tmp_path/'bad.json';path.write_text(text)
    with pytest.raises(PolicyError):load_policy_file(path,usable=True)
    evidence.update(expected='malformed, duplicate, nonfinite or wrong-root JSON rejected',text=text)


def test_V16_invalid_production_loader(lab,evidence):
    g,path,_=lab();calls=[];d=valid_policy();d['max_sdk_retries']=1;path.write_text(json.dumps(d))
    p=adapter(None,lambda **kw:calls.append(kw) or response())
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v6-model')
    assert calls==[];evidence.update(expected='no default/fallback when production policy invalid',calls=len(calls))


def test_V17_invalid_programmatic_policy(lab,evidence):
    g,_,_=lab();g.policy['openai']['v6-model']['unpriced_option']=True
    calls=[];p=adapter(g,lambda **kw:calls.append(kw) or response())
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v6-model')
    with pytest.raises(SpendingBlocked):p.client.responses.create(model='v6-model',input='q')
    with pytest.raises(SpendingBlocked):g.invoke_tavily(lambda:calls.append('search'))
    assert calls==[];evidence.update(expected='invalid live object cannot bypass actual adapter/client/helper paths',calls=len(calls))


def test_V18_safe_legacy_requires_explicit_migration(tmp_path,evidence):
    d=valid_policy();legacy={k:d[k] for k in ['currency','evidence','expires_at','openai','tavily']}
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'never.db',legacy)
    # Explicitly reviewed test migration, not production auto-migration.
    migrated=valid_policy();assert validate_policy(migrated,usable=True)
    assert not (tmp_path/'never.db').exists()
    evidence.update(expected='legacy rejected; explicit reviewed format accepted without activation',auto_migration=False)


def test_V19_inactive_draft_structural_validation(tmp_path,evidence):
    from src.storage.spending import POLICY_PATH,LEDGER_PATH
    before=(POLICY_PATH.exists(),LEDGER_PATH.exists())
    d=json.loads(Path('policy_v5/canonical_budget_policy.draft.json').read_text())
    assert validate_policy(d,usable=False)
    with pytest.raises(SpendingBlocked):SpendingGuard(tmp_path/'draft.db',d)
    raw=object.__new__(SpendingGuard);raw.path=tmp_path/'draft.db';raw.policy=d;raw.digest=digest(d)
    with pytest.raises(SpendingBlocked):raw.initialize()
    assert not raw.path.exists() and before==(POLICY_PATH.exists(),LEDGER_PATH.exists())==(False,False)
    evidence.update(SCHEMA_VALID=True,ENFORCEMENT_VALID=True,PRICING_COMPLETE=False,ACTIVATION_AUTHORIZED=False,production_files_unchanged=True)


@pytest.mark.parametrize('mode',['missing','corrupt','version','draft'])
def test_V20_missing_or_incompatible_during_authorization(lab,mode,evidence):
    g,path,_=lab();calls=[]
    if mode=='missing':path.unlink()
    elif mode=='corrupt':path.write_text('{')
    else:
        d=valid_policy();d.update({'policy_schema_version':999} if mode=='version' else {'state':'draft'})
        path.write_text(json.dumps(d))
    with pytest.raises(SpendingBlocked):adapter(None,lambda **kw:calls.append(kw) or response()).complete('s','u',{},'v6-model')
    assert calls==[];evidence.update(expected='zero dispatch on missing/incompatible policy',mode=mode,calls=len(calls))


def test_V11c_lower_budget_is_not_replaced_by_global_cap(lab,evidence):
    d=valid_policy();d.update(budget_micro_usd=500000,max_aggregate_reserved_micro_usd=500000,max_individual_reservation_micro_usd=400000)
    g,_,_=lab(d);adapter(g,lambda **kw:response()).complete('s','u',{},'v6-model')
    for _ in range(2):g.invoke_tavily(lambda:{'usage':{'credits':1}})
    with pytest.raises(SpendingBlocked):g.invoke_tavily(lambda:pytest.fail('policy budget exceeded'))
    snap=g.snapshot();assert sum(r['reserved_micro_usd'] for r in snap['requests'])==500000
    evidence.update(expected='a supported lower policy budget is enforced exactly',snapshot=snap)


def test_V14c_search_units_enforced_even_inside_monetary_reservation(lab,evidence):
    d=valid_policy();d['tavily']['basic_search_max_usd']='0.2'
    g,_,_=lab(d)
    with pytest.raises(SpendingBlocked):g.invoke_tavily(lambda:{'usage':{'credits':1.5}})
    snap=g.snapshot();assert snap['blocked'] and snap['requests'][0]['reported_micro_usd']==150000
    assert snap['requests'][0]['reserved_micro_usd']==200000
    evidence.update(expected='unit constraint cannot be ignored merely because monetary reserve fits',snapshot=snap)
