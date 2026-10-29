"""Developer synthetic mechanics data and HAND-SPECIFIED oracle, never scorer output.
Run only to mint/review a new synthetic corpus version, not to rewrite a study.
"""
import copy,json
from pathlib import Path
from evaluation_v17a.schema import seal,digest,canonical
from evaluation_v17a.adapter import render_payload
ROOT=Path(__file__).resolve().parent

def judgment(id,**kw):return dict(id=id,origin='synthetic_developer',annotator='developer_fixture_author',status='final',notes='Synthetic stipulated label, not independent human adjudication.',**kw)
def certify(r,claims):
    r['all_claim_ids']=[c['id'] for c in claims];r['submitted_claim_ids']=r['all_claim_ids'][:]
    if not claims:r['segments']=[dict(start=0,end=len(r['text']),kind='nonfactual',claim_ids=[])] if r['text'] else [];return
    spans=[]
    for c in claims:
        spans.append((c['start'],c['end'],c['id']))
        spans.extend((p['start'],p['end'],c['id']) for p in c.get('additional_locations',[]))
    boundaries=sorted({0,len(r['text'])}|{v for a,b,_ in spans for v in (a,b)})
    r['segments']=[]
    for a,b in zip(boundaries,boundaries[1:]):
        ids=sorted({cid for lo,hi,cid in spans if max(a,lo)<min(b,hi)})
        r['segments'].append(dict(start=a,end=b,kind='factual' if ids else 'nonfactual',claim_ids=ids))

def refresh(d):
    r=d['reports'][0];r['text']=render_payload(r['engine_payload'])
    for c in d['claims']:
        c['start']=r['text'].index(c['text']);c['end']=c['start']+len(c['text'])
    certify(r,d['claims'])
def uncite(d):
    d['citations']=[];d['relations']=[]
    for c in d['reports'][0]['engine_payload']['claims']:c['source_ids']=[]
    refresh(d)
def bind_citation(d):
    p=next(x for x in d['passages'] if x['id']==d['citations'][0]['passage_id'])
    source=next(x for x in d['sources'] if x['id']==p['source_id'])
    d['reports'][0]['engine_payload']['sources'][0].update(url=source['description'],passage=p['text'])
    refresh(d)
def replace_source(d,index,text):
    d['sources'][index].update(content=text,sha256=digest(text))
    d['passages'][index].update(start=0,end=len(text),text=text)
def base():
    text='The synthetic trial enrolled 10 participants.'
    source=text+' Duration was 2 days.';other='The synthetic archive opened on Monday.'
    payload=dict(executive_summary='Synthetic demonstration.',findings=[],claims=[dict(id='engine:C1',text=text,classification='VERIFIED',source_ids=['engine:S1'])],sources=[dict(id='engine:S1',url='https://example.invalid/source:1',title='Synthetic source',retrieved_at='',passage=text,verification_status='UNCHECKED')],limitations=[],unresolved_dependencies=[])
    report=dict(id='report:1',task_id='task:1',text=render_payload(payload),engine_payload=payload,candidate_version='synthetic-engine-format-v1',all_claim_ids=['claim:1'],submitted_claim_ids=['claim:1'],excluded_engine_claims={},inventory_complete=True,inventory_reviewer='synthetic_inventory_author',inventory_method='Complete by synthetic construction, not human-certified research.',segments=[])
    start=report['text'].index(text);claim=dict(id='claim:1',report_id='report:1',text=text,start=start,end=start+len(text),additional_locations=[],engine_claim_id='engine:C1',proposition_key='enrollment',atomic_propositions=1,materiality='material');certify(report,[claim])
    def src(id,content):return dict(id=id,description='https://example.invalid/'+id,source_type='synthetic',captured_at=None,content=content,sha256=digest(content),encoding='utf-8',origin='synthetic_developer',provenance={'synthetic':'true','author':'developer'},limitations=['Not real-world evidence.'])
    return dict(schema_version='v17a.1',dataset_version='synthetic-v3',tasks=[dict(id='task:1',objective='Report synthetic enrollment.',domain='synthetic',subquestions=[dict(id='question:1',text='How many enrolled?')],evidence_types=['synthetic trial'],temporal_assumptions='Fixed synthetic time.',source_ids=['source:1','source:2'],rubric='Exact enrolled count with supporting evidence.',limitations=['Synthetic only.'])],sources=[src('source:1',source),src('source:2',other)],passages=[dict(id='passage:1',source_id='source:1',start=0,end=len(text),text=text),dict(id='passage:2',source_id='source:2',start=0,end=len(other),text=other)],references=[dict(id='reference:1',task_id='task:1',answer=text,origin='synthetic_developer',annotators=['developer_fixture_author'],blinded_to_engine=True,blinded_to_auditor=True,disagreements=[],adjudication_notes='Synthetic truth stipulated before scoring; not human-independent.',label_version='synthetic-v3',status='final',expected_action='answer')],reports=[report],claims=[claim],citations=[dict(id='citation:1',engine_source_id='engine:S1',claim_id='claim:1',passage_id='passage:1')],annotations=[judgment('annotation:1',claim_id='claim:1',truth='correct',support='fully_supported')],relations=[judgment('relation:1',citation_id='citation:1',support='fully_supported',attribution='correct_source_and_passage')],questions=[judgment('question_judgment:1',report_id='report:1',subquestion_id='question:1',coverage='full')],contradictions=[],contradiction_judgments=[],numerics=[],numerical_judgments=[],abstentions=[dict(id='abstention:1',report_id='report:1',action='answer',rationale='Synthetic demonstration.')],auditors=[dict(id='auditor:1',report_id='report:1',decision='approve',accepted_claim_ids=['claim:1'],issues=[])],report_judgments=[judgment('gold:1',report_id='report:1',defect='clean')],traces=[dict(id='trace:1',report_id='report:1',**{k:None for k in ['model_calls','input_tokens','output_tokens','reasoning_tokens','tool_calls','actual_cost_usd','estimated_cost_usd','latency_seconds','retries','failures','human_interventions','context_truncations','missing_evidence','terminal_status']})])
