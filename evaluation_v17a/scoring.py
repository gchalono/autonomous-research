"""Deterministic scoring of explicit judgments; never infers entailment or truth."""
from decimal import Decimal,ROUND_HALF_EVEN,localcontext
from fractions import Fraction
from pydantic import ValidationError
from .schema import Dataset,canonical,decimal
from . import SCHEMA_VERSION,SCORER_VERSION

def metric(n,d):
    if type(n)!=int or type(d)!=int or not 0<=n<=d:raise ValueError('inconsistent denominator')
    return {'numerator':n,'denominator':d,'value':float(Fraction(n,d)) if d else None,'status':'measurable' if d else 'undefined'}
def numerical_correct(ref,answer):
    if answer.unit!=ref.unit:return False
    if ref.undefined:return answer.value is None
    if answer.value is None:return False
    with localcontext() as ctx:
        ctx.prec=2300
        x,y=decimal(answer.value),decimal(ref.value)
        if ref.rounding_places is not None:
            q=Decimal(1).scaleb(-ref.rounding_places);x=x.quantize(q,rounding=ROUND_HALF_EVEN);y=y.quantize(q,rounding=ROUND_HALF_EVEN)
        if ref.mode=='exact':return x==y
        tolerance=decimal(ref.tolerance)
        return abs(x-y)<= (tolerance if ref.mode=='absolute' else tolerance*abs(y))
def supporting(a):return bool(a and a.status=='final' and a.support=='fully_supported' and a.attribution=='correct_source_and_passage')
def decisive(a):return bool(a and a.status=='final' and a.truth in ('correct','incorrect','partially_correct'))
def _score_report(ds,r):
    task=next(x for x in ds.tasks if x.id==r.task_id)
    claims=[c for c in ds.claims if c.report_id==r.id];N=len(claims)
    anns={a.claim_id:a for a in ds.annotations};rels={a.citation_id:a for a in ds.relations};passages={p.id:p for p in ds.passages}
    ks=[k for k in ds.citations if k.claim_id in r.all_claim_ids]
    unique={}
    for k in ks:
        p=passages[k.passage_id];unique[(k.claim_id,p.source_id,p.start,p.end)]=rels.get(k.id)
    def fully(c):
        a=anns.get(c.id)
        return bool(a and a.status=='final' and a.support=='fully_supported' and any(k.claim_id==c.id and supporting(rels.get(k.id)) for k in ks))
    final=[c for c in claims if decisive(anns.get(c.id))]
    m={
      'factual_correctness':metric(sum(anns[c.id].truth=='correct' for c in final),len(final)),
      'adjudication_coverage':metric(len(final),N),
      'annotation_coverage':metric(sum(c.id in anns for c in claims),N),
      'submission_coverage':metric(len(r.submitted_claim_ids),N),
      'claim_support':metric(sum(fully(c) for c in claims),N),
      'citation_coverage':metric(sum(fully(c) for c in claims),N),
      'citation_presence':metric(sum(any(k.claim_id==c.id for k in ks) for c in claims),N),
      'citation_precision':metric(sum(supporting(a) for a in unique.values()),sum(bool(a and a.status=='final') for a in unique.values())),
      'relation_adjudication_coverage':metric(sum(bool(a and a.status=='final') for a in unique.values()),len(unique)),
    }
    questions={q.subquestion_id:q for q in ds.questions if q.report_id==r.id}
    m['research_completeness']=metric(sum(bool(questions.get(q.id) and questions[q.id].status=='final' and questions[q.id].coverage=='full') for q in task.subquestions),len(task.subquestions))
    xs=[x for x in ds.contradictions if x.task_id==task.id and x.materiality in ('critical','material')]
    xj={x.contradiction_id:x for x in ds.contradiction_judgments if x.report_id==r.id}
    for step in ('identified','accurate','addressed','reflected'):
        m['contradiction_'+step]=metric(sum(bool(x.id in xj and xj[x.id].status=='final' and getattr(xj[x.id],step)) for x in xs),len(xs))
    ns=[n for n in ds.numerics if n.task_id==task.id];nj={n.numerical_reference_id:n for n in ds.numerical_judgments if n.report_id==r.id}
    m['numerical_correctness']=metric(sum(bool(n.id in nj and nj[n.id].status=='final' and numerical_correct(n,nj[n.id])) for n in ns),len(ns))
    m['numerical_annotation_coverage']=metric(sum(bool(n.id in nj and nj[n.id].status=='final') for n in ns),len(ns))
    auditor=next((a for a in ds.auditors if a.report_id==r.id),None)
    gold=next((g for g in ds.report_judgments if g.report_id==r.id),None)
    ref=next(x for x in ds.references if x.task_id==task.id)
    abstain=next((a for a in ds.abstentions if a.report_id==r.id),None)
    # Structural cross-checks prevent a final clean report label from overriding explicit defects.
    unresolved_issues=bool(auditor and any(i.severity in ('critical','material') and i.status in ('open','in_progress','unresolved') for i in auditor.issues))
    badclaims=[c for c in claims if c.materiality in ('critical','material') and anns.get(c.id) and anns[c.id].status=='final' and (anns[c.id].truth in ('incorrect','partially_correct') or anns[c.id].support in ('partially_supported','unsupported','contradicted','unverifiable','missing_citation'))]
    complete=bool(r.inventory_complete and N and all(decisive(anns.get(c.id)) and anns[c.id].support!='unverifiable' for c in claims) and len(r.submitted_claim_ids)==N)
    goodclaims=bool(complete and all(anns[c.id].truth=='correct' and fully(c) for c in claims))
    required_ok=m['research_completeness']['numerator']==m['research_completeness']['denominator']
    contradictions_ok=all(m['contradiction_'+s]['numerator']==len(xs) for s in ('identified','accurate','addressed','reflected'))
    numerics_ok=m['numerical_correctness']['numerator']==len(ns)
    clean=goodclaims and required_ok and contradictions_ok and numerics_ok and not unresolved_issues
    # Correct abstention can be clean without factual assertions, provided independent reference requires it.
    if not N and ref.status=='final' and ref.expected_action=='abstain' and abstain and abstain.action=='abstain':
        clean=r.inventory_complete and required_ok and contradictions_ok and numerics_ok and not unresolved_issues
    if gold and gold.status=='final' and gold.defect=='clean' and (not clean or ref.status!='final'):raise ValueError('contradictory final clean report adjudication')
    gf=bool(gold and gold.status=='final');bad=gf and gold.defect=='defective';good=gf and gold.defect=='clean'
    m['report_gold_coverage']=metric(int(gf),1)
    m['report_false_approval']=metric(int(bool(bad and auditor and auditor.decision=='approve')),int(bool(bad and auditor)))
    m['auditor_false_rejection']=metric(int(bool(good and auditor and auditor.decision!='approve')),int(bool(good and auditor)))
    m['claim_false_acceptance']=metric(sum(c.id in auditor.accepted_claim_ids for c in badclaims) if auditor else 0,len(badclaims) if auditor else 0)
    category=None
    if ref.status=='final' and abstain:
        if abstain.action=='abstain':category='correct_abstention' if ref.expected_action=='abstain' else 'unnecessary_abstention'
        else:category='correct_substantive_answer' if ref.expected_action=='answer' and clean else 'unsupported_confident_answer'
    expected_answer=ref.status=='final' and ref.expected_action=='answer'
    m['substantive_success']=metric(int(category=='correct_substantive_answer'),int(expected_answer))
    for cat in ['correct_abstention','unnecessary_abstention','unsupported_confident_answer','correct_substantive_answer']:
        m[cat]=metric(int(category==cat),int(category is not None))
    insuff=[]
    if not r.inventory_complete:insuff.append('claim_inventory_uncertified')
    if any(not decisive(anns.get(c.id)) or anns[c.id].status!='final' for c in claims):insuff.append('missing_or_unresolved_truth')
    if any(c.id not in anns or anns[c.id].status!='final' or anns[c.id].support=='unverifiable' for c in claims):insuff.append('missing_or_unresolved_support')
    if m['relation_adjudication_coverage']['numerator']<len(unique):insuff.append('missing_relation_labels')
    if any(q.id not in questions or questions[q.id].status!='final' for q in task.subquestions):insuff.append('missing_question_judgments')
    if any(x.id not in xj or xj[x.id].status!='final' for x in xs):insuff.append('missing_contradiction_judgments')
    if any(n.id not in nj or nj[n.id].status!='final' for n in ns):insuff.append('missing_numerical_judgments')
    if not gf:insuff.append('missing_final_report_gold')
    if ref.status!='final':insuff.append('missing_final_reference')
    trace=next((x for x in ds.traces if x.report_id==r.id),None)
    operational=trace.model_dump() if trace else None
    missing_trace=[k for k,v in operational.items() if v is None] if operational else ['trace_absent']
    return {'task_id':task.id,'report_id':r.id,'domain':task.domain,'status':'insufficient_adjudication' if insuff else 'valid','limitations':insuff,'inventory_complete_attested':r.inventory_complete,'inventory_origin_warning':'Attestation requires independent audit; no mechanical completeness proof.','metrics':m,'abstention_category':category,'operations':operational,'unavailable_operational_fields':missing_trace,'missing_claim_annotations':sorted(c.id for c in claims if c.id not in anns),'unresolved_material_audit_issue':unresolved_issues}

