"""Independent fixture oracles, hand calculations and adversarial validation."""
import copy,json,math
from fractions import Fraction
from pathlib import Path
import pytest
from evaluation_v17a.schema import Dataset,seal,canonical,digest
from evaluation_v17a.scoring import evaluate,metric,serialize,numerical_correct
from evaluation_v17a.adapter import inventory_template
from evaluation_v17a.fixtures.build_corpus import base,judgment,numeric,certify,refresh,unsupported,defective,unknown,contradiction
FIX=Path(__file__).parents[1]/'fixtures'
def load(case='E01'):return json.loads((FIX/(case+'.json')).read_text())
def run(d):return evaluate(seal(d))
def m(r,name):return r['micro_descriptive_metrics'][name]
def assert_fraction(r,name,n,d):
    v=m(r,name);assert (v['numerator'],v['denominator'])==(n,d)
    assert v['value']==(float(Fraction(n,d)) if d else None)
    assert v['status']==('measurable' if d else 'undefined')

@pytest.mark.parametrize('case',[f'E{i:02}' for i in range(1,31)])
def test_frozen_oracle(case):
    # Never re-build expected labels from scorer output.
    oracle=json.loads((FIX/'ORACLES.json').read_text())[case];r=evaluate(load(case));assert r['state']==oracle['state'],r
    for name,(n,d) in oracle['metrics'].items():assert_fraction(r,name,n,d)
    assert oracle['reason']

def combine(parts):
    # Distinct research tasks, not correlated claims masquerading as independent samples.
    result=copy.deepcopy(parts[0]);fields=[k for k,v in result.items() if isinstance(v,list)]
    for k in fields:result[k]=[]
    for i,part in enumerate(parts):
        ids=set()
        def gather(x):
            if isinstance(x,dict):
                if 'id' in x:ids.add(x['id'])
                for v in x.values():gather(v)
            elif isinstance(x,list):
                for v in x:gather(v)
        gather(part)
        def rename(x):
            if isinstance(x,str):return str(i)+':'+x if x in ids else x
            if isinstance(x,list):return [rename(v) for v in x]
            if isinstance(x,dict):return {k:rename(v) for k,v in x.items()}
            return x
        part=rename(part)
        refresh(part)
        for k in fields:result[k].extend(part[k])
    result['dataset_version']='hand-four-tasks-v1';return seal(result)

def test_hand_calculated_four_tasks():
    d=combine([load('E01'),load('E02'),load('E03'),load('E12')]);r=evaluate(d)
    assert r['state']=='insufficient_adjudication'
    # 2 correct / 3 decisive; one supported / all 4 inventoried; 4 genuine relations, 2 judged supportive.
    assert_fraction(r,'factual_correctness',2,3);assert_fraction(r,'adjudication_coverage',3,4)
    assert_fraction(r,'claim_support',1,4);assert_fraction(r,'citation_precision',2,4)
    assert_fraction(r,'report_false_approval',2,2)

def independent_support_oracle(raw):
    # Set-intersection approach independent of report traversal and helper predicates.
    labels={x['claim_id']:x for x in raw['annotations']}
    judged={x['citation_id']:x for x in raw['relations']}
    witnessed=set()
    for citation in raw['citations']:
        label=judged.get(citation['id'],{})
        if (label.get('status'),label.get('support'),label.get('attribution'))==('final','fully_supported','correct_source_and_passage'):witnessed.add(citation['claim_id'])
    eligible={c['id'] for c in raw['claims']}
    labeled={cid for cid,a in labels.items() if (a['status'],a['support'])==('final','fully_supported')}
    return len(eligible & labeled & witnessed),len(eligible)
@pytest.mark.parametrize('case',['E01','E02','E03','E08','E09','E11','E12','E20','E21','E28'])
def test_independent_set_oracle(case):
    d=load(case);r=evaluate(d);n,den=independent_support_oracle(d);assert_fraction(r,'claim_support',n,den)

