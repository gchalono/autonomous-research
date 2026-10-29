"""New independent V4 tests: actual adapter/SDK paths, synthetic prices only."""

from tests.policy_fixtures import reviewed_fixture
import asyncio,concurrent.futures,json,multiprocessing,os,random,sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.storage.spending import SpendingGuard,SpendingBlocked,CAP,EXPERIMENT_ID
from src.llm.provider import OpenAIProvider


def policy():
    return reviewed_fixture({'currency':'USD','expires_at':'2099-01-01T00:00:00+00:00','evidence':'offline V4 synthetic pricing only',
      'openai':{'v4-model':{'max_input_tokens':20000,'max_output_tokens':100,'max_request_bytes':30000,
                          'input_token_overhead':256,'input_usd_per_million':15,'output_usd_per_million':1000}},
      'tavily':{'basic_search_max_usd':.1,'usd_per_credit':.1}})

def bind(path,policy_path):
    import src.storage.spending as module
    module.LEDGER_PATH=Path(path);module.POLICY_PATH=Path(policy_path)

def reply(i=10,o=5):
    return SimpleNamespace(id='offline',output_text='{}',output=[],model='v4-model',service_tier='default',
                           usage=SimpleNamespace(input_tokens=i,output_tokens=o))

def make_provider(g,send):
    p=object.__new__(OpenAIProvider);p.guard=g;p.fallback_model=None
    p.client=SimpleNamespace(responses=SimpleNamespace(create=send));return p

def rows(path):
    with sqlite3.connect(path) as db:return db.execute('SELECT provider,model,reserved,state,operation FROM requests').fetchall()

def assert_reserved(g,provider,model=None):
    r=rows(g.path);active=[x for x in r if x[3]=='dispatching']
    assert len(active)==1 and active[0][0]==provider
    assert sum(x[2] for x in r)<=CAP
    if model:assert active[0][1]==model
    return active[0]

@pytest.fixture
def lab(tmp_path,monkeypatch):
    import src.storage.spending as module
    def provision(data=None,name='canonical'):
        data=data or policy();path=tmp_path/(name+'.db');pp=tmp_path/(name+'.json')
        pp.write_text(json.dumps(data));g=SpendingGuard(path,data);g.initialize()
        monkeypatch.setattr(module,'LEDGER_PATH',path);monkeypatch.setattr(module,'POLICY_PATH',pp)
        return g
    return provision

@pytest.fixture
def guard(lab):return lab()

def sdk_provider(g,handler):
    from openai import OpenAI,DefaultHttpxClient,_base_client
    h=_base_client.httpx2
    client=OpenAI(api_key='offline-not-a-credential',base_url='https://api.openai.com/v1',max_retries=0,
                  http_client=DefaultHttpxClient(follow_redirects=False,transport=h.MockTransport(handler)))
    p=object.__new__(OpenAIProvider);p.guard=g;p.client=client;p.fallback_model=None
    return p,h

def api_response(h,output=None,i=10,o=5):
    if output is None:output=[{'id':'msg','type':'message','role':'assistant','status':'completed',
       'content':[{'type':'output_text','text':'{}','annotations':[]}]}]
    return h.Response(200,json={'id':'offline','object':'response','created_at':0,'status':'completed',
      'model':'v4-model','service_tier':'default','output':output,
      'usage':{'input_tokens':i,'output_tokens':o,'total_tokens':i+o}})


def test_A01_repeated_sdk_posts(guard,evidence):
    calls=[]
    def send(req):
        assert_reserved(guard,'openai','v4-model');calls.append(str(req.url))
        return h.Response(307,headers={'Location':'https://api.openai.com/v1/responses?again=1'})
    p,h=sdk_provider(guard,send)
    try:
        with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v4-model')
        with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v4-model')
    finally:p._sdk.close()
    evidence.update(expected='one reserved POST; no automatic redirect or reused retry',calls=calls,snapshot=guard.snapshot())
    assert len(calls)==1


def test_A02_sdk_timeout_after_acceptance(guard,evidence):
    calls=[]
    def timeout(req):
        assert_reserved(guard,'openai');calls.append(True)
        raise h.ReadTimeout('mock accepted then timeout',request=req)
    p,h=sdk_provider(guard,timeout)
    try:
        for _ in range(3):
            with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v4-model')
    finally:p._sdk.close()
    evidence.update(expected='no hidden SDK retry; uncertainty retained',calls=len(calls),snapshot=guard.snapshot())
    assert len(calls)==1 and guard.snapshot()['blocked']