def evaluate(raw,*,config=None,timestamp=None,environment=None):
    try:
        # Always revalidate instances: mutable model lists must not bypass validators.
        ds=Dataset.model_validate(raw.model_dump() if isinstance(raw,Dataset) else raw)
        reports=sorted((_score_report(ds,r) for r in ds.reports),key=lambda x:x['task_id'])
        names=sorted(reports[0]['metrics'])
        totals={name:metric(sum(r['metrics'][name]['numerator'] for r in reports),sum(r['metrics'][name]['denominator'] for r in reports)) for name in names}
        result={'id':'result:'+ds.dataset_version,'state':'insufficient_adjudication' if any(r['status']!='valid' for r in reports) else 'valid','dataset_version':ds.dataset_version,'dataset_manifest_sha256':ds.manifest_sha256,'schema_version':SCHEMA_VERSION,'scorer_version':SCORER_VERSION,'candidate_versions':sorted({r.candidate_version for r in ds.reports}),'configuration':config or {},'timestamp':timestamp,'environment':environment or {},'reports':reports,'micro_descriptive_metrics':totals,'adjudication_origins':sorted({a.origin for a in ds.annotations}|{a.origin for a in ds.references}), 'all_supplied_truth_labels_declare_independent_human_origin':bool(ds.annotations and all(a.origin=='independent_human' and a.status=='final' for a in ds.annotations) and all(a.origin=='independent_human' and a.status=='final' for a in ds.references)), 'provenance_attestations_authenticated':False, 'research_accuracy_claim':'NONE: synthetic mechanics or supplied adjudications only'}
        canonical(result) # Fail closed on nonfinite metadata too.
        return result
    except (ValidationError,ValueError,TypeError,KeyError,ArithmeticError) as e:
        return {'state':'invalid_input','errors':[str(e)],'schema_version':SCHEMA_VERSION,'scorer_version':SCORER_VERSION}

def serialize(result):return canonical(result)+'\n'
