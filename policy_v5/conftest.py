"""Only isolated mock transports; block all real INET connects in tests."""
import json,socket
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent
RESULTS=[]
def pytest_addoption(parser):
    parser.addoption('--policy-audit-output',default=None)
def pytest_configure(config):
    global ROOT
    if config.getoption('--policy-audit-output'):
        ROOT=Path(config.getoption('--policy-audit-output'))/'v5'
        ROOT.mkdir(parents=True,exist_ok=True)
@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    original=socket.socket.connect
    def blocked(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):raise AssertionError('network forbidden in V5 policy tests')
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
    (ROOT/'test_results.json').write_text(json.dumps({'exit_status':exitstatus,'tests':RESULTS},indent=2))
