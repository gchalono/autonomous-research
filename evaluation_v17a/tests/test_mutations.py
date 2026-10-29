"""Controlled evaluator mutations only, never edits production or assertions."""
import importlib.util,json,os,hashlib
from pathlib import Path
import pytest
from evaluation_v17a import scoring
from evaluation_v17a.tests.test_harness import load,combine
from evaluation_v17a.schema import seal

MUTATIONS=[
('missing_as_supported','a=anns.get(c.id)\n        return','a=anns.get(c.id)\n        if a is None: return True\n        return','E12','claim_support',(0,1)),
('duplicate_relations_counted','unique[(k.claim_id,p.source_id,p.start,p.end)]=','unique[(k.claim_id,p.source_id,p.start,p.end,k.id)]=','E21','citation_precision',(1,1)),
('partial_as_full',"a.support=='fully_supported'","a.support in ('fully_supported','partially_supported')",'E08','claim_support',(0,1)),
('empty_perfect','if d else None','if d else 1.0','E11','factual_correctness',(0,0)),
('ignore_unresolved_critical',"('open','in_progress','unresolved')","('open','in_progress')",'E24','unresolved',True),
('reverse_auditor_approval',"auditor.decision=='approve'","auditor.decision!='approve'",'E18','report_false_approval',(1,1)),
]

def observation(mod,case,name):
    r=mod.evaluate(load(case))
    if name=='unresolved':return r['reports'][0]['unresolved_material_audit_issue']
    x=r['micro_descriptive_metrics'][name]
    # Include empty-set value so a perfect-on-empty mutant cannot hide behind 0/0 metadata.
    return (x['numerator'],x['denominator'],x['value'])

@pytest.mark.parametrize('name,old,new,case,metric,expected',MUTATIONS,ids=[m[0] for m in MUTATIONS])
def test_controlled_mutation_detected(tmp_path,name,old,new,case,metric,expected):
    original=Path(scoring.__file__).read_text();assert old in original
    modified=original.replace(old,new);assert modified!=original
    file=tmp_path/(name+'.py');file.write_text(modified)
    spec=importlib.util.spec_from_file_location('evaluation_v17a._mutant_'+name,file);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    # Expectations are fixed cases and hand-specified values, not mutant output.
    wanted=expected if metric=='unresolved' else (*expected,expected[0]/expected[1] if expected[1] else None)
    actual=observation(scoring,case,metric);mutated=observation(mod,case,metric)
    evidence=Path(os.environ['AUDIT_WORK_ROOT'])/'evidence/mutations';evidence.mkdir(parents=True,exist_ok=True)
    (evidence/(name+'.json')).write_text(json.dumps({'mutation':name,'case':case,'metric':metric,'hand_expected':wanted,'original_observed':actual,'mutated_observed':mutated,'detected':mutated!=wanted,'original_source_sha256':hashlib.sha256(original.encode()).hexdigest(),'mutated_source_sha256':hashlib.sha256(modified.encode()).hexdigest()},indent=2))
    assert actual==wanted
    assert mutated!=wanted,'MATERIAL MUTATION SURVIVED'
