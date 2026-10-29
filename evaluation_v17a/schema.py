"""Strict evaluation entities and cross-entity validation (no semantic oracle)."""
from __future__ import annotations
import hashlib,json,re
from decimal import Decimal,InvalidOperation
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from . import SCHEMA_VERSION
Status=Literal['final','provisional','disputed','unresolved','missing']
Truth=Literal['correct','incorrect','partially_correct','indeterminate','not_evaluated']
Support=Literal['fully_supported','partially_supported','unsupported','contradicted','unverifiable','missing_citation']
Attribution=Literal['correct_source_and_passage','correct_source_wrong_passage','wrong_source','invalid_reference','no_reference']
Materiality=Literal['critical','material','minor','not_applicable']
Origin=Literal['synthetic_developer','independent_human','unverified']

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def decimal(value):
    try:d=Decimal(value)
    except (InvalidOperation,TypeError,ValueError):raise ValueError('invalid decimal') from None
    if not d.is_finite() or len(value)>128 or abs(d.adjusted())>1000:raise ValueError('nonfinite or unbounded decimal')
    return d
class Entity(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    id:str=Field(min_length=1,max_length=160)
class Subquestion(Entity):
    text:str=Field(min_length=1)
class Source(Entity):
    description:str=Field(min_length=1)
    source_type:str
    captured_at:str|None
    content:str
    sha256:str=Field(pattern='^[a-f0-9]{64}$')
    encoding:Literal['utf-8']
    origin:Origin
    provenance:dict[str,str]
    limitations:list[str]
class Passage(Entity):
    source_id:str
    start:int=Field(ge=0)
    end:int=Field(ge=0)
    text:str=Field(min_length=1)
class Task(Entity):
    objective:str=Field(min_length=1)
    domain:str=Field(min_length=1)
    subquestions:list[Subquestion]
    evidence_types:list[str]
    temporal_assumptions:str
    source_ids:list[str]
    rubric:str
    limitations:list[str]
class Reference(Entity):
    task_id:str
    answer:str
    origin:Origin
    annotators:list[str]
    blinded_to_engine:bool
    blinded_to_auditor:bool
    disagreements:list[str]
    adjudication_notes:str
    label_version:str
    status:Status
    expected_action:Literal['answer','abstain']
class Segment(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    start:int=Field(ge=0)
    end:int=Field(ge=0)
    kind:Literal['factual','nonfactual']
    claim_ids:list[str]
class Report(Entity):
    task_id:str
    text:str
    engine_payload:dict
    candidate_version:str
    all_claim_ids:list[str]
    submitted_claim_ids:list[str]
    excluded_engine_claims:dict[str,str]
    inventory_complete:bool
    inventory_reviewer:str|None
    inventory_method:str
    segments:list[Segment]
class ClaimLocation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    start:int=Field(ge=0)
    end:int=Field(ge=0)
class Claim(Entity):
    report_id:str
    text:str=Field(min_length=1)
    start:int=Field(ge=0)
    end:int=Field(ge=0)
    additional_locations:list[ClaimLocation]
    engine_claim_id:str|None
    proposition_key:str=Field(min_length=1)
    atomic_propositions:int=Field(ge=1,le=1)
    materiality:Materiality
class Citation(Entity):
    engine_source_id:str
    claim_id:str
    passage_id:str
class Judgment(Entity):
    origin:Origin
    annotator:str=Field(min_length=1)
    status:Status
    notes:str
    @model_validator(mode='after')
    def verified_final_origin(self):
        if self.status=='final' and self.origin=='unverified':raise ValueError('unverified final adjudication')
        return self
class Annotation(Judgment):
    claim_id:str
    truth:Truth
    support:Support
class RelationAnnotation(Judgment):
    citation_id:str
    support:Support
    attribution:Attribution
class QuestionJudgment(Judgment):
    report_id:str
    subquestion_id:str
    coverage:Literal['full','partial','missing','unresolved']
class Contradiction(Entity):
    task_id:str
    passage_ids:list[str]=Field(min_length=2)
    materiality:Materiality
    description:str
class ContradictionJudgment(Judgment):
    report_id:str
    contradiction_id:str
    identified:bool
    accurate:bool
    addressed:bool
    reflected:bool
class NumericalReference(Entity):
    task_id:str
    expression:str
    value:str|None
    undefined:bool
    unit:str=Field(min_length=1)
    mode:Literal['exact','absolute','relative']
    tolerance:str
    rounding_places:int|None=Field(default=None,ge=0,le=20)
    @model_validator(mode='after')
    def valid_number(self):
        t=decimal(self.tolerance)
        if t<0 or (self.mode=='exact' and t!=0) or (self.mode=='relative' and t>1):raise ValueError('invalid tolerance')
        if self.undefined!=(self.value is None):raise ValueError('undefined/value mismatch')
        if self.value is not None:decimal(self.value)
        return self
class NumericalJudgment(Judgment):
    report_id:str
    numerical_reference_id:str
    value:str|None
    unit:str
    @model_validator(mode='after')
    def valid_number(self):
        if self.value is not None:decimal(self.value)
        return self
class Abstention(Entity):
    report_id:str
    action:Literal['answer','abstain']
    rationale:str
class Issue(Entity):
    severity:Materiality
    status:Literal['open','in_progress','resolved','unresolved','superseded']
    description:str
class Auditor(Entity):
    report_id:str
    decision:Literal['approve','corrections_required','inconclusive','blocked']
    accepted_claim_ids:list[str]
    issues:list[Issue]
class ReportJudgment(Judgment):
    report_id:str
    defect:Literal['defective','clean','unresolved']
class Trace(Entity):
    report_id:str
    model_calls:int|None=Field(ge=0)
    input_tokens:int|None=Field(ge=0)
    output_tokens:int|None=Field(ge=0)
    reasoning_tokens:int|None=Field(ge=0)
    tool_calls:int|None=Field(ge=0)
    actual_cost_usd:float|None=Field(ge=0)
    estimated_cost_usd:float|None=Field(ge=0)
    latency_seconds:float|None=Field(ge=0)
    retries:int|None=Field(ge=0)
    failures:int|None=Field(ge=0)
    human_interventions:int|None=Field(ge=0)
    context_truncations:int|None=Field(ge=0)
    missing_evidence:int|None=Field(ge=0)
    terminal_status:str|None
class Dataset(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    schema_version:Literal['v17a.1']
    dataset_version:str=Field(min_length=1)
    manifest_sha256:str=Field(pattern='^[a-f0-9]{64}$')
    tasks:list[Task]=Field(min_length=1)
    sources:list[Source]
    passages:list[Passage]
    references:list[Reference]
    reports:list[Report]=Field(min_length=1)
    claims:list[Claim]
    citations:list[Citation]
    annotations:list[Annotation]
    relations:list[RelationAnnotation]
    questions:list[QuestionJudgment]
    contradictions:list[Contradiction]
    contradiction_judgments:list[ContradictionJudgment]
    numerics:list[NumericalReference]
    numerical_judgments:list[NumericalJudgment]
    abstentions:list[Abstention]
    auditors:list[Auditor]
    report_judgments:list[ReportJudgment]
    traces:list[Trace]
    @model_validator(mode='after')
    def cross_validate(self):
        raw=self.model_dump();seal=raw.pop('manifest_sha256')
        if digest(canonical(raw))!=seal:raise ValueError('dataset manifest mismatch')
        groups=[v for v in self.__dict__.values() if isinstance(v,list)]
        entities=[e for g in groups for e in g]
        entities += [q for t in self.tasks for q in t.subquestions]+[i for a in self.auditors for i in a.issues]
        ids=[e.id for e in entities]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate entity ID')
        tables={name:{x.id:x for x in getattr(self,name)} for name in ['tasks','sources','passages','reports','claims','citations','contradictions','numerics']}
        T,S,P,R,C,K,X,N=[tables[n] for n in tables]
        def req(mapping,key):
            if key not in mapping:raise ValueError('dangling reference: '+key)
            return mapping[key]
        def unique(values):
            if len(values)!=len(set(values)):raise ValueError('duplicate relationship')
        for s in self.sources:
            if digest(s.content)!=s.sha256:raise ValueError('snapshot hash mismatch')
            if s.origin=='synthetic_developer' and s.provenance.get('synthetic')!='true':raise ValueError('synthetic source not labeled')
        for t in self.tasks:
            unique(t.source_ids)
            for s in t.source_ids:req(S,s)
        for p in self.passages:
            s=req(S,p.source_id)
            if not (p.start<p.end<=len(s.content)) or s.content[p.start:p.end]!=p.text:raise ValueError('invalid full evidence span')
        for x in self.contradictions:
            t=req(T,x.task_id);unique(x.passage_ids)
            for p in x.passage_ids:
                if req(P,p).source_id not in t.source_ids:raise ValueError('contradiction outside task sources')
        for n in self.numerics:req(T,n.task_id)
        for ref in self.references:
            req(T,ref.task_id)
            if ref.status=='final' and ref.origin=='unverified':raise ValueError('unverified final reference')
            if ref.status=='final' and (not ref.annotators or not ref.blinded_to_engine or not ref.blinded_to_auditor):raise ValueError('invalid final reference protocol')
            if ref.status=='final' and not ref.adjudication_notes:raise ValueError('missing adjudication notes')
        unique([x.task_id for x in self.references])
        if {x.task_id for x in self.references}!=set(T):raise ValueError('missing reference answer')
        unique([r.task_id for r in self.reports]) # one candidate/report per task in one run
        if {r.task_id for r in self.reports}!=set(T):raise ValueError('missing task report')
        by_report={r.id:[] for r in self.reports}
        for c in self.claims:
            r=req(R,c.report_id);by_report[r.id].append(c)
            spans=[(c.start,c.end)]+[(p.start,p.end) for p in c.additional_locations]
            unique(spans)
            for start,end in spans:
                if not (start<end<=len(r.text)) or r.text[start:end]!=c.text:raise ValueError('invalid claim location')
        for r in self.reports:
            from .adapter import render_payload
            from src.models.contracts import ExecutionReport
            normalized=ExecutionReport.model_validate(r.engine_payload).model_dump(mode='json')
            if normalized!=r.engine_payload or render_payload(normalized)!=r.text:raise ValueError('engine report rendering mismatch')
            req(T,r.task_id);unique(r.all_claim_ids);unique(r.submitted_claim_ids)
            if set(r.all_claim_ids)!={c.id for c in by_report[r.id]}:raise ValueError('incomplete claim inventory references')
            if not set(r.submitted_claim_ids)<=set(r.all_claim_ids):raise ValueError('submission outside inventory')
            keys=[c.proposition_key for c in by_report[r.id]];texts=[re.sub(r'\s+',' ',c.text.casefold()).strip() for c in by_report[r.id]]
            unique(keys);unique(texts)
            if r.inventory_complete:
                if not r.inventory_reviewer or not r.inventory_method:raise ValueError('uncertified complete inventory')
                pos=0;seen=set()
                for seg in r.segments:
                    if seg.start!=pos or not seg.start<seg.end<=len(r.text):raise ValueError('inventory segment gap/overlap')
                    pos=seg.end;unique(seg.claim_ids)
                    if (seg.kind=='factual')!=bool(seg.claim_ids):raise ValueError('factual segment missing claim')
                    for cid in seg.claim_ids:
                        c=req(C,cid)
                        if c.report_id!=r.id or not any(max(a,seg.start)<min(b,seg.end) for a,b in [(c.start,c.end)]+[(p.start,p.end) for p in c.additional_locations]):raise ValueError('segment attribution mismatch')
                        seen.add(cid)
                if pos!=len(r.text) or seen!=set(r.all_claim_ids):raise ValueError('incomplete certified inventory')
                for c in by_report[r.id]:
                    for start,end in [(c.start,c.end)]+[(p.start,p.end) for p in c.additional_locations]:
                        if any(seg.kind!='factual' for seg in r.segments if max(start,seg.start)<min(end,seg.end)):raise ValueError('claim span marked nonfactual')
        for r in self.reports:
            engine_claims=r.engine_payload['claims'];engine_sources=r.engine_payload['sources']
            unique([c['id'] for c in engine_claims]);unique([s['id'] for s in engine_sources])
            linked={c.engine_claim_id for c in by_report[r.id] if c.engine_claim_id is not None}
            excluded=set(r.excluded_engine_claims)
            if linked & excluded or any(not reason.strip() for reason in r.excluded_engine_claims.values()) or not excluded<={c['id'] for c in engine_claims}:raise ValueError('invalid normative engine-claim exclusion')
            if r.inventory_complete and {c['id'] for c in engine_claims}!=linked|excluded:raise ValueError('inventoried engine claim mismatch')
            if r.inventory_complete:
                from .adapter import render_with_locations
                locations=render_with_locations(r.engine_payload)[1]
                for i,x in enumerate(engine_claims):
                    if x['id'] in excluded:
                        lo,hi=locations['$.claims['+str(i)+'].text']
                        if any(seg.kind=='factual' and max(lo,seg.start)<min(hi,seg.end) for seg in r.segments):raise ValueError('normative exclusion overlaps factual segment')
        for c in self.claims:
            r=R[c.report_id];ec={x['id']:x for x in r.engine_payload['claims']}
            cited={k.engine_source_id for k in self.citations if k.claim_id==c.id}
            if c.engine_claim_id is None:
                if cited:raise ValueError('cannot invent citation on unlisted engine claim')
            else:
                e=req(ec,c.engine_claim_id)
                from .adapter import render_with_locations
                index=next(i for i,x in enumerate(r.engine_payload['claims']) if x['id']==c.engine_claim_id)
                lo,hi=render_with_locations(r.engine_payload)[1]['$.claims['+str(index)+'].text']
                if c.text not in e['text'] or not lo<=c.start<c.end<=hi:raise ValueError('claim does not correspond to actual engine claim text location')
                if cited!=set(e['source_ids']):raise ValueError('omitted or added engine citation relationship')
        for k in self.citations:
            c=req(C,k.claim_id);p=req(P,k.passage_id);r=R[c.report_id]
            s=req({s['id']:s for s in r.engine_payload['sources']},k.engine_source_id)
            if s['url']!=S[p.source_id].description or s['passage']!=p.text:raise ValueError('citation not bound to actual engine source and full quote')
            if p.source_id not in T[r.task_id].source_ids:raise ValueError('citation outside task sources')
        ann={}
        for a in self.annotations:
            c=req(C,a.claim_id)
            if a.claim_id not in R[c.report_id].submitted_claim_ids:raise ValueError('annotation not submitted')
            if a.status=='missing' and (a.truth!='not_evaluated' or a.support!='unverifiable'):raise ValueError('contradictory missing annotation')
            if a.claim_id in ann:raise ValueError('duplicate claim annotation')
            ann[a.claim_id]=a
        rel={};normalized={}
        for a in self.relations:
            k=req(K,a.citation_id);p=P[k.passage_id]
            if a.citation_id in rel:raise ValueError('duplicate relation annotation')
            if a.status=='missing' and a.support!='unverifiable':raise ValueError('contradictory missing relation annotation')
            if a.attribution in ('invalid_reference','no_reference'):raise ValueError('existing citation contradicts reference status')
            if a.support=='fully_supported' and a.attribution!='correct_source_and_passage':raise ValueError('contradictory support/attribution')
            key=(k.claim_id,p.source_id,p.start,p.end)
            label=(a.support,a.attribution,a.status)
            if key in normalized and normalized[key]!=label:raise ValueError('conflicting duplicate citation labels')
            normalized[key]=label;rel[k.id]=a
        # A duplicated relationship cannot lose its annotation to evade coverage.
        for k in self.citations:
            p=P[k.passage_id];key=(k.claim_id,p.source_id,p.start,p.end)
            if key in normalized and k.id not in rel:raise ValueError('duplicate citation missing consistent annotation')
        for cid,a in ann.items():
            cited=[k for k in self.citations if k.claim_id==cid]
            if a.support=='missing_citation' and cited:raise ValueError('missing citation label with citation')
            if a.status=='final' and a.support=='fully_supported' and not any(k.id in rel and rel[k.id].status=='final' and rel[k.id].support=='fully_supported' and rel[k.id].attribution=='correct_source_and_passage' for k in cited):raise ValueError('fully supported without judged evidence')
        def report_link(x):return req(R,x.report_id)
        for name,target_key in [('abstentions','report_id'),('auditors','report_id'),('report_judgments','report_id'),('traces','report_id')]:
            xs=getattr(self,name);unique([getattr(x,target_key) for x in xs])
            for x in xs:report_link(x)
        for a in self.auditors:
            unique(a.accepted_claim_ids)
            for cid in a.accepted_claim_ids:
                if req(C,cid).report_id!=a.report_id:raise ValueError('auditor accepts foreign claim')
        unique([(x.report_id,x.subquestion_id) for x in self.questions])
        for q in self.questions:
            r=report_link(q)
            if q.subquestion_id not in {s.id for s in T[r.task_id].subquestions}:raise ValueError('foreign subquestion')
        unique([(x.report_id,x.contradiction_id) for x in self.contradiction_judgments])
        for x in self.contradiction_judgments:
            if req(X,x.contradiction_id).task_id!=report_link(x).task_id:raise ValueError('foreign contradiction')
            if (x.accurate or x.addressed or x.reflected) and not x.identified:raise ValueError('unidentified contradiction marked handled')
            if x.reflected and not (x.accurate and x.addressed):raise ValueError('unaddressed contradiction reflected')
        unique([(x.report_id,x.numerical_reference_id) for x in self.numerical_judgments])
        for n in self.numerical_judgments:
            if req(N,n.numerical_reference_id).task_id!=report_link(n).task_id:raise ValueError('foreign numerical reference')
        for j in self.report_judgments:
            if j.status=='final' and j.defect=='unresolved':raise ValueError('final unresolved report gold')
            if j.status=='missing' and j.defect!='unresolved':raise ValueError('missing report gold has decision')
        return self

def seal(raw):
    """For dataset authors only, not a loader: mint a new version before changing frozen data."""
    raw=json.loads(canonical(raw));raw.pop('manifest_sha256',None);raw['manifest_sha256']=digest(canonical(raw));return raw
