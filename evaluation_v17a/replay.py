"""Disposable offline replay; preserves V6 evidence and original checkout bytes."""
from pathlib import Path
import argparse,subprocess,sys,tempfile,shutil,os,json,hashlib,resource
BASELINE='8decbf0e15b5fd73bf462f35be4f3bff61c3755a'
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('group',choices=['harness','schema','metamorphic','mutation','statistics','characterization','relevant','full']);p.add_argument('--repository',type=Path);p.add_argument('--baseline-directory',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--protect-repository',type=Path);a=p.parse_args()
if bool(a.repository)==bool(a.baseline_directory):p.error('choose repository OR baseline-directory')
output=a.output.resolve()
with tempfile.TemporaryDirectory(prefix='v17a-audit-') as temp:
    tmp=Path(temp);tree=tmp/'tree';(tmp/'tmp').mkdir()
    if a.repository:
        assert subprocess.check_output(['git','-C',str(a.repository),'rev-parse',BASELINE]).decode().strip()==BASELINE
        tree.mkdir();archive=subprocess.check_output(['git','-C',str(a.repository),'archive',BASELINE]);subprocess.run(['tar','-x','-C',str(tree)],input=archive,check=True)
    else:shutil.copytree(a.baseline_directory,tree)
    shutil.copytree(root,tree/'evaluation_v17a',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    for q in (tree/'policy_v6/case_evidence').glob('*.json'):q.unlink()
    q=tree/'policy_v6/validator_results.json'
    if q.exists():q.unlink()
    before={str(q.relative_to(tree)):hashlib.sha256(q.read_bytes()).hexdigest() for q in tree.rglob('*') if q.is_file()}
    base=['tests','audit_v3/test_independent_guard.py','audit_v4/test_v4_adversarial.py','audit_v4/test_v4_review.py','policy_v5/test_policy_validation.py','policy_v6/test_v6_validator.py','policy_v7/test_v7_policy.py','policy_v7/followup/test_blocked_policy.py']
    flags=['--audit-output',str(tmp/'evidence/v3'),'--policy-audit-output',str(tmp/'evidence'),'-k','not test_live_end_to_end']
    groups={'harness':['evaluation_v17a/tests'],'schema':['evaluation_v17a/tests/test_harness.py'],
     'metamorphic':['evaluation_v17a/tests/test_transformations.py'],'mutation':['evaluation_v17a/tests/test_mutations.py'],'statistics':['evaluation_v17a/tests/test_statistics.py'],
     'characterization':['evaluation_v17a/characterization.py'],
     'relevant':['tests/test_tools.py','tests/test_orchestration.py','tests/test_recovery.py','tests/test_phase4.py','tests/test_ddg_parser.py','tests/test_html_extraction.py','tests/test_bounded_retrieval.py','tests/test_ssrf.py'],
     'full':base+['evaluation_v17a/tests']+flags}
    env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
    env.update(PYTHONPATH=str(root/'offline_guard'),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',AUDIT_RESULTS=str(tmp/'results.json'),TMPDIR=str(tmp/'tmp'),V14_MEASUREMENTS=str(tmp/'measurements'),AUDIT_WORK_ROOT=str(tmp),AUDIT_IMMUTABLE_ROOT=str(root),AUDIT_PROTECTED_REPO=str((a.protect_repository or a.repository).resolve()) if (a.protect_repository or a.repository) else '')
    def limits():
        resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3));resource.setrlimit(resource.RLIMIT_CPU,(90,90));resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024**2,16*1024**2))
    cmd=[sys.executable,str(root/'offline_child.py'),*groups[a.group],'-q','-ra','-p','no:cacheprovider']
    try:
        result=subprocess.run(cmd,cwd=tree,env=env,capture_output=True,text=True,timeout=150,preexec_fn=limits);code=result.returncode;log=result.stdout+result.stderr
    except subprocess.TimeoutExpired as e:code=124;log='TIMEOUT\n'+str(e)
    output.mkdir(parents=True,exist_ok=True);(output/'pytest.log').write_text(log)
    if (tmp/'results.json').exists():shutil.copyfile(tmp/'results.json',output/'results.json')
    for dirname in ['measurements','evidence','demonstration','characterization']:
        if (tmp/dirname).exists():shutil.copytree(tmp/dirname,output/dirname,dirs_exist_ok=True)
    for q in [tree/'policy_v6/validator_results.json',*sorted((tree/'policy_v6/case_evidence').glob('*.json'))]:
        if q.exists():
            dest=output/q.relative_to(tree);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(q,dest)
    for f,h in before.items():assert hashlib.sha256((tree/f).read_bytes()).hexdigest()==h,f
    (output/'replay.json').write_text(json.dumps({'command':cmd,'process_exit':code,'baseline':BASELINE,'snapshot_file_hashes':before,'original_snapshot_files_unchanged':True},indent=2))
    if (output/'results.json').exists():
        d=json.loads((output/'results.json').read_text());print(json.dumps({k:d[k] for k in ('exit_code','initial_collected','selected','outcomes','teardown_errors','collection_errors','internal_errors')}))
    print('process_exit:',code,'evidence:',output);sys.exit(code)