def defective(d):d['report_judgments'][0]['defect']='defective'
def unknown(d):d['report_judgments'][0].update(defect='unresolved',status='unresolved')
def no_claims(d,text=''):
    r=d['reports'][0];r['engine_payload']['executive_summary']=text;r['engine_payload']['claims']=[];r['engine_payload']['sources']=[];r['text']=render_payload(r['engine_payload']);d['claims']=[];certify(r,[]);d['annotations']=[];d['citations']=[];d['relations']=[];d['auditors'][0]['accepted_claim_ids']=[]
def unsupported(d,support='unsupported',attribution='correct_source_wrong_passage'):
    defective(d);d['annotations'][0]['support']=support;d['relations'][0].update(support=support,attribution=attribution)
def numeric(d,value='21'):
    d['numerics']=[dict(id='number:1',task_id='task:1',expression='10*2',value='20',undefined=False,unit='person-days',mode='exact',tolerance='0',rounding_places=None)]
    d['numerical_judgments']=[judgment('number_judgment:1',report_id='report:1',numerical_reference_id='number:1',value=value,unit='person-days')]
def contradiction(d):
    text='The synthetic trial enrolled 11 participants.'
    d['sources'][1].update(content=text,sha256=digest(text));d['passages'][1].update(start=0,end=len(text),text=text)
    d['contradictions']=[dict(id='contradiction:1',task_id='task:1',passage_ids=['passage:1','passage:2'],materiality='material',description='Two synthetic records disagree: enrollment 10 versus 11.')]
def change_claim(d,text):
    r=d['reports'][0];r['engine_payload']['claims'][0]['text']=text;r['text']=render_payload(r['engine_payload']);c=d['claims'][0];c.update(text=text,start=r['text'].index(text),end=r['text'].index(text)+len(text));certify(r,[c])