def test_A03_nested_native_tool_call(guard,monkeypatch,evidence):
    from src.agents.executor import run_execution_native
    from src.tools.base import ToolRegistry
    from src.tools.search import web_search_tool
    dispatch=[]
    class SearchResponse:
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def read(self):return json.dumps({'usage':{'credits':1},'results':[]}).encode()
    def search_send(req,timeout=30):
        assert_reserved(guard,'tavily');dispatch.append('tavily');return SearchResponse()
    monkeypatch.setenv('TAVILY_API_KEY','offline-test-credential')
    monkeypatch.setattr('src.tools.search._open_tavily',search_send)
    def send(req):
        assert_reserved(guard,'openai','v4-model');dispatch.append('openai')
        if dispatch.count('openai')==1:
            output=[{'id':'fc1','type':'function_call','call_id':'c1','name':'web_search','arguments':'{"query":"q","max_results":1}'}]
        else:
            report={'executive_summary':'offline report','findings':[],'claims':[],'sources':[],
                    'limitations':['offline synthetic fixture'],'unresolved_dependencies':[]}
            output=[{'id':'fc2','type':'function_call','call_id':'c2','name':'submit_report','arguments':json.dumps(report)}]
        return api_response(h,output)
    p,h=sdk_provider(guard,send);registry=ToolRegistry();registry.register(web_search_tool())
    try:report=run_execution_native(p,'v4-model',['offline specification'],registry,max_iterations=2)
    finally:p._sdk.close()
    evidence.update(expected='model, nested search, next model separately reserved',dispatches=dispatch,snapshot=guard.snapshot())
    assert dispatch==['openai','tavily','openai'] and report.executive_summary=='offline report'
    assert sum(r['reserved_micro_usd'] for r in guard.snapshot()['requests'])==900000


def test_A04_direct_adapter_and_public_client(guard,evidence):
    calls=[]
    def send(req):assert_reserved(guard,'openai');calls.append(True);return api_response(h)
    p,h=sdk_provider(guard,send)
    try:
        payload,_,_=p.complete('s','u',{},'v4-model');assert payload=={}
        p.client.responses.create(model='v4-model',input='direct client')
        with pytest.raises(SpendingBlocked):p.client.responses.create(model='v4-model',input='third')
    finally:p._sdk.close()
    evidence.update(expected='library and exposed client share cumulative pool',calls=len(calls),snapshot=guard.snapshot())
    assert len(calls)==2


def test_A05_thread_and_async_concurrency(guard,evidence):
    calls=[]
    def send(**kw):assert_reserved(guard,'openai');calls.append(True);return reply()
    def one(_):
        try:make_provider(guard,send).complete('s','u',{},'v4-model');return True
        except SpendingBlocked:return False
    with concurrent.futures.ThreadPoolExecutor(8) as pool:threaded=list(pool.map(one,range(16)))
    async def run():
        # The managed sandbox denies send() on asyncio's AF_UNIX wakeup
        # socket. Keep a test-only timer heartbeat so queued thread callbacks
        # are serviced, including executor shutdown. No network is enabled.
        loop=asyncio.get_running_loop()
        def poll():loop.call_later(.01,poll)
        loop.call_soon(poll)
        return await asyncio.gather(*(asyncio.to_thread(one,n) for n in range(8)))
    resumed=asyncio.run(run())
    evidence.update(expected='atomic same-file admission from threads/async callers',accepted=sum(threaded)+sum(resumed),snapshot=guard.snapshot())
    assert sum(threaded)+sum(resumed)==len(calls)<=2
    assert sum(x['reserved_micro_usd'] for x in guard.snapshot()['requests'])<=CAP


def race_worker(path,pp,barrier,q):
    bind(path,pp);g=SpendingGuard(path,policy());barrier.wait(timeout=10)
    def send(**kw):assert_reserved(g,'openai');return reply()
    try:make_provider(g,send).complete('s','u',{},'v4-model');q.put(True)
    except SpendingBlocked:q.put(False)


def test_A06_cross_process_race(guard,evidence):
    ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(4);q=ctx.Queue();pp=guard.path.with_suffix('.json')
    children=[ctx.Process(target=race_worker,args=(str(guard.path),str(pp),barrier,q)) for _ in range(4)]
    for c in children:c.start()
    results=[q.get(timeout=20) for c in children]
    for c in children:c.join(10);assert c.exitcode==0
    evidence.update(expected='separate adapter instances share one cap',accepted=sum(results),snapshot=guard.snapshot())
    assert 1<=sum(results)<=2
    assert sum(x['reserved_micro_usd'] for x in guard.snapshot()['requests'])<=CAP


