import copy,json,random
from pathlib import Path
import pytest
from evaluation_v17a.schema import seal,canonical
from evaluation_v17a.scoring import evaluate
from evaluation_v17a.tests.test_harness import load,combine,m,assert_fraction
from evaluation_v17a.fixtures.build_corpus import base,defective,unsupported,numeric,contradiction,judgment,uncite,bind_citation

def metrics(d):return evaluate(seal(d))['micro_descriptive_metrics']
@pytest.mark.parametrize('field',['claims','sources','annotations','relations','reports','passages','tasks'])
def test_reorder_invariance(field):
    d=combine([load('E01'),load('E02'),load('E03')]);before=metrics(d);d[field].reverse();assert metrics(d)==before

def test_irrelevant_metadata_invariance():
    d=base();before=metrics(d);d['sources'][0]['limitations'].append('Metadata note.');d['annotations'][0]['notes']='Different annotation rationale.';assert metrics(d)==before

def test_duplicate_citation_invariance():
    d=combine([load('E01'),load('E02')]);before=metrics(d)
    k=copy.deepcopy(d['citations'][0]);old=k['id'];k['id']='extra:duplicate';d['citations'].append(k)
    a=copy.deepcopy(next(x for x in d['relations'] if x['citation_id']==old));a.update(id='extra:relation',citation_id=k['id']);d['relations'].append(a)
    assert metrics(d)==before

def test_serialization_order_invariance():
    d=load();r=evaluate(d);reversed_order=json.loads(json.dumps(d,sort_keys=True));assert evaluate(reversed_order)==r

def test_remove_evidence_rejudged_decreases_support():
    d=base();before=metrics(d);uncite(d);d['annotations'][0]['support']='missing_citation';defective(d)
    after=metrics(d);assert before['claim_support']['value']==1 and after['claim_support']['value']==0

def test_delete_evidence_without_rejudgment_is_invalid():
    d=base();d['passages']=[];assert evaluate(seal(d))['state']=='invalid_input'

def test_unrelated_relation_rejudgment_decreases_precision():
    d=base();before=metrics(d);d['citations'][0]['passage_id']='passage:2';bind_citation(d);unsupported(d)
    after=metrics(d);assert before['citation_precision']['value']==1 and after['citation_precision']['value']==0

def test_introduce_contradictory_evidence_and_rejudgment_changes_scores():
    d=base();before=metrics(d);contradiction(d);unsupported(d,'contradicted','correct_source_and_passage')
    after=metrics(d);assert after['claim_support']['value']<before['claim_support']['value'];assert after['contradiction_reflected']['value']==0

def test_remove_subquestion_judgment_decreases_completeness():
    d=base();before=metrics(d);d['questions']=[];defective(d);assert metrics(d)['research_completeness']['value']<before['research_completeness']['value']

def test_wrong_numeric_answer_decreases_score():
    d=base();numeric(d,'20');before=metrics(d);d['numerical_judgments'][0]['value']='21';defective(d);assert metrics(d)['numerical_correctness']['value']<before['numerical_correctness']['value']

def test_seeded_permutations_keep_scores():
    d=combine([load('E01'),load('E02'),load('E03'),load('E12')]);before=metrics(d);rng=random.Random(20261029)
    for _ in range(30):
        for key,value in d.items():
            if isinstance(value,list):rng.shuffle(value)
        assert metrics(d)==before
