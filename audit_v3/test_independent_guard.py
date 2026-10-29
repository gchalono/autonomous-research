"""Independent V3 tests; fixture prices never authorize a real request.

Failures assert desired controls and intentionally expose unchanged defects.
"""

from tests.policy_fixtures import reviewed_fixture
import concurrent.futures
import json
import multiprocessing
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.storage.spending import SpendingGuard,SpendingBlocked
from src.llm.provider import OpenAIProvider


def policy():
    return reviewed_fixture({'currency':'USD','evidence':'synthetic V3 audit policy, not verified pricing',
      'expires_at':'2099-01-01T00:00:00+00:00',
      'openai':{'audit-model':{'max_input_tokens':1000,'max_output_tokens':100,
        'max_request_bytes':10000,'input_usd_per_million':500,'output_usd_per_million':1000}},
      'tavily':{'basic_search_max_usd':.1,'usd_per_credit':.1}})

@pytest.fixture
def guard(tmp_path,monkeypatch):
    g=SpendingGuard(tmp_path/'session.sqlite3',policy());g.initialize()
    import src.storage.spending as module
    policy_path=tmp_path/'policy.json';policy_path.write_text(json.dumps(policy()))
    monkeypatch.setattr(module,'LEDGER_PATH',g.path);monkeypatch.setattr(module,'POLICY_PATH',policy_path)
    return g

def resp(i=10,o=10):
    return SimpleNamespace(id='mock-response',output_text='{}',output=[],
      usage=SimpleNamespace(input_tokens=i,output_tokens=o),model='audit-model',service_tier='default')

def invoke(g,send=None,**kwargs):
    return g.invoke_openai(send or (lambda **kw:resp()),dict(model='audit-model',input='question',**kwargs))

def mock_provider(g,send):
    p=object.__new__(OpenAIProvider);p.guard=g;p.fallback_model=None
    p.client=SimpleNamespace(responses=SimpleNamespace(create=send));return p

def crash_worker(path,after_dispatch,marker):
    import src.storage.spending as module
    module.LEDGER_PATH=Path(path);module.POLICY_PATH=Path(path).parent/'policy.json'
    g=SpendingGuard(path,policy())
    if not after_dispatch:
        g.reserve('openai','audit-model',.6)
        os._exit(17)
    def accept(**kwargs):
        Path(marker).write_text('mock provider accepted request')
        os._exit(18)
    invoke(g,accept)

def race_worker(path,barrier,queue):
    import src.storage.spending as module
    module.LEDGER_PATH=Path(path);module.POLICY_PATH=Path(path).parent/'policy.json'
    g=SpendingGuard(path,policy());barrier.wait(timeout=10)
    try:
        invoke(g);queue.put('accepted')
    except SpendingBlocked:
        queue.put('blocked')


def test_T01_budget_exhaustion_before_dispatch(guard,evidence):
    invoke(guard);calls=[]
    with pytest.raises(SpendingBlocked):invoke(guard,lambda **k:calls.append(k))
    evidence.update(expected='second $0.60 request rejected before dispatch',actual_calls=len(calls),snapshot=guard.snapshot())
    assert calls==[]


def test_T02_concurrent_reservations(guard,evidence):
    def admit(_):
        try:return SpendingGuard(guard.path,policy()).reserve('openai','audit-model',.6)
        except SpendingBlocked:return None
    with concurrent.futures.ThreadPoolExecutor(8) as pool:results=list(pool.map(admit,range(16)))
    evidence.update(expected='at most one $0.60 pending request',accepted=sum(x is not None for x in results),snapshot=guard.snapshot())
    assert sum(x is not None for x in results)==1


@pytest.mark.parametrize('after_dispatch',[False,True],ids=['T03_before_dispatch','T04_after_dispatch'])
def test_crash_reservation_survives(guard,tmp_path,after_dispatch,evidence):
    ctx=multiprocessing.get_context('spawn');marker=tmp_path/'accepted.txt'
    child=ctx.Process(target=crash_worker,args=(str(guard.path),after_dispatch,str(marker)))
    child.start();child.join(15)
    assert child.exitcode==(18 if after_dispatch else 17)
    reopened=SpendingGuard(guard.path,policy())
    with pytest.raises(SpendingBlocked):invoke(reopened,lambda **kw:pytest.fail('crash refund'))
    evidence.update(expected='pending exposure retained, no automatic recovery refund',accepted_marker=marker.exists(),snapshot=reopened.snapshot())
    assert marker.exists()==after_dispatch
    assert reopened.snapshot()['requests'][0]['reserved_micro_usd']==600000


def test_T05_timeout_after_acceptance(guard,evidence):
    accepted=[]
    def timeout(**kwargs):accepted.append(True);raise TimeoutError('after mocked acceptance')
    with pytest.raises(SpendingBlocked):invoke(guard,timeout)
    snap=guard.snapshot();evidence.update(expected='full unresolved exposure retained',accepted=len(accepted),snapshot=snap)
    assert snap['blocked'] and snap['requests'][0]['reported_micro_usd'] is None