# Explicit fractions are hand-calculated; these are not calls into the scorer.
ORACLES={
'E01':('valid',{'factual_correctness':[1,1],'claim_support':[1,1],'citation_precision':[1,1]},'One true atomic claim and one correctly anchored supporting relation.'),
'E02':('valid',{'factual_correctness':[1,1],'claim_support':[0,1],'citation_precision':[0,1]},'Truth stays correct but unrelated evidence gives zero support.'),
'E03':('valid',{'factual_correctness':[0,1],'claim_support':[0,1]},'False count cites a real passage; passage existence is not truth.'),
'E04':('invalid_input',{},'Fabricated continuation differs from full frozen source slice, despite genuine prefix.'),
'E05':('valid',{'claim_support':[0,1],'citation_precision':[0,1]},'Wrong-source attribution is not supporting evidence.'),
'E06':('valid',{'claim_support':[0,1]},'A genuine different passage from the same source does not support enrollment.'),
'E07':('valid',{'factual_correctness':[0,1],'claim_support':[0,1]},'Cited source contradicts the false count.'),
'E08':('valid',{'claim_support':[0,1],'citation_precision':[0,1]},'Partial support receives no full credit.'),
'E09':('valid',{'claim_support':[0,1],'citation_presence':[0,1]},'Missing citation remains an inventoried unsupported claim.'),
'E10':('valid',{'citation_precision':[0,0],'citation_coverage':[0,1]},'Zero relations gives undefined precision, zero adequate citation coverage.'),
'E11':('insufficient_adjudication',{'factual_correctness':[0,0],'claim_support':[0,0]},'An empty report is not a perfect report; reference gold unresolved.'),
'E12':('insufficient_adjudication',{'claim_support':[0,1],'adjudication_coverage':[0,1],'annotation_coverage':[0,1]},'Omitted annotation stays in inventory denominators.'),
'E13':('valid',{'unnecessary_abstention':[1,1],'substantive_success':[0,1]},'Answerable reference plus abstention is unnecessary abstention.'),
'E14':('valid',{'correct_abstention':[1,1],'substantive_success':[0,0]},'Unanswerable reference plus abstention is correct, not substantive success.'),
'E15':('valid',{'numerical_correctness':[0,1]},'10*2 is 20 person-days, not 21.'),
'E16':('valid',{'research_completeness':[0,1]},'Omitted required question remains in denominator.'),
'E17':('valid',{'contradiction_identified':[0,1],'contradiction_reflected':[0,1]},'Known material conflict is not mentioned or reflected.'),
'E18':('valid',{'report_false_approval':[1,1],'claim_false_acceptance':[1,1]},'Auditor approves and explicitly accepts a material unsupported claim.'),
'E19':('valid',{'auditor_false_rejection':[1,1]},'Auditor rejects independently clean synthetic report.'),
'E20':('insufficient_adjudication',{'claim_support':[0,1]},'Lost evidence does not earn support; trace records one truncation and evidence gap.'),
'E21':('valid',{'citation_precision':[1,1]},'Duplicate supporting relation counts once, not twice.'),
'E22':('invalid_input',{},'Duplicate proposition cannot inflate claim denominators.'),
'E23':('invalid_input',{},'Compound proposition must be split, not labeled vaguely partly supported.'),
'E24':('valid',{'report_false_approval':[1,1]},'Unresolved critical issue prevents a clean gold report; approval is false.'),
'E25':('invalid_input',{},'Frozen source digest does not match bytes.'),
'E26':('invalid_input',{},'Passage offsets outside the source are invalid.'),
'E27':('invalid_input',{},'Missing annotation cannot assert correct/fully-supported labels.'),
'E28':('insufficient_adjudication',{'adjudication_coverage':[0,1],'claim_support':[0,1]},'Unresolved labels stay unresolved, not final support.'),
'E29':('invalid_input',{},'Empty dataset cannot return plausible quality metrics.'),
'E30':('invalid_input',{},'NaN numerical reference is invalid, not an undefined calculation.')}

