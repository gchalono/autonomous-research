"""Offline tests exercise real HTTP framing, pinning and page/tool boundaries."""
import io
import socket
import ssl
import pytest
from src.tools import safe_http as net
from src.tools.retrieval import fetch_url, fetch_page_tool

PUBLIC = '93.184.216.34'

@pytest.fixture
def wire(monkeypatch):
    for key in list(__import__('os').environ):
        if key.lower().endswith('_proxy'): monkeypatch.delenv(key)
    attempts, established, sent, tls, resolutions = [], [], [], [], []
    replies = []
    answers = [PUBLIC]
    def resolve(host,port,**kwargs):
        resolutions.append(host)
        return [(socket.AF_INET6 if ':' in a else socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',(a,port)) for a in answers]
    class Sock:
        def __init__(self,*args): pass
        def settimeout(self,t): pass
        def connect(self,addr): attempts.append(addr); established.append(addr)
        def sendall(self,b): sent.append(b)
        def makefile(self,*args):
            status,headers,body = replies.pop(0) if replies else (200,{},b'<title>Public</title><p>Evidence</p>')
            return io.BytesIO(('HTTP/1.1 '+str(status)+' OK\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'Content-Length: '+str(len(body))+'\r\n\r\n').encode()+body)
        def close(self): pass
    real_context = ssl.create_default_context
    def context():
        ctx = real_context()
        assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
        class Context:
            def wrap_socket(self,sock,server_hostname):
                tls.append((server_hostname,ctx.check_hostname,ctx.verify_mode));return sock
        return Context()
    monkeypatch.setattr(net.socket,'getaddrinfo',resolve)
    monkeypatch.setattr(net.socket,'socket',Sock)
    monkeypatch.setattr(net.ssl,'create_default_context',context)
    return dict(attempts=attempts,established=established,sent=sent,tls=tls,resolutions=resolutions,replies=replies,answers=answers)

@pytest.mark.parametrize('url',[
 'http://127.0.0.1','http://10.0.0.1','http://169.254.169.254',
 'http://[::1]','http://[fc00::1]','http://[fe80::1]',
 'http://[::ffff:192.168.1.1]','http://2130706433','http://0177.0.0.1','http://0x7f000001',
 'http://u:p@example.com','http://bad..host','http://example.com:0','http://example.com:65536',
 'http://[broken]','http://example.com:','http://example.com\\@127.0.0.1',
 'file:///etc/passwd','/relative','http://example.com\n','http://224.0.0.1','http://0.0.0.0',
 'http://[64:ff9b::7f00:1]','http://[3fff::1]','http://192.0.0.8','http://100.64.0.1',
 'http://[2002:7f00:1::]','http://[2001::1]','http://api.openai.com',
])
def test_S01_S09_reject_invalid_and_nonpublic(wire,url):
    result=fetch_page_tool().run({'url':url})
    assert not result.ok
    assert wire['attempts']==wire['established']==[]

@pytest.mark.parametrize('answers',[['10.0.0.1'],[PUBLIC,'127.0.0.1'],[],['not-an-ip'],['2606:4700:4700::1111%eth0']])
def test_S10_S11_dns_fail_closed(wire,answers):
    wire['answers'][:]=answers
    with pytest.raises(ValueError):fetch_url('https://public.example')
    assert wire['attempts']==[]


def test_S12_rebinding_cannot_change_actual_socket(wire,monkeypatch):
    calls=[]
    def dns(host,port,**kw):
        calls.append(host)
        ip=PUBLIC if len(calls)==1 else '127.0.0.1'
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',(ip,port))]
    monkeypatch.setattr(net.socket,'getaddrinfo',dns)
    assert fetch_url('https://public.example')[0]=='Public'
    assert calls==['public.example']
    assert wire['attempts']==[(PUBLIC,443)]


def test_S13_private_redirect(wire):
    wire['replies'].append((302,{'Location':'http://169.254.169.254/latest'},b''))
    with pytest.raises(ValueError): fetch_url('https://public.example')
    assert wire['attempts']==[(PUBLIC,443)] # one approved initial hop, zero private attempts


def test_S14_public_redirect(wire):
    wire['replies'].append((302,{'Location':'https://other.example/article'},b''))
    assert fetch_url('https://public.example')[0]=='Public'
    assert wire['attempts']==[(PUBLIC,443)]*2
    assert [x[0] for x in wire['tls']]==['public.example','other.example']

@pytest.mark.parametrize('mode',['loop','limit','bad_scheme','control'])
def test_S15_redirect_bounded(wire,mode):
    if mode=='limit': wire['replies'][:]=[(302,{'Location':f'/hop{i}'},b'') for i in range(6)]
    else:wire['replies'].append((302,{'Location':{'loop':'https://public.example/','bad_scheme':'file:///etc/passwd','control':'https://other.example/\tbad'}[mode]},b''))
    with pytest.raises(ValueError):fetch_url('https://public.example/')
    assert len(wire['attempts'])==(6 if mode=='limit' else 1)

@pytest.mark.parametrize('var',['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'])
def test_S16_proxy_environment_fails_closed(wire,monkeypatch,var):
    monkeypatch.setenv(var,'http://proxy.example:8080');monkeypatch.setenv('NO_PROXY','*')
    with pytest.raises(ValueError,match='proxy'):fetch_url('https://public.example')
    assert wire['attempts']==wire['resolutions']==[]

@pytest.mark.parametrize('url,ip,port',[('http://93.184.216.34',PUBLIC,80),('http://[2606:4700:4700::1111]','2606:4700:4700::1111',80),('https://public.example',PUBLIC,443)])
def test_S17_S19_public_socket_and_authority(wire,url,ip,port):
    assert fetch_url(url)==('Public','Public Evidence')
    assert wire['attempts'][0][:2]==(ip,port)
    assert len(wire['established'])==1
    if port==443:
        assert wire['tls']==[('public.example',True,ssl.CERT_REQUIRED)]
        assert b'Host: public.example\r\n' in b''.join(wire['sent'])
    else:assert wire['tls']==[] and wire['resolutions']==[]


def test_S20_tool_and_search_workflow(wire):
    result=fetch_page_tool().run({'url':'https://public.example'})
    assert result.ok and result.provenance['title']=='Public'
    from src.tools.search import _search_duckduckgo
    wire['replies'].append((200,{},b'<a class="result__a" href="https://public.example/doc">Result</a><a class="result__snippet">Snippet</a>'))
    assert _search_duckduckgo('query')[0]['url']=='https://public.example/doc'
    assert wire['attempts']==[(PUBLIC,443)]*2


def test_redirect_rebinding_rechecks_answers(wire,monkeypatch):
    count=[]
    def dns(host,port,**kw):
        count.append(host)
        return [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',(PUBLIC if len(count)==1 else '10.0.0.1',port))]
    monkeypatch.setattr(net.socket,'getaddrinfo',dns)
    wire['replies'].append((302,{'Location':'/next'},b''))
    with pytest.raises(ValueError):fetch_url('https://public.example')
    assert len(count)==2 and wire['attempts']==[(PUBLIC,443)]


def test_tls_certificate_failure_is_not_retried(wire,monkeypatch):
    class BadContext:
        def wrap_socket(self,sock,server_hostname):raise ssl.SSLCertVerificationError('offline certificate rejected')
    monkeypatch.setattr(net.ssl,'create_default_context',lambda:BadContext())
    with pytest.raises(ssl.SSLCertVerificationError):fetch_url('https://public.example')
    assert wire['attempts']==[(PUBLIC,443)] and wire['sent']==[]


def test_cgi_proxy_is_not_silently_bypassed(wire,monkeypatch):
    monkeypatch.setenv('REQUEST_METHOD','GET')
    monkeypatch.setenv('HTTP_PROXY','http://required.example:8080')
    with pytest.raises(ValueError,match='proxy'):fetch_url('https://public.example')
    assert wire['attempts']==[]
