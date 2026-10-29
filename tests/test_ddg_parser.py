"""V16 production fallback tests; synthetic fixtures, no live HTML/network."""
import json
from pathlib import Path
import random
import pytest
from src.tools import search
from tests.ddg_v16_fixtures import result,corpus,malicious

@pytest.fixture
def run(monkeypatch):
    def invoke(page,limit=8):
        monkeypatch.setattr(search,'read_public_url',lambda url:page.encode() if isinstance(page,str) else page)
        return search._search_duckduckgo('offline',limit)
    return invoke

@pytest.mark.parametrize('name',list(corpus()))
def test_valid_corpus(run,name):
    page,limit=corpus()[name];rows=run(page,limit)
    assert len(rows)<=limit
    if name=='zero':assert rows==[]
    elif name=='duplicates':assert [r['title'] for r in rows]==['One','Again'] and rows[0]['url']==rows[1]['url']
    elif name=='entities':assert rows==[{'title':'A & B','url':'https://example.com/a','snippet':'C A <D>'}]
    elif name=='outbound':assert rows[0]['url']=='https://example.com/a?q=x y'
    elif name=='empty_content':assert rows==[{'title':'','url':'https://example.com/a','snippet':''}]
    elif name=='more':assert len(rows)==1 and rows[0]['title']=='One'
    elif name=='multiple':assert [r['title'] for r in rows]==['One','Two']
    elif name=='inline':assert rows[0]['title']=='Bold title' and rows[0]['snippet']=='Text with inline'
    elif name=='unicode':assert rows[0]['title']=='日本 🙂'
    else:assert rows==[{'title':'Title','url':'https://example.com/a','snippet':'Snippet'}]

@pytest.mark.parametrize('family',['openings','missing_close','near_class','malformed','whitespace'])
def test_D01_D02_D03_D06_D14_D15_incomplete_families(run,family):
    try:rows=run(malicious(family,65536))
    except ValueError:return
    assert rows==[]

@pytest.mark.parametrize('page',[
    '<a class="result__a" href="'+'x'*9000+'">Title</a>',
    '<a class="result__a" href="unclosed',
    '<p <a class="result__a">',
    '<div>'*129+'deep',
    '<a class="result__a" class="result__snippet" href="https://example.com/a">ambiguous</a>',
])
def test_D04_D05_D13_malformed_safe_failure(run,page):
    with pytest.raises(ValueError):run(page)


def test_D07_nested_anchor_does_not_inherit_url(run):
    page='<a class="result__a" href="https://example.com/A">A'+result('B','https://example.com/B','B snippet')
    assert run(page)==[{'title':'B','url':'https://example.com/B','snippet':'B snippet'}]

@pytest.mark.parametrize('wrapper',['<!--{}-->','<script>{}</script>','<style>{}</style>'])
def test_D08_D09_hidden_markup(run,wrapper):
    assert run(wrapper.format(result('Fake'))+result('Real'))==[{'title':'Real','url':'https://example.com/a','snippet':'Snippet'}]


def test_D10_entity_buffers_are_bounded(run):
    rows=run(result('&amp;'*5000,snippet='&#65;'*5000))
    assert rows[0]['title']=='&'*1024 and rows[0]['snippet']=='A'*500
    assert run(result('&#'+'9'*5000+';',snippet='ok'))[0]['title'].startswith('&#9999')


def test_D11_unicode_and_nul(run):
    rows=run(result('日本\0🙂',snippet='café\0text'))
    assert rows[0]['title']=='日本\0🙂' and rows[0]['snippet']=='café\0text'


def test_D12_case_and_class_tokens(run):
    page='<A HREF="https://example.com/a" CLASS="other result__a">Title</A><A CLASS="result__snippet extra">Snippet</A>'
    assert run(page)==[{'title':'Title','url':'https://example.com/a','snippet':'Snippet'}]
    assert run(result().replace('result__a','result__aaa'))==[]


def test_D16_D17_missing_fields_not_invented(run):
    assert run('<a class="result__a" href="https://example.com/A">A</a>')==[]
    assert run('<a class="result__snippet">alone</a>')==[]


def test_D18_D19_latest_complete_flat_pair_only(run):
    page='<a class="result__a" href="https://example.com/A">A</a>'+result('B','https://example.com/B','B snippet')+'<a class="result__snippet">extra</a>'
    assert run(page)==[{'title':'B','url':'https://example.com/B','snippet':'B snippet'}]


def test_A_title_does_not_take_B_snippet_across_records(run):
    page='<div class="result"><a class="result__a" href="https://example.com/A">A</a></div><div class="result"><a class="result__snippet">B snippet</a></div>'
    assert run(page)==[]