def test_T06_retry_after_timeout(guard,evidence):
    calls=[]
    def timeout(**kwargs):calls.append(True);raise TimeoutError()
    for _ in range(2):
        with pytest.raises(SpendingBlocked):invoke(guard,timeout)
    evidence.update(expected='retry rejected after ambiguous request',calls=len(calls),snapshot=guard.snapshot())
    assert len(calls)==1


def test_T07_provider_fallback_is_guarded(guard,evidence):
    calls=[]
    def error(**kwargs):calls.append(kwargs['model']);raise RuntimeError('model does not exist')
    p=mock_provider(guard,error);p.fallback_model='unpriced-fallback'
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'audit-model')
    evidence.update(expected='uncertain charge stops fallback',models_dispatched=calls,snapshot=guard.snapshot())
    assert calls==['audit-model']


def test_T08_unknown_model_price(guard,evidence):
    calls=[]
    with pytest.raises(SpendingBlocked):
        guard.invoke_openai(lambda **kw:calls.append(kw),{'model':'unknown','input':'q'})
    evidence.update(expected='unpriced model never dispatched',calls=calls,snapshot=guard.snapshot())
    assert calls==[]


def test_T09_unpriced_top_level_tool(guard,evidence):
    calls=[]
    with pytest.raises(SpendingBlocked):invoke(guard,lambda **kw:calls.append(kw),tools=[{'type':'web_search'}])
    evidence.update(expected='unpriced built-in tool rejected',calls=calls)
    assert calls==[]


def test_T10_malformed_ledger(guard,evidence):
    guard.path.write_bytes(b'corrupt ledger bytes')
    with pytest.raises(SpendingBlocked):invoke(guard,lambda **kw:pytest.fail('dispatch on corrupt file'))
    evidence.update(expected='fail closed; no budget reset',file_still_corrupt=guard.path.read_bytes()==b'corrupt ledger bytes')
    assert guard.path.read_bytes()==b'corrupt ledger bytes'


def test_T11_restart_resume(guard,evidence):
    invoke(guard);reopened=SpendingGuard(guard.path,policy())
    with pytest.raises(SpendingBlocked):invoke(reopened,lambda **kw:pytest.fail('restart reset'))
    evidence.update(expected='retained maximum still consumes allowance after restart',snapshot=reopened.snapshot())
    assert len(reopened.snapshot()['requests'])==1


def test_T12_cross_process_race(guard,evidence):
    ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(4);queue=ctx.Queue()
    children=[ctx.Process(target=race_worker,args=(str(guard.path),barrier,queue)) for _ in range(4)]
    for child in children:child.start()
    results=[queue.get(timeout=20) for _ in children]
    for child in children:child.join(10);assert child.exitcode==0
    evidence.update(expected='only one $0.60 request admitted across processes',outcomes=results,snapshot=guard.snapshot())
    assert results.count('accepted')==1


def test_T13_reconciliation_mismatch(guard,evidence):
    with pytest.raises(SpendingBlocked):invoke(guard,lambda **kw:resp(2000,10))
    snap=guard.snapshot()
    with pytest.raises(SpendingBlocked):guard.invoke_tavily(lambda:pytest.fail('post-overage search'))
    evidence.update(expected='record violation, block later calls, do not claim prevented charge',snapshot=snap)
    assert snap['blocked'] and snap['requests'][0]['reported_micro_usd']==1010000


def test_T14_repeated_failed_requests(guard,evidence):
    calls=[]
    def fail(**kw):calls.append(True);raise ConnectionError('ambiguous')
    for _ in range(10):
        with pytest.raises(SpendingBlocked):invoke(guard,fail)
    evidence.update(expected='only first ambiguous attempt can dispatch',calls=len(calls),snapshot=guard.snapshot())
    assert len(calls)==1


def test_T15_new_run_ids_do_not_reset_default_pool(guard,tmp_path,monkeypatch,evidence):
    import src.storage.spending as module
    from src.orchestration.engine import Orchestrator
    from src.storage.database import Store
    from src.config import Settings
    policy_path=tmp_path/'policy.json';policy_path.write_text(json.dumps(policy()))
    monkeypatch.setattr(module,'POLICY_PATH',policy_path);monkeypatch.setattr(module,'LEDGER_PATH',guard.path)
    accepted=[];project_ids=[]
    for n in range(3):
        p=mock_provider(None,lambda **kw:accepted.append(kw) or resp())
        settings=Settings(projects_root=str(tmp_path/f'project-root-{n}'))
        engine=Orchestrator(settings,Store(str(tmp_path/f'store-{n}.db')),client=p)
        project_ids.append(engine.create_project('offline audit objective'))
        try:p.complete('s','u',{},'audit-model')
        except SpendingBlocked:pass
    evidence.update(expected='different project IDs/roots share fixed default pool',project_ids=project_ids,calls=len(accepted),snapshot=guard.snapshot())
    assert len(set(project_ids))==3 and len(accepted)==1


