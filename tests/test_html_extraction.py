"""V15 production extraction tests, entirely offline."""
import pytest
from src.tools import retrieval as page

@pytest.fixture
def extract(monkeypatch):
    def run(body):
        monkeypatch.setattr(page,'read_public_url',lambda url:body.encode() if isinstance(body,str) else body)
        return page.fetch_url('https://offline.example/document')
    return run


def test_H01_H22_page_tool_contract(extract):
    title,text=extract('<html><title>Example &amp; Title</title><p>Hello <b>world</b>.</p></html>')
    assert title=='Example & Title' and 'Hello world .' in text
    result=page.fetch_page_tool().run({'url':'https://offline.example/document'})
    assert result.ok and result.output.startswith('TITLE: Example & Title\n\n')
    assert result.provenance=={'url':'https://offline.example/document','title':title,'chars':len(text)}

@pytest.mark.parametrize('tag',['script','style','ScRiPt','STYLE'])
def test_H02_H06_raw_content_excluded(extract,tag):
    assert extract(f'<p>Before</p><{tag}>hidden &amp; <p>secret</p></{tag}><p>After</p>')==('','Before After')

@pytest.mark.parametrize('tag',['script','style'])
def test_H03_H05_unclosed_raw_text(extract,tag):
    title,text=extract('before'+f'<{tag}>'*50000+'hidden')
    assert text=='before' and title==''

@pytest.mark.parametrize('html',[
    '<a x="'+('v'*9000)+'">text</a>',
    '<p x="unfinished', '<p', '</p junk>', '<p <script>>',
    '<'+('n'*65)+'>text', '<script>bad</script '+(' '*9000)+'>tail',
])
def test_H07_H09_bounded_malformed_tags_fail(extract,html):
    with pytest.raises(ValueError):extract(html)
    result=page.fetch_page_tool().run({'url':'https://offline.example/document'})
    assert not result.ok and 'must not be cited' in result.error


def test_H10_raw_nesting_has_no_stack(extract):
    assert extract('a<script><style>hidden</style><script>more</script>b')==('','a b')
    assert extract('a<style><script>hidden</script></style>b')==('','a b')
    assert extract('a<script/>hidden')==('','a')


def test_H11_comments_and_attribute_markup(extract):
    assert extract('a<!-- <script>not real</script> -->b<div x="<script>attribute</script>">c</div>')==('','a b c')
    assert extract('a<!-- unclosed <script> hidden')==('','a')


def test_H12_H14_entities(extract):
    title,text=extract('<title>A &amp; B</title><p>&lt;tag&gt; &#65; &#x1F642; &NotEqualTilde; &bogus; &amp</p>')
    assert title=='A & B' and '<tag> A 🙂 ≂̸ &bogus; &' in text
    # No entity-decoded tag is recursively parsed.
    assert '<script>visible</script>' in extract('&lt;script&gt;visible&lt;/script&gt;')[1]
    assert extract('&#'+'9'*50000+';')[1].startswith('&#9999')


def test_H15_replacement_and_unicode(extract):
    title,text=extract(b'<title>\xff</title><p>caf\xc3\xa9 \xf0\x9f\x99\x82</p>')
    assert title=='�' and text=='� café 🙂'

@pytest.mark.parametrize('html,expected',[
    ('<p>none</p>',''),('<title></title><title>second</title>',''),
    ('<title>first</title><title>second</title>','first'),
    ('<title>unclosed','unclosed'),('<title>one<title>two</title>','onetwo'),
])
def test_H16_title_semantics(extract,html,expected):
    assert extract(html)[0]==expected


def test_H17_H19_output_accumulation_caps(extract):
    title,text=extract('<title>'+'T'*100000+'</title><p>'+'x'*100000+'</p>')
    assert len(title)==1024 and len(text)==12000
    assert len(page._Text(5).parts)==0


def test_H18_whitespace(extract):
    assert extract(' \n\tA\u00a0 \r\n B <div> C </div> D  ')[1]=='A B C D'
    assert extract('2 < 3 and 5 > 4')[1]=='2 < 3 and 5 > 4'

@pytest.mark.parametrize('body',[
    'x'*page.MAX_DECODED_BYTES,
    '🙂'.encode()+b'a'*(page.MAX_DECODED_BYTES-4),
    '<script>'*(page.MAX_DECODED_BYTES//8),
    '<!--'+'x'*(page.MAX_DECODED_BYTES-4),
    '<title>'+'T'*(page.MAX_DECODED_BYTES-len('<title></title>'))+'</title>',
])
def test_H20_maximum_input(extract,body):
    title,text=extract(body)
    assert len(text)<=12000 and len(title)<=1024


def test_H21_search_contract_unchanged(monkeypatch):
    from src.tools.search import _search_duckduckgo
    monkeypatch.setattr('src.tools.search.read_public_url',lambda url:b'<a class="result__a" href="https://public.example/doc">Result</a><a class="result__snippet">Snippet</a>')
    assert _search_duckduckgo('query')==[{'title':'Result','url':'https://public.example/doc','snippet':'Snippet'}]


def test_H23_http_failure_is_not_recovered_as_text(monkeypatch):
    def fail(url):raise ValueError('HTTP byte limit')
    monkeypatch.setattr(page,'read_public_url',fail)
    result=page.fetch_page_tool().run({'url':'https://offline.example/document'})
    assert not result.ok and 'must not be cited' in result.error and result.provenance=={}

@pytest.mark.parametrize('body',['<','<<<<<','a &unknown b','a<!DOCTYPE html>b','a<?pi?>b','a</scripture>b','<div><div><div>x','<script>hide</scripture>still hidden'])
def test_H24_small_malformed_corpus(extract,body):
    title,text=extract(body)
    assert isinstance(title,str) and isinstance(text,str) and len(text)<=12000


def test_bounded_scanner_does_not_delegate_to_dom_or_global_substitution(monkeypatch,extract):
    import html.parser
    monkeypatch.setattr(html.parser.HTMLParser,'feed',lambda *a:(_ for _ in ()).throw(AssertionError('DOM path')))
    monkeypatch.setattr(page.re,'sub',lambda *a,**k:(_ for _ in ()).throw(AssertionError('global rescan')))
    assert extract('<p>safe</p>')==('','safe')


def test_maximum_incomplete_attribute_fails_without_token_accumulation(extract):
    with pytest.raises(ValueError,match='oversized'):
        extract('<a title="'+'x'*(page.MAX_DECODED_BYTES-len('<a title="')))


def test_entity_decoder_never_receives_unbounded_token(monkeypatch,extract):
    original=page.html_lib.unescape;seen=[]
    def bounded(token):
        seen.append(len(token));assert len(token)<=35;return original(token)
    monkeypatch.setattr(page.html_lib,'unescape',bounded)
    assert extract('&amp; '*10000)[1].startswith('& &')
    assert seen and max(seen)<=35