INVALID_MUTATIONS=[
('task_id_duplicate',lambda d:d['tasks'].append(copy.deepcopy(d['tasks'][0]))),
('claim_id_duplicate',lambda d:d['claims'].append(copy.deepcopy(d['claims'][0]))),
('source_missing',lambda d:d.update(sources=[])),
('source_bad_hash',lambda d:d['sources'][0].update(sha256='0'*64)),
('citation_dangling',lambda d:d['citations'][0].update(passage_id='absent')),
('passage_prefix_forgery',lambda d:d['passages'][0].update(text=d['passages'][0]['text']+' invented')),
('negative_offset',lambda d:d['passages'][0].update(start=-1)),
('bad_end',lambda d:d['passages'][0].update(end=99999)),
('bad_label',lambda d:d['annotations'][0].update(truth='probably')),
('bad_status',lambda d:d['annotations'][0].update(status='ACCEPT')),
('missing_field',lambda d:d['tasks'][0].pop('objective')),
('extra_field',lambda d:d['tasks'][0].update(hidden_override=True)),
('bad_schema',lambda d:d.update(schema_version='v99')),
('bool_offset',lambda d:d['passages'][0].update(start=True)),
('cross_task',lambda d:d['reports'][0].update(task_id='absent')),
('submitted_not_in_inventory',lambda d:d['reports'][0]['submitted_claim_ids'].append('absent')),
('all_claims_omitted',lambda d:d['reports'][0].update(all_claim_ids=[])),
('segment_gap',lambda d:d['reports'][0]['segments'][0].update(start=1)),
('segment_false_nonfactual',lambda d:d['reports'][0]['segments'][1].update(kind='nonfactual')),
('nonindependent_reference',lambda d:d['references'][0].update(blinded_to_engine=False)),
('unlabeled_synthetic',lambda d:d['sources'][0].update(provenance={})),
('contradictory_support',lambda d:d['relations'][0].update(attribution='wrong_source')),
('unresolvable_invalid_label',lambda d:d['relations'][0].update(attribution='invalid_reference',support='unsupported')),
('missing_reference',lambda d:d.update(references=[])),
('nonfinite_trace',lambda d:d['traces'][0].update(actual_cost_usd=float('inf'))),
]
@pytest.mark.parametrize('name,mutate',INVALID_MUTATIONS,ids=[x[0] for x in INVALID_MUTATIONS])
def test_invalid_schema(name,mutate):
    d=base();mutate(d)
    try:d=seal(d)
    except ValueError: # Nonfinite JSON is rejected at encoding too; exercise validator directly below.
        d['manifest_sha256']='0'*64
    assert evaluate(d)['state']=='invalid_input'

def test_frozen_manifest_tamper():
    d=load();d['references'][0]['answer']='changed';assert evaluate(d)['state']=='invalid_input'

def test_uncertified_inventory_never_comprehensive():
    d=base();d['reports'][0].update(inventory_complete=False,inventory_reviewer=None,segments=[]);unknown(d)
    r=run(d);assert r['state']=='insufficient_adjudication';assert not r['reports'][0]['inventory_complete_attested']

def test_missing_claim_not_submitted_stays_denominator():
    d=base();d['reports'][0]['submitted_claim_ids']=[];d['annotations']=[];unknown(d)
    r=run(d);assert_fraction(r,'claim_support',0,1);assert_fraction(r,'submission_coverage',0,1)

def test_duplicate_relation_inconsistent_judgment_invalid():
    d=load('E21');d['relations'][1]['support']='unsupported';assert run(d)['state']=='invalid_input'

def test_duplicate_relation_missing_label_invalid():
    d=load('E21');d['relations'].pop();assert run(d)['state']=='invalid_input'

def test_missing_relation_label_not_perfect():
    d=base();d['relations']=[];d['annotations'][0]['status']='unresolved';unknown(d)
    r=run(d);assert r['state']=='insufficient_adjudication';assert_fraction(r,'citation_precision',0,0);assert_fraction(r,'claim_support',0,1)

def test_missing_trace_values_not_zero():
    r=evaluate(load());o=r['reports'][0];assert o['operations']['model_calls'] is None;assert 'actual_cost_usd' in o['unavailable_operational_fields']

def test_contradictory_clean_gold_rejected():
    d=load('E24');d['report_judgments'][0]['defect']='clean';assert run(d)['state']=='invalid_input'

@pytest.mark.parametrize('field',['truth','support'])
def test_nonfinal_labels_not_full_credit(field):
    d=base();d['annotations'][0]['status']='provisional';unknown(d);r=run(d)
    assert r['state']=='insufficient_adjudication';assert_fraction(r,'factual_correctness',0,0);assert_fraction(r,'claim_support',0,1)

def test_denominator_guard():
    for n,d in [(2,1),(-1,2),(1,0),(True,1)]:
        with pytest.raises(ValueError):metric(n,d)

