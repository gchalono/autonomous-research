import os,sys,json,socket
from pathlib import Path
sys.path.insert(0,os.getcwd())
assert not any(os.environ.get(k) for k in ('OPENAI_API_KEY','TAVILY_API_KEY'))
try:socket.create_connection(('example.invalid',443))
except RuntimeError as e:assert str(e)=='AUDIT_OFFLINE_NETWORK_DENIED'
else:raise AssertionError('offline guard absent')
# Prove original/snapshot source and canonical DB writes remain forbidden.
for name in [os.path.join(os.environ['AUDIT_IMMUTABLE_ROOT'],'current/src/tools/safe_http.py'),str(Path.cwd()/'src/tools/safe_http.py'),str(Path.cwd()/'projects/bounded_spending.sqlite3')]:
    try:
        with open(name,'wb'):pass
    except RuntimeError as e:assert str(e)=='AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED'
    else:raise AssertionError('write guard absent')
import pytest
class Census:
    def __init__(self):self.reports=[];self.deselected=[];self.collection_errors=[];self.expected_v6=[];self.internal_errors=[]
    def pytest_collection_modifyitems(self,items):
        self.expected_v6=[i.name for i in items if i.nodeid.startswith('policy_v6/') and 'evidence' in i.fixturenames]
    def pytest_deselected(self,items):self.deselected.extend(i.nodeid for i in items)
    def pytest_collectreport(self,report):
        if report.failed:self.collection_errors.append(report.nodeid)
    def pytest_internalerror(self,excrepr,excinfo):self.internal_errors.append(str(excrepr))
    def pytest_runtest_logreport(self,report):
        outcome='xfailed' if report.skipped and hasattr(report,'wasxfail') else 'xpassed' if report.passed and hasattr(report,'wasxfail') else report.outcome
        self.reports.append({'nodeid':report.nodeid,'phase':report.when,'outcome':outcome,'error':str(report.longrepr) if report.failed else None})
    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self,session,exitstatus):
        per={}
        for x in self.reports:
            if x['phase']=='call' or x['outcome'] not in ('passed',):per[x['nodeid']]=x['outcome']
        outcomes={k:list(per.values()).count(k) for k in ('passed','failed','skipped','xfailed','xpassed')}
        Path(os.environ['AUDIT_RESULTS']).write_text(json.dumps({'exit_code':int(exitstatus),'initial_collected':session.testscollected+len(self.deselected),'selected':session.testscollected,'outcomes':outcomes,'deselected':self.deselected,'collection_errors':self.collection_errors,'internal_errors':self.internal_errors,'expected_v6_evidence':self.expected_v6,'teardown_reports':sum(x['phase']=='teardown' for x in self.reports),'teardown_errors':[x for x in self.reports if x['phase']=='teardown' and x['outcome']!='passed'],'reports':self.reports},indent=2))
if __name__=='__main__':raise SystemExit(pytest.main(sys.argv[1:],plugins=[Census()]))