def test_T16_logically_inconsistent_ledger_must_block(guard,evidence):
    invoke(guard)
    # Inject accounting corruption without destroying SQLite structure/schema.
    with sqlite3.connect(guard.path) as db:
        db.execute("UPDATE requests SET actual=1100000,state='reported'")
    rejected=False
    try:guard.reserve('tavily','basic',.1)
    except SpendingBlocked:rejected=True
    evidence.update(expected='reject logically inconsistent recorded charge > cap',rejected=rejected,snapshot=guard.snapshot())
    assert rejected,'ledger accepts new reservation despite recorded charge already above $1'


def test_T17_sdk_extra_body_cannot_override_guard(guard,evidence):
    from openai import OpenAI,DefaultHttpxClient,_base_client
    httpx=_base_client.httpx2;captured=[]
    def mock_http(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'mock','object':'response','created_at':0,'status':'completed',
          'model':'unpriced-model','output':[],
          'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}})
    client=OpenAI(api_key='offline-not-a-real-credential',base_url='https://api.openai.com/v1',max_retries=0,
                  http_client=DefaultHttpxClient(transport=httpx.MockTransport(mock_http)))
    try:
        mock_provider(guard,client.responses.create)._request(model='audit-model',input='q',
          extra_body={'model':'unpriced-model','max_output_tokens':100000,
                        'tools':[{'type':'web_search'}],'service_tier':'priority'})
    except SpendingBlocked:pass
    finally:client.close()
    evidence.update(expected='unpriced wire-body override rejected before dispatch',wire_bodies=captured,snapshot=guard.snapshot())
    assert captured==[],'SDK merges extra_body after guard checks: unpriced model/tool/tier and uncapped output sent'


def test_T18_input_token_limit_is_enforced_before_dispatch(guard,evidence):
    calls=[]
    # Synthetic one-character-per-token model: 1001 input tokens, policy cap 1000.
    def synthetic_provider(**kw):calls.append(kw);return resp(len(kw['input']),0)
    try:guard.invoke_openai(synthetic_provider,{'model':'audit-model','input':'x'*1001})
    except SpendingBlocked:pass
    evidence.update(expected='input above configured token allowance rejected before dispatch',calls=len(calls),snapshot=guard.snapshot())
    assert calls==[],'byte envelope is checked, but configured input-token maximum is not enforced before dispatch'


def test_T19_injected_new_session_cannot_replenish_experiment(tmp_path,evidence):
    calls=[];snapshots=[]
    for n in range(2):
        g=SpendingGuard(tmp_path/f'session-{n}.db',policy());g.initialize()
        p=mock_provider(g,lambda **kw:calls.append(kw) or resp())
        with pytest.raises(SpendingBlocked,match='noncanonical'):
            p.complete('s','u',{},'audit-model')
        snapshots.append(g.snapshot())
    exposure=sum(row['reserved_micro_usd'] for s in snapshots for row in s['requests'])
    evidence.update(expected='library guard injection must retain experiment allowance identity',calls=len(calls),reserved_micro_usd=exposure,snapshots=snapshots)
    assert calls==[]
    assert exposure<=1000000,'alternate experiment pools must not authorize dispatch'


def test_T20_policy_mutation_cannot_change_pinned_rates(guard,evidence):
    guard.policy['openai']['audit-model']['input_usd_per_million']=.001
    rejected=False
    try:invoke(guard)
    except SpendingBlocked:rejected=True
    evidence.update(expected='mutated in-memory policy must mismatch pinned digest',rejected=rejected,snapshot=guard.snapshot())
    assert rejected,'digest checked against stored constructor digest, not effective policy content'


def test_T21_sdk_redirects_require_separate_reservations(guard,evidence):
    from openai import OpenAI,DefaultHttpxClient,_base_client
    httpx=_base_client.httpx2;captured=[]
    def mock_http(request):
        captured.append({'method':request.method,'url':str(request.url)})
        if len(captured)==1:return httpx.Response(307,headers={'Location':'https://api.openai.com/v1/responses?redirected=1'})
        return httpx.Response(200,json={'id':'mock','object':'response','created_at':0,'status':'completed',
          'model':'audit-model','output':[],'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}})
    client=OpenAI(api_key='offline-not-a-real-credential',base_url='https://api.openai.com/v1',max_retries=0,
                  http_client=DefaultHttpxClient(transport=httpx.MockTransport(mock_http)))
    try:mock_provider(guard,client.responses.create)._create('system','q','audit-model',{'type':'json_object'})
    except SpendingBlocked:pass
    finally:client.close()
    rows=guard.snapshot()['requests'];posts=sum(x['method']=='POST' for x in captured)
    evidence.update(expected='each potentially billable POST covered, or redirects disabled',http_dispatches=captured,reservations=len(rows),snapshot=guard.snapshot())
    assert posts<=len(rows),'default SDK follows 307 with a second POST under a single reservation'
