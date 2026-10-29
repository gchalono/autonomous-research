"""Task-level resampling; no claims-as-independent-observations inference."""
import math,random
from statistics import mean

def _values(data):
    if not isinstance(data,dict):raise ValueError('task-ID mapping required')
    for k,v in data.items():
        if not isinstance(k,str) or not k or (v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1)):raise ValueError('invalid task value')
def _interval(values,seed,replicates,confidence):
    if type(seed)!=int or type(replicates)!=int or not 100<=replicates<=100000 or type(confidence) not in (int,float) or not 0<confidence<1:raise ValueError('invalid bootstrap configuration')
    if len(values)<2:return None
    rng=random.Random(seed);samples=sorted(mean(rng.choices(values,k=len(values))) for _ in range(replicates))
    def quantile(p):
        i=(len(samples)-1)*p;lo=int(i);hi=min(lo+1,len(samples)-1);return samples[lo]+(samples[hi]-samples[lo])*(i-lo)
    a=(1-confidence)/2;return [quantile(a),quantile(1-a)]
def bootstrap(tasks,seed=20261029,replicates=2000,confidence=.95):
    _values(tasks);values=[v for k,v in sorted(tasks.items()) if v is not None]
    interval=_interval(values,seed,replicates,confidence)
    return {'unit':'task','n':len(values),'missing':sorted(k for k,v in tasks.items() if v is None),'mean':mean(values) if values else None,'interval':interval,'seed':seed,'replicates':replicates,'confidence':confidence}
def paired(baseline,candidate,seed=20261029,replicates=2000,confidence=.95):
    _values(baseline);_values(candidate);allids=set(baseline)|set(candidate)
    ids=sorted(k for k in allids if baseline.get(k) is not None and candidate.get(k) is not None)
    diffs=[candidate[k]-baseline[k] for k in ids]
    return {'unit':'paired_task','paired_ids':ids,'excluded_ids':sorted(allids-set(ids)),'mean_difference':mean(diffs) if diffs else None,'interval':_interval(diffs,seed,replicates,confidence),'seed':seed}
def stratified(tasks,domains,**kw):
    _values(tasks)
    if set(tasks)!=set(domains) or any(not isinstance(d,str) or not d for d in domains.values()):raise ValueError('domain mapping mismatch')
    return {d:bootstrap({k:v for k,v in tasks.items() if domains[k]==d},**kw) for d in sorted(set(domains.values()))}