def cases():
    out={}
    for i in range(1,31):
        key=f'E{i:02}';d=base()
        if i==2:unsupported(d,attribution='wrong_source');d['citations'][0]['passage_id']='passage:2';bind_citation(d)
        elif i in (3,7):change_claim(d,'The synthetic trial enrolled 11 participants.');unsupported(d,'contradicted','correct_source_and_passage');d['annotations'][0]['truth']='incorrect'
        elif i==4:d['passages'][0]['text']+=' Fabricated continuation.'
        elif i==5:unsupported(d,attribution='wrong_source');d['citations'][0]['passage_id']='passage:2';bind_citation(d)
        elif i==6:
            p=d['passages'][0];p.update(start=p['end']+1,end=len(d['sources'][0]['content']),text='Duration was 2 days.');unsupported(d);bind_citation(d)
        elif i==8:
            replace_source(d,0,'An interim estimate suggests 10 participants; final enrollment is not reported in this excerpt.')
            replace_source(d,1,'The final synthetic trial enrolled 10 participants.')
            bind_citation(d);unsupported(d,'partially_supported','correct_source_and_passage')
            d['references'][0]['adjudication_notes']='Synthetic final record 2 establishes count 10 independently; cited interim estimate 1 is only partial support.'
        elif i in (9,10):defective(d);uncite(d);d['annotations'][0]['support']='missing_citation'
        elif i==11:no_claims(d);unknown(d);d['questions'][0]['coverage']='missing'
        elif i==12:d['annotations']=[];unknown(d)
        elif i in (13,14):
            no_claims(d,'Insufficient synthetic evidence.');d['abstentions'][0]['action']='abstain'
            if i==13:defective(d);d['questions'][0]['coverage']='missing'
            else:
                d['references'][0].update(expected_action='abstain',answer='Unpublished one-year survival cannot be determined from the frozen sources.')
                d['tasks'][0]['objective']='Determine unpublished one-year survival.';d['tasks'][0]['subquestions'][0]['text']='What is one-year survival, not reported by either frozen source?'
                d['tasks'][0]['rubric']='Abstain explicitly when the requested endpoint is absent.'
        elif i==15:
            numeric(d);defective(d)
            text='The synthetic total is 21 person-days.'
            d['reports'][0]['engine_payload']['claims'].append(dict(id='engine:C2',text=text,classification='ESTIMATED',source_ids=[]))
            d['claims'].append(dict(id='claim:2',report_id='report:1',text=text,start=0,end=1,additional_locations=[],engine_claim_id='engine:C2',proposition_key='total-person-days',atomic_propositions=1,materiality='material'))
            d['annotations'].append(judgment('annotation:2',claim_id='claim:2',truth='incorrect',support='missing_citation'))
            d['references'][0]['answer']+=' Duration 2 days implies 20 person-days.'
            d['tasks'][0]['objective']+=' Compute person-days from the two-day duration.'
            refresh(d)
        elif i==16:d['questions'][0]['coverage']='missing';defective(d)
        elif i==17:
            contradiction(d);defective(d);d['references'][0]['adjudication_notes']='Synthetic primary trial record 1 stipulates true enrollment 10; conflicting secondary archive 2 says 11 and must be disclosed.';d['contradiction_judgments']=[judgment('conflict_judgment:1',report_id='report:1',contradiction_id='contradiction:1',identified=False,accurate=False,addressed=False,reflected=False)]
        elif i==18:
            change_claim(d,'The synthetic treatment cured all patients.')
            replace_source(d,1,'Not all synthetic patients were cured.')
            unsupported(d);d['annotations'][0]['truth']='incorrect'
            d['tasks'][0]['objective']='Assess whether all synthetic patients were cured.'
            d['tasks'][0]['subquestions'][0]['text']='Were all synthetic patients cured?'
            d['references'][0]['answer']='Not all patients were cured, according to frozen source 2; enrollment source 1 supplies no efficacy evidence.'
        elif i==19:d['auditors'][0]['decision']='blocked'
        elif i==20:
            replace_source(d,0,'The synthetic trial [the remainder of the enrollment evidence was lost from context].')
            replace_source(d,1,'The final synthetic trial enrolled 10 participants.')
            bind_citation(d);unsupported(d,'unverifiable','correct_source_and_passage');d['traces'][0].update(context_truncations=1,missing_evidence=1)
            d['references'][0]['adjudication_notes']='Independent synthetic final source 2 establishes the truth; cited truncated source 1 does not supply the count.'
        elif i==21:
            d['citations'].append(dict(d['citations'][0],id='citation:2'));d['relations'].append(dict(d['relations'][0],id='relation:2',citation_id='citation:2'))
        elif i==22:
            d['claims'].append(dict(d['claims'][0],id='claim:2'));d['reports'][0]['all_claim_ids'].append('claim:2')
        elif i==23:change_claim(d,'The synthetic trial enrolled 10 participants and lasted 2 days.');d['claims'][0]['atomic_propositions']=2;unsupported(d,'partially_supported','correct_source_and_passage')
        elif i==24:
            d['auditors'][0]['issues']=[dict(id='issue:1',severity='critical',status='unresolved',description='Unresolved synthetic material defect.')];defective(d)
        elif i==25:d['sources'][0]['sha256']='0'*64
        elif i==26:d['passages'][0]['end']=1000000
        elif i==27:d['annotations'][0]['status']='missing'
        elif i==28:d['annotations'][0]['status']='unresolved';unknown(d)
        elif i==29:d['tasks']=[];d['reports']=[]
        elif i==30:numeric(d);d['numerics'][0]['value']='NaN'
        d['dataset_version']='synthetic-v3-'+key;out[key]=seal(d)
    return out
if __name__=='__main__':
    for key,d in cases().items():(ROOT/(key+'.json')).write_text(canonical(d)+'\n')
    (ROOT/'ORACLES.json').write_text(json.dumps({k:dict(state=v[0],metrics=v[1],reason=v[2]) for k,v in ORACLES.items()},indent=2)+'\n')
