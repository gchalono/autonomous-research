"""Read-only adapter: lossless path-tagged fields and explicit inventory template."""
from .schema import canonical

def render_with_locations(payload):
    parts=[];locations={};pos=0
    def leaf(path,value):
        nonlocal pos
        prefix=path+': ';text=value if isinstance(value,str) else canonical(value)
        parts.append(prefix+text+'\n');locations[path]=(pos+len(prefix),pos+len(prefix)+len(text));pos+=len(prefix)+len(text)+1
    def walk(value,path):
        if isinstance(value,dict) and value:
            for key in sorted(value):walk(value[key],path+'.'+key)
        elif isinstance(value,list) and value:
            for i,v in enumerate(value):walk(v,path+'['+str(i)+']')
        else:leaf(path,value)
    walk(payload,'$');return ''.join(parts),locations

def render_payload(payload):return render_with_locations(payload)[0]

def inventory_template(payload,report_id,task_id,candidate_version):
    from src.models.contracts import ExecutionReport
    normalized=ExecutionReport.model_validate(payload).model_dump(mode='json')
    return {'id':report_id,'task_id':task_id,'text':render_payload(normalized),
            'engine_payload':normalized,'candidate_version':candidate_version,
            'all_claim_ids':[],'submitted_claim_ids':[],'excluded_engine_claims':{},'inventory_complete':False,
            'inventory_reviewer':None,'inventory_method':'Await independent full-text inventory; engine claims are suggestions only.',
            'segments':[]}