@pytest.mark.parametrize('mode,tol,reference,answer,unit,places,expected',[
('exact','0','20','20','person-days',None,True),('exact','0','20','20','days',None,False),
('absolute','0.1','20','20.1','person-days',None,True),('absolute','0.1','20','20.1001','person-days',None,False),
('relative','0.01','20','20.2','person-days',None,True),('relative','0.01','0','0.01','person-days',None,False),
('exact','0','1.245','1.244','person-days',2,True),('exact','0','1.255','1.245','person-days',2,False),
])
def test_numeric_boundaries(mode,tol,reference,answer,unit,places,expected):
    d=base();numeric(d,answer);d['numerics'][0].update(mode=mode,tolerance=tol,value=reference,rounding_places=places);d['numerical_judgments'][0]['unit']=unit
    if not expected:defective(d)
    r=run(d);assert r['state']=='valid',r;assert_fraction(r,'numerical_correctness',int(expected),1)
@pytest.mark.parametrize('mode,tolerance',[('absolute','-1'),('relative','1.1'),('exact','0.1'),('absolute','NaN'),('absolute','Infinity')])
def test_invalid_tolerances(mode,tolerance):
    d=base();numeric(d);d['numerics'][0].update(mode=mode,tolerance=tolerance);assert run(d)['state']=='invalid_input'
@pytest.mark.parametrize('answer,expected',[(None,True),('0',False)])
def test_undefined_calculation(answer,expected):
    d=base();numeric(d,answer);d['numerics'][0].update(value=None,undefined=True)
    if not expected:defective(d)
    r=run(d);assert_fraction(r,'numerical_correctness',int(expected),1)

def test_adapter_covers_unlisted_summary_claim():
    payload={'executive_summary':'Unlisted claim: the synthetic trial enrolled 99 people.','claims':[],'findings':[],'sources':[],'limitations':['Unverified.'],'unresolved_dependencies':[]}
    r=inventory_template(payload,'report:1','task:1','synthetic');assert not r['inventory_complete'];assert '99 people' in r['text'];assert not r['all_claim_ids']

def test_end_to_end_roundtrip_and_intentional_defect():
    d=load();Dataset.model_validate(d);a=evaluate(json.loads(canonical(d)),timestamp='2026-10-29',environment={'python':'recorded'})
    assert serialize(a)==serialize(evaluate(json.loads(canonical(d)),timestamp='2026-10-29',environment={'python':'recorded'}))
    bad=load('E02');b=evaluate(bad);assert m(a,'claim_support')['value']==1;assert m(b,'claim_support')['value']==0
    assert a['reports'][0]['operations']['actual_cost_usd'] is None

