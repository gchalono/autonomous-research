"""Assessment-only synthetic fixture, actual provider/SDK/guard dispatch path."""
import json
from types import SimpleNamespace
import pytest
from openai import OpenAI,DefaultHttpxClient,_base_client
from src.llm.provider import OpenAIProvider
from src.agents.executor import run_execution_native,SUBMIT_REPORT_NAME
from src.tools.base import ToolRegistry
from src.storage.spending import SpendingGuard,SpendingBlocked
from tests.policy_fixtures import reviewed_fixture

@pytest.fixture
def lab(tmp_path,monkeypatch):
    import src.storage.spending as module
    p=reviewed_fixture({'currency':'USD','expires_at':'2099-01-01T00:00:00+00:00','evidence':'SYNTHETIC V10 guarded integration fixture, not real account rates',
      'openai':{'fixture-model':{'max_input_tokens':20000,'max_output_tokens':100,'max_request_bytes':24000,'input_token_overhead':256,'input_bound_mode':'utf8_text','input_usd_per_million':'10','output_usd_per_million':'10'}},'tavily':None})
    p.update(max_individual_reservation_micro_usd=201000,max_aggregate_reserved_micro_usd=201000)
    path=tmp_path/'policy.json';path.write_text(json.dumps(p))
    monkeypatch.setattr(module,'POLICY_PATH',path);monkeypatch.setattr(module,'LEDGER_PATH',tmp_path/'ledger.sqlite3')
    g=SpendingGuard.default();g.initialize();yield g

def make(g,handler,base='https://api.openai.com/v1',retries=0):
    h=_base_client.httpx2
    sdk=OpenAI(api_key='offline-test-not-a-credential',base_url=base,max_retries=retries,http_client=DefaultHttpxClient(follow_redirects=False,transport=h.MockTransport(handler)))
    p=object.__new__(OpenAIProvider);p.guard=g;p.client=sdk;p.fallback_model=None
    return p,sdk

def reply(req,usage=True):
    report={'executive_summary':'SYNTHETIC','findings':[],'claims':[],'sources':[],'limitations':[],'unresolved_dependencies':[]}
    return _base_client.httpx2.Response(200,json={'id':'offline','object':'response','created_at':0,'status':'completed','model':'fixture-model','service_tier':'default',
      'output':[{'type':'function_call','call_id':'offline-call','name':SUBMIT_REPORT_NAME,'arguments':json.dumps(report)}],
      'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2} if usage else None})

def test_forced_turn_has_reservation_at_actual_sdk_dispatch(lab):
    seen=[];cost=[]
    def send(req):
        row=lab.snapshot()['requests'][0];assert row['state']=='dispatching' and row['reserved_micro_usd']==201000
        data=json.loads(req.content);assert data['tool_choice']=={'type':'function','name':SUBMIT_REPORT_NAME}
        assert data['service_tier']=='default' and data['max_output_tokens']==100
        seen.append(data);return reply(req)
    p,sdk=make(lab,send)
    try:
        r=run_execution_native(p,'fixture-model',['SPEC'],ToolRegistry(),max_iterations=1,cost_cb=lambda *a,**k:cost.append(k.get('preflight',False)))
        assert r.executive_summary=='SYNTHETIC' and cost==[True,False] and len(seen)==1
        with pytest.raises(SpendingBlocked):run_execution_native(p,'fixture-model',['SPEC'],ToolRegistry(),max_iterations=1)
        assert len(seen)==1
    finally:sdk.close()

@pytest.mark.parametrize('variant',['no_reservation','unknown_model','unknown_endpoint','unpriced_tool','sdk_retry'])
def test_invalid_combined_path_zero_dispatch(lab,variant):
    calls=[]
    p,sdk=make(lab,lambda r:calls.append(r),base='https://example.com/v1' if variant=='unknown_endpoint' else 'https://api.openai.com/v1',retries=2 if variant=='sdk_retry' else 0)
    if variant=='no_reservation':
        lab.path.unlink() # absent fixture ledger cannot auto-provision at dispatch
    try:
        with pytest.raises(SpendingBlocked):
            p.create_tool_response('s',[{'role':'user','content':'u'}],[{'type':'web_search'}] if variant=='unpriced_tool' else [],'unknown' if variant=='unknown_model' else 'fixture-model',tool_choice={'type':'function','name':SUBMIT_REPORT_NAME})
        assert calls==[]
    finally:sdk.close()

@pytest.mark.parametrize('failure',['schema_error','model_not_found','missing_usage'])
def test_ambiguous_failure_no_fallback_and_retained_reservation(lab,failure):
    calls=[]
    def send(req):
        calls.append(req)
        if failure=='missing_usage':return reply(req,False)
        return _base_client.httpx2.Response(400 if failure=='schema_error' else 404,json={'error':{'message':'schema rejected' if failure=='schema_error' else 'model not found','type':'invalid_request_error'}})
    p,sdk=make(lab,send);p.fallback_model='unapproved-model'
    try:
        with pytest.raises(SpendingBlocked):
            p.create_tool_response('s',[{'role':'user','content':'u'}],[{'type':'function','name':'f','strict':True,'parameters':{'type':'object','properties':{}}}],'fixture-model')
        assert len(calls)==1 and lab.snapshot()['blocked']
        assert lab.snapshot()['requests'][0]['reserved_micro_usd']==201000
    finally:sdk.close()


def test_freeform_route_still_goes_through_guard_and_json_validation(lab):
    from src.models.contracts import ExecutorStep
    from src.agents.common import call_agent,AgentOutputError
    calls=[]
    def send(req):
        data=json.loads(req.content);calls.append(data)
        assert data['text']['format']=={'type':'json_object'} and 'json' in data['input'].lower()
        body={'id':'offline','object':'response','created_at':0,'model':'fixture-model','service_tier':'default','status':'completed','output':[{'type':'message','id':'m','status':'completed','role':'assistant','content':[{'type':'output_text','text':'{"done":"invalid-bool"}','annotations':[]}]}],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
        return _base_client.httpx2.Response(200,json=body)
    p,sdk=make(lab,send)
    try:
        with pytest.raises(SpendingBlocked):call_agent(p,'fixture-model','s','u',ExecutorStep)
        assert len(calls)==1 # invalid receive-side value initiates repair; second reservation denied
    finally:sdk.close()


def test_literal_property_names_not_newly_stripped():
    from src.llm.provider import make_strict_schema
    d={'type':'object','properties':{'minimum':{'type':'integer'},'format':{'type':'string'}},'required':['minimum','format']}
    assert set(make_strict_schema(d)['properties'])=={'minimum','format'}