def crash_worker(path,pp,marker):
    bind(path,pp);g=SpendingGuard(path,policy())
    def send(**kw):assert_reserved(g,'openai');Path(marker).write_text('accepted');os._exit(17)
    make_provider(g,send).complete('s','u',{},'v4-model')


def test_A07_crash_after_dispatch(guard,tmp_path,evidence):
    ctx=multiprocessing.get_context('spawn');marker=tmp_path/'accepted'
    c=ctx.Process(target=crash_worker,args=(str(guard.path),str(guard.path.with_suffix('.json')),str(marker)))
    c.start();c.join(15);assert c.exitcode==17 and marker.exists()
    reopened=SpendingGuard(guard.path,policy())
    with pytest.raises(SpendingBlocked):make_provider(reopened,lambda **k:pytest.fail('crash refund')).complete('s','u',{},'v4-model')
    evidence.update(expected='dispatching state survives death and blocks continuation',snapshot=reopened.snapshot())
    assert reopened.snapshot()['requests'][0]['state']=='dispatching'


def test_A08_recovery_after_uncertain_completion(guard,evidence):
    p=make_provider(guard,lambda **kw:(_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v4-model')
    reopened=SpendingGuard(guard.path,policy())
    with pytest.raises(SpendingBlocked):make_provider(reopened,lambda **kw:pytest.fail('resume')).complete('s','u',{},'v4-model')
    evidence.update(expected='uncertain retained after restart',snapshot=reopened.snapshot())
    assert reopened.snapshot()['requests'][0]['state']=='uncertain'


@pytest.mark.parametrize('mutation',[
 "PRAGMA user_version=999", "UPDATE session SET experiment='another'", "UPDATE requests SET state='nonsense'",
 "UPDATE requests SET actual=1100000", "UPDATE requests SET usage='{}'", "ALTER TABLE requests DROP COLUMN usage",
 "UPDATE requests SET reserved=-1", "UPDATE requests SET actual='NaN'", "UPDATE requests SET experiment='wrong'",
 "UPDATE requests SET usage='{\"input_tokens\":NaN,\"output_tokens\":1}'"
])
def test_A09_corrupted_ledger(guard,mutation,evidence):
    make_provider(guard,lambda **kw:reply()).complete('s','u',{},'v4-model')
    with sqlite3.connect(guard.path) as db:
        db.execute('PRAGMA ignore_check_constraints=ON');db.execute(mutation)
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:pytest.fail('corrupt dispatch')).complete('s','u',{},'v4-model')
    evidence.update(expected='logical/schema/monetary corruption blocks without reset',mutation=mutation)


def test_A10_missing_ledger_on_resume(guard,evidence):
    make_provider(guard,lambda **kw:reply()).complete('s','u',{},'v4-model');guard.path.unlink()
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:pytest.fail('missing ledger')).complete('s','u',{},'v4-model')
    evidence.update(expected='no implicit fresh allowance',file_exists=guard.path.exists())
    assert not guard.path.exists()


def test_A11_unknown_model_and_search_pricing(guard,lab,evidence):
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:pytest.fail('unknown model')).complete('s','u',{},'unpriced')
    data=policy();del data['tavily']
    with pytest.raises(SpendingBlocked):lab(data,'no-search-price')
    evidence.update(expected='zero priced-operation dispatches; incomplete search policy rejected by loader',model_rows=guard.snapshot()['requests'])


@pytest.mark.parametrize('bound',[None,0,-1,float('inf')])
def test_A12_unbounded_output(lab,bound,evidence):
    data=policy();data['openai']['v4-model']['max_output_tokens']=bound
    try:g=lab(data)
    except SpendingBlocked:
        evidence.update(expected='reject invalid output cap before provisioning/dispatch',rejected='policy');return
    with pytest.raises(SpendingBlocked):make_provider(g,lambda **kw:pytest.fail('output unbounded')).complete('s','u',{},'v4-model')
    evidence.update(expected='reject invalid output cap',snapshot=g.snapshot())


def test_A13_provider_fallback(guard,evidence):
    calls=[]
    def fail(**kw):assert_reserved(guard,'openai');calls.append(kw['model']);raise RuntimeError('model not found')
    p=make_provider(guard,fail);p.fallback_model='unpriced-fallback'
    with pytest.raises(SpendingBlocked):p.complete('s','u',{},'v4-model')
    evidence.update(expected='uncertain primary charge stops fallback',models=calls,snapshot=guard.snapshot())
    assert calls==['v4-model']


