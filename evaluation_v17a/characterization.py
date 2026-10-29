"""Existing production defects: safe-behavior assertions intentionally XFAIL.
Separate from harness acceptance. No live dispatch, only deterministic stubs.
"""
import json,os
from pathlib import Path
import pytest
from src.models.contracts import ExecutionReport,SourceRecord,VerificationStatus
from src.agents.auditor import verify_sources
from src.agents.executor import _capped_items
from src.config import Settings
from src.storage.database import Store
from src.llm.provider import StubProvider,default_stub_behavior
from src.orchestration.engine import Orchestrator
from tests.conftest import fake_registry,fake_fetch

def record(key,data):
    p=Path(os.environ['AUDIT_WORK_ROOT'])/'characterization';p.mkdir(exist_ok=True);(p/(key+'.json')).write_text(json.dumps(data,indent=2))

def engine(tmp_path,behavior):
    settings=Settings.from_env();settings.projects_root=str(tmp_path/'projects')
    store=Store(str(tmp_path/'projects/research.db'))
    return Orchestrator(settings,store,client=StubProvider(behavior),registry=fake_registry(),fetch_fn=fake_fetch),store

@pytest.mark.xfail(strict=True,raises=AssertionError,reason='PROD-01: only first 60 normalized passage characters checked')
def test_prefix_fabrication_not_confirmed():
    prefix='A genuine frozen synthetic passage containing more than sixty characters. '
    quote=prefix+'This fabricated continuation declares a 99 percent improvement.'
    report=ExecutionReport(executive_summary='Synthetic.',sources=[SourceRecord(id='S1',url='https://example.invalid/synthetic',passage=quote)])
    observed=verify_sources(report,lambda _:('synthetic',prefix+'The real continuation contains no improvement claim.'))['S1']
    record('PROD-01',dict(input_quote=quote,fetched=prefix+'The real continuation contains no improvement claim.',observed=observed.value,expected='NOT_FOUND'))
    assert observed!=VerificationStatus.CONFIRMED

@pytest.mark.xfail(strict=True,raises=AssertionError,reason='PROD-02: unlisted factual summary with zero claims/citations can complete')
def test_zero_citation_factual_report_not_approved(tmp_path):
    behavior=default_stub_behavior();behavior['executor']={'executive_summary':'The synthetic treatment cures every patient.', 'findings':[],'claims':[],'sources':[],'limitations':[],'unresolved_dependencies':[]}
    # StubProvider expects a final ExecutorStep, not an agent dispatch override.
    behavior['executor']={'tool_calls':[],'done':True,'report':behavior['executor']}
    behavior['auditor']={'decision':'APPROVE','issues':[],'rationale':'Synthetic mistaken approval.'}
    orch,store=engine(tmp_path,behavior)
    try:
        pid=orch.create_project('Synthetic characterization only.');observed=orch.run(pid)
        record('PROD-02',dict(state=observed['state'],report=behavior['executor']['report'],expected='Must not complete factual report without independently evaluated claims/evidence.'))
        assert observed['state']!='COMPLETED'
    finally:store.close()

@pytest.mark.xfail(strict=True,raises=AssertionError,reason='PROD-03: relevant evidence can be dropped by oldest-round truncation')
def test_context_keeps_material_evidence():
    spec={'role':'user','content':'Synthesize the conflict.'}
    rounds=[[{'role':'user','content':'MATERIAL_CONTRADICTION: synthetic trial was retracted.'}], [{'role':'user','content':'Irrelevant filler '*100}]]
    result=_capped_items(spec,rounds,max_chars=200)
    record('PROD-03',dict(input_rounds=rounds,cap=200,observed=result,expected='Retain material evidence or enforce a non-answer when it is absent.'))
    assert 'MATERIAL_CONTRADICTION' in json.dumps(result)

@pytest.mark.xfail(strict=True,raises=AssertionError,reason='PROD-04: prior open issue persists in store but omitted next audit can approve')
def test_prior_critical_issue_blocks_later_approval(tmp_path):
    behavior=default_stub_behavior()
    def auditor(call_no,user):
        if call_no==1:return {'decision':'CORRECTIONS_REQUIRED','issues':[dict(id='PRIOR-CRITICAL',severity='CRITICAL',affected_claim_or_section='summary',description='Synthetic material attribution defect.',required_correction='Resolve with evidence.',status='OPEN')],'rationale':'Synthetic issue.'}
        return {'decision':'APPROVE','issues':[],'rationale':'Synthetic omitted issue.'}
    behavior['auditor']=auditor;orch,store=engine(tmp_path,behavior)
    try:
        pid=orch.create_project('Synthetic correction characterization.');observed=orch.run(pid);issues=store.list_issues(pid)
        record('PROD-04',dict(state=observed['state'],persisted_issues=issues,expected='Prior unresolved critical issue blocks final approval until explicit valid resolution.'))
        assert not (observed['state']=='COMPLETED' and any(i['id']=='PRIOR-CRITICAL' and i['status']=='OPEN' for i in issues))
    finally:store.close()
