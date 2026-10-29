"""V14: real HTTP framing and compressed bytes over deterministic fake sockets."""
import asyncio
import gzip
import io
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import zlib
import pytest
from src.tools import safe_http as net
from src.tools.retrieval import fetch_url,fetch_page_tool

@pytest.fixture
def lab(monkeypatch,tmp_path,request):
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):monkeypatch.delenv(key)
    m={'advertised_length':None,'raw_http_bytes':0,'body_delivered':0,'decoded_probe_bytes':0,
       'max_retained':0,'reads':0,'max_requested':0,'response_closed':False,'connection_closed':False,
       'connections':[],'result':None,'created_responses':[],'closed_responses':[],'tool_results':[]}
    state={'replies':[],'stall':False,'error':None,'step':0,'clock':0,'one_byte':False}
    monkeypatch.setattr(net.time,'monotonic',lambda:state['clock'])
    class Raw(io.RawIOBase):
        def __init__(self,data):self.data=data;self.position=0
        def readable(self):return True
        def readinto(self,b):
            m['reads']+=1
            if state['error'] and self.position>=state.get('error_after',0):raise state['error']
            if state['stall']:raise TimeoutError('offline stalled read')
            state['clock']+=state['step']
            n=min(len(b),len(self.data)-self.position,1 if state['one_byte'] else len(b))
            b[:n]=self.data[self.position:self.position+n];self.position+=n;m['raw_http_bytes']+=n
            return n
    class Sock:
        def __init__(self,*a):pass
        def settimeout(self,t):assert 0<t<=net.READ_TIMEOUT_S
        def connect(self,a):m['connections'].append(a)
        def sendall(self,b):m['request']=b.decode()
        def makefile(self,mode,buffering=0):assert buffering==0;return Raw(state['replies'].pop(0))
        def close(self):m['connection_closed']=True
    monkeypatch.setattr(net.socket,'socket',Sock)
    monkeypatch.setattr(net.socket,'getaddrinfo',lambda host,port,**kw:[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',port))])
    real_context=ssl.create_default_context
    class Context:
        def wrap_socket(self,sock,server_hostname):
            ctx=real_context();assert ctx.check_hostname and ctx.verify_mode==ssl.CERT_REQUIRED
            m['sni']=server_hostname;return sock
    monkeypatch.setattr(net.ssl,'create_default_context',lambda:Context())
    original=net.http.client.HTTPResponse
    class Response(original):
        def __init__(self,*a,**kw):
            self.token=len(m['created_responses']);m['created_responses'].append(self.token)
            super().__init__(*a,**kw)
        def read1(self,n):
            m['max_requested']=max(m['max_requested'],n)
            data=super().read1(n);m['body_delivered']+=len(data);return data
        def close(self):
            m['response_closed']=True
            if self.token not in m['closed_responses']:m['closed_responses'].append(self.token)
            return super().close()
    monkeypatch.setattr(net.http.client,'HTTPResponse',Response)
    def reply(body=b'',headers=None,status=200):
        h={'Content-Length':str(len(body))} if headers is None else headers
        m['advertised_length']=h.get('Content-Length')
        return (f'HTTP/1.1 {status} OK\r\n'+''.join(f'{k}: {v}\r\n' for k,v in h.items())+'\r\n').encode()+body
    probe_line=next(i+1 for i,line in enumerate(Path(net.__file__).read_text().splitlines()) if line.strip().startswith('if len(output) + len(decoded)'))
    original_reader=net._bounded_body
    def trace(frame,event,arg):
        if frame.f_code is original_reader.__code__:
            values=frame.f_locals;m['max_retained']=max(m['max_retained'],len(values.get('output',b'')))
            if event=='line' and frame.f_lineno==probe_line:
                m['decoded_probe_bytes']=max(m['decoded_probe_bytes'],len(values.get('output',b''))+len(values.get('decoded',b'')))
        return trace
    def observed_reader(resp,budget):
        previous=sys.gettrace();sys.settrace(trace)
        try:
            value=original_reader(resp,budget);m['result']='accepted_body';return value
        except BaseException as e:m['result']=type(e).__name__;raise
        finally:sys.settrace(previous)
    monkeypatch.setattr(net,'_bounded_body',observed_reader)
    def go(body=b'',headers=None,url='https://public.example/',status=200):
        if not state['replies']:state['replies'].append(reply(body,headers,status))
        try:
            value=net.read_public_url(url);m['result']='accepted';return value
        except BaseException as e:m['result']=type(e).__name__;raise
    yield m,state,reply,go
    assert set(m['created_responses'])==set(m['closed_responses'])
    output=os.environ.get('V14_MEASUREMENTS')
    if output:
        p=Path(output);p.mkdir(parents=True,exist_ok=True)
        (p/(request.node.name.replace('/','_')+'.json')).write_text(json.dumps(m,indent=2))

@pytest.mark.parametrize('offset',[-1,0,1])
def test_B01_B03_exact_boundary(lab,offset):
    m,s,reply,go=lab;size=net.MAX_BODY_BYTES+offset
    # No Content-Length: force overflow discovery from actual reads.
    if offset>0:
        with pytest.raises(ValueError):go(b'x'*size,{})
    else:assert len(go(b'x'*size,{}))==size
    assert m['body_delivered']<=net.MAX_BODY_BYTES+1 and m['max_retained']<=net.MAX_BODY_BYTES
    assert m['response_closed'] and m['connection_closed']

@pytest.mark.parametrize('length',['999999999999999999999999','invalid','-1','1, 2'])
def test_B04_invalid_or_huge_declared_length(lab,length):
    m,s,reply,go=lab
    with pytest.raises(ValueError):go(b'x',{'Content-Length':length})
    assert m['body_delivered']==0 and m['response_closed']


def test_B05_underreported_real_framing_is_not_an_unbounded_read(lab):
    m,s,reply,go=lab
    assert go(b'x'*(net.MAX_BODY_BYTES*3),{'Content-Length':'1'})==b'x'
    assert m['body_delivered']==1 and m['raw_http_bytes']<=8192
    assert m['response_closed'] # extra bytes outside the declared HTTP message are not followed

@pytest.mark.parametrize('headers',[{}, {'Content-Length':'100'}])
def test_B06_missing_or_overreported_length(lab,headers):
    m,s,reply,go=lab
    if headers:
        with pytest.raises(ValueError):go(b'x',headers)
    else:
        with pytest.raises(ValueError):go(b'x'*(net.MAX_BODY_BYTES+1),headers)
    assert m['response_closed'] and m['max_retained']<=net.MAX_BODY_BYTES


def test_B07_chunked_body(lab):
    m,s,reply,go=lab
    data=b'x'*(net.MAX_BODY_BYTES+1)
    framed=f'{len(data):x}\r\n'.encode()+data+b'\r\n0\r\n\r\n'
    with pytest.raises(ValueError):go(framed,{'Transfer-Encoding':'chunked'})
    assert m['body_delivered']==net.MAX_BODY_BYTES+1 and m['max_retained']<=net.MAX_BODY_BYTES


def test_B08_oversized_response_api_chunk_rejected(lab,monkeypatch):
    # Defense-in-depth against a broken response adapter, not a wire guarantee.
    m,s,reply,go=lab
    monkeypatch.setattr(net.http.client.HTTPResponse,'read1',lambda self,n:b'x'*(n+1))
    with pytest.raises(ValueError,match='invalid body transport'):go(b'x')
    assert m['max_retained']==0 and m['response_closed']


def test_B09_continuous_delivery_deadline(lab):
    m,s,reply,go=lab;s['one_byte']=True;s['step']=0.25
    with pytest.raises(ValueError,match='deadline'):go(b'x'*1000,{})
    assert m['raw_http_bytes']<=int(net.OPERATION_TIMEOUT_S/s['step'])+1
    assert m['response_closed'] and m['connection_closed']

@pytest.mark.parametrize('error',[TimeoutError('stalled'),ConnectionResetError('interrupted'),asyncio.CancelledError()])
def test_B10_B11_B22_exception_cleanup(lab,error):
    m,s,reply,go=lab;s['error']=error;s['one_byte']=True;s['error_after']=len(reply(b'content'))-len(b'content')
    with pytest.raises(type(error)):go(b'content')
    assert m['response_closed'] and m['connection_closed']

@pytest.mark.parametrize('encoding,compress',[('gzip',gzip.compress),('deflate',zlib.compress)])
def test_B12_B13_expansion_bomb(lab,encoding,compress):
    m,s,reply,go=lab;payload=compress(b'x'*(net.MAX_DECODED_BYTES+1))
    with pytest.raises(ValueError):go(payload,{'Content-Encoding':encoding,'Content-Length':str(len(payload))})
    assert m['body_delivered']<=net.MAX_BODY_BYTES+1 and m['max_retained']<=net.MAX_DECODED_BYTES
    assert m['decoded_probe_bytes']<=net.MAX_DECODED_BYTES+1 and m['response_closed']

@pytest.mark.parametrize('encoding,compress',[('gzip',gzip.compress),('deflate',zlib.compress)])
@pytest.mark.parametrize('offset',[-1,0,1])
def test_decoded_exact_boundaries(lab,encoding,compress,offset):
    m,s,reply,go=lab;data=b'x'*(net.MAX_DECODED_BYTES+offset);payload=compress(data)
    if offset>0:
        with pytest.raises(ValueError):go(payload,{'Content-Encoding':encoding})
    else:assert go(payload,{'Content-Encoding':encoding})==data
    assert m['max_retained']<=net.MAX_DECODED_BYTES and m['response_closed']

@pytest.mark.parametrize('encoding,body',[('gzip',b'bad'),('deflate',b'bad'),('gzip',gzip.compress(b'ok')[:-2]),('gzip',gzip.compress(b'ok')+gzip.compress(b'extra')),('br',b'bomb'),('gzip, deflate',b'bomb')])
def test_B14_B15_invalid_unsupported_or_trailing_compression(lab,encoding,body):
    m,s,reply,go=lab
    with pytest.raises(ValueError):go(body,{'Content-Encoding':encoding})
    assert m['response_closed']


def test_B16_redirect_body_not_consumed(lab):
    m,s,reply,go=lab
    s['replies']=[reply(b'x'*net.MAX_BODY_BYTES,{'Location':'/next','Content-Length':'999999999'},302),reply(b'ok')]
    assert go()==b'ok' and m['body_delivered']==2 and len(m['connections'])==2
    assert m['raw_http_bytes']<=2*8192

@pytest.mark.parametrize('body',[bytes(range(256)),b'<title>T</title><p>\xfftext</p>'])
def test_B17_B18_binary_and_malformed_utf8(lab,body):
    m,s,reply,go=lab;s['replies']=[reply(body)]
    title,text=fetch_url('https://public.example/')
    m['tool_results'].append({'title':title,'text_chars':len(text)})
    assert isinstance(text,str) and len(text)<=12000 and m['response_closed']


def test_B19_B20_html_and_search_contract(lab):
    m,s,reply,go=lab
    s['replies']=[reply(b'<title>Title</title><script>bad</script><p>Evidence</p>')]
    result=fetch_page_tool().run({'url':'https://public.example/'})
    m['tool_results'].append({'ok':result.ok,'error':result.error,'provenance':result.provenance})
    assert result.ok and result.provenance['title']=='Title' and 'bad' not in result.output
    from src.tools.search import _search_duckduckgo
    s['replies']=[reply(b'<a class="result__a" href="https://public.example/doc">Result</a><a class="result__snippet">Snippet</a>')]
    assert _search_duckduckgo('query')[0]['title']=='Result'
    assert m['response_closed']


def test_B21_oversize_tool_failure_not_truncation(lab):
    m,s,reply,go=lab;s['replies']=[reply(b'x'*(net.MAX_BODY_BYTES+1),{})]
    result=fetch_page_tool().run({'url':'https://public.example/'})
    m['result']='tool_ok' if result.ok else result.error
    assert not result.ok and 'must not be cited' in result.error and m['response_closed']

@pytest.mark.parametrize('case',['private','proxy'])
def test_B23_B25_v13_refusal(lab,monkeypatch,case):
    m,s,reply,go=lab
    if case=='proxy':monkeypatch.setenv('HTTPS_PROXY','http://required.example:8080')
    with pytest.raises(ValueError):go(url='http://127.0.0.1/' if case=='private' else 'https://public.example/')
    assert m['connections']==[]


def test_B24_B26_rebinding_and_https_authority(lab,monkeypatch):
    m,s,reply,go=lab;resolutions=[]
    def dns(host,port,**kw):
        resolutions.append(host)
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34' if len(resolutions)==1 else '127.0.0.1',port))]
    monkeypatch.setattr(net.socket,'getaddrinfo',dns)
    assert go(b'ok')==b'ok' and resolutions==['public.example']
    assert m['connections']==[('93.184.216.34',443)] and m['sni']=='public.example'
    assert 'Host: public.example\r\n' in m['request'] and 'Accept-Encoding: identity' in m['request']


def test_wire_budget_includes_chunk_framing(lab,monkeypatch):
    m,s,reply,go=lab;monkeypatch.setattr(net,'MAX_HTTP_BYTES',256)
    # Many tiny chunks: body remains small but framing exhausts the raw HTTP budget.
    with pytest.raises(ValueError,match='HTTP byte budget'):go(b'1\r\nx\r\n'*100+b'0\r\n\r\n',{'Transfer-Encoding':'chunked'})
    assert m['raw_http_bytes']<=257 and m['response_closed']


def test_contradictory_framing_refused(lab):
    m,s,reply,go=lab
    with pytest.raises(ValueError,match='framing'):go(b'0\r\n\r\n',{'Transfer-Encoding':'chunked','Content-Length':'10'})
    assert m['body_delivered']==0 and m['response_closed']


def test_downstream_parser_failure_has_closed_transport(lab,monkeypatch):
    m,s,reply,go=lab;s['replies']=[reply(b'<title>T</title>')]
    monkeypatch.setattr('src.tools.retrieval.re.search',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('parse failure')))
    result=fetch_page_tool().run({'url':'https://public.example/'})
    m['tool_results'].append({'ok':result.ok,'error':result.error})
    assert not result.ok and m['response_closed'] and m['connection_closed']


def test_redirect_chain_shares_wire_budget(lab,monkeypatch):
    m,s,reply,go=lab;monkeypatch.setattr(net,'MAX_HTTP_BYTES',512)
    s['replies']=[reply(b'x'*300,{'Location':'/next'},302),reply(b'x'*300)]
    with pytest.raises(ValueError,match='HTTP byte budget'):go()
    assert len(m['connections'])==2 and m['raw_http_bytes']<=513


def test_deadline_checked_after_blocking_resolver_returns(lab,monkeypatch):
    m,s,reply,go=lab
    def dns(host,port,**kw):
        s['clock']=net.OPERATION_TIMEOUT_S+1
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',port))]
    monkeypatch.setattr(net.socket,'getaddrinfo',dns)
    with pytest.raises(ValueError,match='deadline'):go()
    assert m['connections']==[] # does not claim the resolver can be interrupted