def test_cli_demo_with_retained_outputs(tmp_path):
    import os,subprocess,sys
    output=Path(os.environ['AUDIT_WORK_ROOT'])/'demonstration';output.mkdir(exist_ok=True)
    for case,name in [('E01','supported'),('E02','unrelated_citation')]:
        source=output/(name+'_input.json');dest=output/(name+'_result.json');source.write_text(canonical(load(case)))
        result=subprocess.run([sys.executable,'-m','evaluation_v17a.cli',str(source),str(dest)],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        scored=json.loads(dest.read_text());assert scored['state']=='valid'
        assert_fraction(scored,'claim_support',int(case=='E01'),1)
    (output/'README.md').write_text('Synthetic mechanics demonstration only. Two engine-format reports with frozen sources and developer-authored labels. Supported case earns 1/1 support; unrelated citation earns 0/1. No research engine accuracy measured.\n')

def test_unresolved_critical_issue_is_visible():
    r=evaluate(load('E24'));assert r['reports'][0]['unresolved_material_audit_issue'] is True

def test_rendering_integrity_blocks_uninventoried_payload_change():
    d=load();d['reports'][0]['engine_payload']['executive_summary']+=' Hidden new assertion.';assert run(d)['state']=='invalid_input'

def test_missing_numerical_label_no_full_credit():
    d=base();numeric(d,'20');d['numerical_judgments']=[];defective(d);r=run(d);assert_fraction(r,'numerical_correctness',0,1)

def test_missing_report_gold_remains_insufficient():
    d=base();d['report_judgments']=[];r=run(d);assert r['state']=='insufficient_adjudication';assert_fraction(r,'report_gold_coverage',0,1)

def test_human_origin_not_inferred_from_fixture():
    d=load();assert d['references'][0]['origin']=='synthetic_developer';assert d['annotations'][0]['origin']=='synthetic_developer'

@pytest.mark.parametrize('kind',['absolute','relative'])
def test_extreme_but_bounded_decimals(kind):
    d=base();numeric(d,'1e1000');d['numerics'][0].update(value='1e1000',mode=kind,tolerance='0',rounding_places=2);r=run(d);assert_fraction(r,'numerical_correctness',1,1)

def test_unverified_final_labels_rejected():
    d=base();d['annotations'][0]['origin']='unverified';assert run(d)['state']=='invalid_input'

def test_synthetic_labels_explicit_in_result():
    r=evaluate(load());assert r['adjudication_origins']==['synthetic_developer'];assert not r['all_supplied_truth_labels_declare_independent_human_origin']

def test_cannot_omit_bad_actual_engine_citation():
    d=base();r=d['reports'][0];r['engine_payload']['claims'][0]['source_ids'].append('engine:S2')
    r['engine_payload']['sources'].append(dict(r['engine_payload']['sources'][0],id='engine:S2',url=d['sources'][1]['description'],passage=d['passages'][1]['text']))
    refresh(d);assert run(d)['state']=='invalid_input'

def test_extra_bad_actual_citation_penalizes_precision():
    d=base();r=d['reports'][0];r['engine_payload']['claims'][0]['source_ids'].append('engine:S2')
    r['engine_payload']['sources'].append(dict(r['engine_payload']['sources'][0],id='engine:S2',url=d['sources'][1]['description'],passage=d['passages'][1]['text']))
    d['citations'].append(dict(id='citation:2',engine_source_id='engine:S2',claim_id='claim:1',passage_id='passage:2'))
    d['relations'].append(judgment('relation:2',citation_id='citation:2',support='unsupported',attribution='wrong_source'))
    refresh(d);r=run(d);assert r['state']=='valid',r;assert_fraction(r,'citation_precision',1,2);assert_fraction(r,'claim_support',1,1)

def test_cannot_add_evaluation_only_citation():
    d=base();d['reports'][0]['engine_payload']['claims'][0]['source_ids']=[];refresh(d);assert run(d)['state']=='invalid_input'

def test_cannot_map_claim_to_quoted_source_location():
    d=base();c=d['claims'][0];r=d['reports'][0];start=r['text'].rindex(c['text']);assert start!=c['start']
    c.update(start=start,end=start+len(c['text']));certify(r,[c]);assert run(d)['state']=='invalid_input'

def test_entire_actual_engine_quote_must_match():
    d=base();d['reports'][0]['engine_payload']['sources'][0]['passage']+=' Fabricated continuation.';refresh(d);assert run(d)['state']=='invalid_input'

def test_normative_engine_statement_can_be_excluded_explicitly():
    d=load('E14');r=d['reports'][0];r['engine_payload']['claims']=[dict(id='normative',text='We should seek more evidence.',classification='HYPOTHETICAL',source_ids=[])]
    r['excluded_engine_claims']={'normative':'Normative recommendation, no empirical proposition.'};refresh(d)
    assert run(d)['state']=='valid'

def test_repeated_proposition_has_one_scoring_unit_multiple_locations():
    from evaluation_v17a.adapter import render_with_locations
    d=base();r=d['reports'][0];r['engine_payload']['executive_summary']=d['claims'][0]['text'];refresh(d)
    c=d['claims'][0];lo,hi=render_with_locations(r['engine_payload'])[1]['$.executive_summary'];c['additional_locations']=[dict(start=lo,end=hi)]
    spans=sorted([(c['start'],c['end']),(lo,hi)]);r['segments']=[];pos=0
    for start,end in spans:
        if start>pos:r['segments'].append(dict(start=pos,end=start,kind='nonfactual',claim_ids=[]))
        r['segments'].append(dict(start=start,end=end,kind='factual',claim_ids=[c['id']]));pos=end
    if pos<len(r['text']):r['segments'].append(dict(start=pos,end=len(r['text']),kind='nonfactual',claim_ids=[]))
    result=run(d);assert result['state']=='valid',result;assert_fraction(result,'claim_support',1,1)

def test_multiline_unicode_engine_text_preserves_offsets():
    from evaluation_v17a.fixtures.build_corpus import change_claim,bind_citation
    d=base();text='Synthetic café enrolled "10" participants.\nUnicode line: α.'
    d['sources'][0]['content']=text;d['sources'][0]['sha256']=digest(text);d['passages'][0].update(start=0,end=len(text),text=text)
    change_claim(d,text);bind_citation(d);result=run(d);assert result['state']=='valid',result