def test_A14_missing_usage(guard,evidence):
    def send(**kw):assert_reserved(guard,'openai');r=reply();r.usage=None;return r
    with pytest.raises(SpendingBlocked):make_provider(guard,send).complete('s','u',{},'v4-model')
    evidence.update(expected='retain reservation, preserve unknown charge',snapshot=guard.snapshot())
    assert guard.snapshot()['requests'][0]['reported_micro_usd'] is None


def test_A15_excess_usage(guard,evidence):
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:reply(100000,10000)).complete('s','u',{},'v4-model')
    snap=guard.snapshot()
    with pytest.raises(SpendingBlocked):guard.invoke_tavily(lambda:pytest.fail('after overage'))
    evidence.update(expected='record discrepancy; block later work, not undo provider charge',snapshot=snap)
    assert snap['requests'][0]['reported_micro_usd']>CAP and snap['blocked']


def test_A16_experiment_reset(guard,tmp_path,evidence):
    calls=[]
    for _ in range(3):
        p=make_provider(None,lambda **kw:calls.append(True) or reply())
        try:p.complete('s','new run',{},'v4-model')
        except SpendingBlocked:pass
    rogue=SpendingGuard(tmp_path/'new-experiment.db',policy());rogue.initialize()
    with pytest.raises(SpendingBlocked,match='noncanonical'):
        make_provider(rogue,lambda **kw:pytest.fail('alternate allowance')).complete('s','u',{},'v4-model')
    evidence.update(expected='new adapter/run IDs and alternate path cannot replenish canonical allowance',calls=len(calls),snapshot=guard.snapshot())
    assert len(calls)==2 and rogue.snapshot()['requests']==[]


def partial_writer(path):
    db=sqlite3.connect(path);db.execute('BEGIN IMMEDIATE');db.execute("UPDATE session SET blocked='interrupted write'");os._exit(19)


def test_A17_partial_write_and_truncation(guard,evidence):
    make_provider(guard,lambda **kw:reply()).complete('s','u',{},'v4-model')
    ctx=multiprocessing.get_context('spawn');c=ctx.Process(target=partial_writer,args=(str(guard.path),))
    c.start();c.join(15);assert c.exitcode==19
    snap=guard.snapshot();assert snap['integrity_error'] is None and len(snap['requests'])==1
    data=guard.path.read_bytes();guard.path.write_bytes(data[:len(data)//2])
    with pytest.raises(SpendingBlocked):make_provider(guard,lambda **kw:pytest.fail('truncated ledger')).complete('s','u',{},'v4-model')
    evidence.update(expected='uncommitted transaction rolls back; truncated file blocks',pre_truncation=snap)


@pytest.mark.parametrize('amount',[-1,'NaN','Infinity','-Infinity','bad',None,True,{},[]])
def test_A18_invalid_money(guard,amount,evidence):
    before=guard.snapshot()
    with pytest.raises(SpendingBlocked):guard.reserve('openai','v4-model',amount)
    evidence.update(expected='invalid amount rejected without state mutation',amount=str(amount))
    assert guard.snapshot()==before


def test_A19_unexpected_sdk_operation(guard,evidence):
    p=make_provider(guard,lambda **kw:pytest.fail('unsupported operation reached transport'))
    with pytest.raises(SpendingBlocked):p.client.chat.completions.create(model='v4-model',messages=[])
    with pytest.raises(SpendingBlocked):p.client.responses.delete('other')
    with pytest.raises(SpendingBlocked):p.client.responses.create(model='v4-model',input='q',extra_body={'tools':[{'type':'web_search'}]})
    evidence.update(expected='only reviewed Responses creation surface exposed',snapshot=guard.snapshot())
    assert guard.snapshot()['requests']==[]


def test_A20_every_http_send_has_distinct_durable_reservation(guard,evidence):
    observed=[]
    def send(req):
        row=assert_reserved(guard,'openai','v4-model');body=json.loads(req.content)
        assert req.method=='POST' and req.url.path=='/v1/responses'
        assert body['max_output_tokens']==100 and body['service_tier']=='default'
        with sqlite3.connect(guard.path) as db:
            rid=db.execute("SELECT id FROM requests WHERE state='dispatching'").fetchone()[0]
        assert rid not in observed;observed.append(rid)
        return api_response(h)
    p,h=sdk_provider(guard,send)
    try:
        for _ in range(4):
            try:p.complete('s','u',{},'v4-model')
            except SpendingBlocked:pass
    finally:p._sdk.close()
    evidence.update(expected='zero unreserved sends; no reservation reuse',send_reservations=observed,snapshot=guard.snapshot())
    assert len(observed)==2 and len(set(observed))==2
