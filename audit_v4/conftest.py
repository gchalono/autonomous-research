"""Isolated V4 audit; no real INET connection may occur inside these tests."""
import json,socket
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent
RESULTS=[]
def pytest_configure(config):
    global ROOT
    output=config.getoption('--policy-audit-output',default=None)
    if output:
        ROOT=Path(output)/'v4'
        ROOT.mkdir(parents=True,exist_ok=True)
@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    original=socket.socket.connect
    def blocked(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            raise AssertionError('real network forbidden in V4 offline tests')
        return original(sock,address)
    monkeypatch.setattr(socket.socket,'connect',blocked)
@pytest.fixture
def evidence(request):
    data={'test_id':request.node.name}
    yield data
    (ROOT/'case_evidence').mkdir(exist_ok=True)
    (ROOT/'case_evidence'/(request.node.name+'.json')).write_text(json.dumps(data,indent=2,default=str))
def pytest_runtest_logreport(report):
    if report.when=='call':RESULTS.append({'test':report.nodeid,'status':report.outcome,'failure':str(report.longrepr) if report.failed else None})
def pytest_sessionfinish(session,exitstatus):
    (ROOT/'adversarial_results.json').write_text(json.dumps({'exit_status':exitstatus,'tests':RESULTS},indent=2))