def test_A_url_does_not_take_B_title(run):
    page='<div class="result"><a class="result__a" href="https://example.com/A">A'+result('B','https://example.com/B','B snippet',wrapper=True)+'</div>'
    assert run(page)==[{'title':'B','url':'https://example.com/B','snippet':'B snippet'}]


def test_malformed_candidate_does_not_poison_valid_result(run):
    page='<a class="result__a" href="invalid">bad</a>'+result('Good','https://example.com/good','Good snippet')
    assert run(page)==[{'title':'Good','url':'https://example.com/good','snippet':'Good snippet'}]

@pytest.mark.parametrize('scoped',[False,True])
def test_irrelevant_subtree_snippet_not_associated(run,scoped):
    page='<a class="result__a" href="https://example.com/A">A</a><div class="unrelated"><a class="result__snippet">irrelevant</a></div>'
    if scoped:page='<div class="result">'+page+'</div>'
    assert run(page)==[]


def test_record_body_and_title_wrapper(run):
    page='<div class="result"><div class="result__body"><h2 class="result__title"><a class="result__a" href="https://example.com/a">Title</a></h2><div class="extras"><a href="https://irrelevant.test">extra</a></div><a class="result__snippet">Snippet</a></div></div>'
    assert run(page)==[{'title':'Title','url':'https://example.com/a','snippet':'Snippet'}]


def test_flat_irrelevant_markup_breaks_adjacency(run):
    head='<a class="result__a" href="https://example.com/A">A</a>'
    tail='<a class="result__snippet">not proven</a>'
    for gap in ['<div></div>','irrelevant text','</missing>','<a>other</a>']:
        assert run(head+gap+tail)==[]
    assert run(head+' \n<!-- neutral -->'+tail)[0]['title']=='A'

@pytest.mark.parametrize('family',['openings','whitespace'])
def test_D20_production_cap(run,family):
    try:rows=run(malicious(family,search.MAX_DECODED_BYTES))
    except ValueError:return
    assert rows==[]


def test_maximum_output_bound_and_early_exit(run):
    page=''.join(result(str(i),f'https://example.com/{i}','s') for i in range(60))+'<bad unfinished'
    rows=run(page,50)
    assert len(rows)==50 and [r['title'] for r in rows]==list(map(str,range(50)))
    assert all(len(r['title'])<=1024 and len(r['snippet'])<=500 and len(r['url'])<=4096 for r in rows)

@pytest.mark.parametrize('limit',[0,51,True,-1])
def test_requested_result_limit(run,limit):
    with pytest.raises(ValueError):run(result(),limit)


def test_href_entity_decode_and_wrapper_filter(run):
    assert run(result(url='https://example.com/?a=1&amp;b=2'))[0]['url']=='https://example.com/?a=1&b=2'
    assert run(result(url='/l/?missing=1'))==[]
    assert run(result(url='javascript:alert(1)'))==[]


def test_deterministic_malformed_contamination_corpus(run):
    rng=random.Random(20261029)
    for iteration in range(50):
        blocks=[];expected=set()
        for i in range(10):
            token=f'{iteration}_{i}'
            if rng.randrange(3)==0:
                blocks.append(f'<a class="result__a" href="https://example.com/bad{token}">bad{token}</a>')
            else:
                blocks.append(result('T'+token,'https://example.com/'+token,'S'+token,wrapper=bool(rng.randrange(2))))
                expected.add(('T'+token,'https://example.com/'+token,'S'+token))
        for row in run(''.join(blocks),50):assert (row['title'],row['url'],row['snippet']) in expected


def test_tool_output_and_no_results_failure(run,monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY',raising=False)
    run(result())
    out=search.web_search_tool().invoke({'query':'q'})
    assert out.ok and out.provenance=={'result_count':1,'result_urls':['https://example.com/a']}
    run('<p>no results</p>')
    out=search.web_search_tool().invoke({'query':'q'})
    assert not out.ok and 'no results were fabricated' in out.error


def test_multiple_titles_in_one_explicit_record_are_ambiguous(run):
    page='<div class="result"><a class="result__a" href="https://example.com/A">A</a><a class="result__a" href="https://example.com/B">B</a><a class="result__snippet">ambiguous</a></div>'
    assert run(page)==[]


def test_oversized_href_rejects_candidate_without_truncation_or_poisoning(run):
    page=result('Oversize','https://example.com/'+'x'*4096,'bad')+result('Good','https://example.com/good','Good snippet')
    assert run(page)==[{'title':'Good','url':'https://example.com/good','snippet':'Good snippet'}]


def test_one_anchor_cannot_be_both_title_and_snippet(run):
    page='<a class="result__a result__snippet" href="https://example.com/bad">ambiguous</a>'+result('Good')
    assert run(page)==[{'title':'Good','url':'https://example.com/a','snippet':'Snippet'}]
