"""V6 test-local mock transports and evidence; no real INET sockets."""
import json,socket
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent
RESULTS=[]
@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    original=socket.socket.connect
    def blocked(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):raise AssertionError('real network forbidden in V6 validator tests')
        return original(sock,address)
    monkeypatch.setattr(socket.socket,'connect',blocked)
@pytest.fixture
def evidence(request):
    data={'test':request.node.name}
    yield data
    (ROOT/'case_evidence').mkdir(exist_ok=True)
    (ROOT/'case_evidence'/(request.node.name+'.json')).write_text(json.dumps(data,indent=2,default=str))
def pytest_runtest_logreport(report):
    if report.when=='call':RESULTS.append({'test':report.nodeid,'outcome':report.outcome,'trace':str(report.longrepr) if report.failed or report.skipped else None})
def pytest_sessionfinish(session,exitstatus):
    (ROOT/'validator_results.json').write_text(json.dumps({'exit_status':exitstatus,'tests':RESULTS},indent=2))
