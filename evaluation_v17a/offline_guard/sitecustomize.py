"""External audit isolation; no repository/test-source changes."""
import os,sys,socket
from urllib.parse import urlsplit, unquote
for key in list(os.environ):
    if any(x in key.upper() for x in ('API_KEY','TOKEN','SECRET','PASSWORD','CREDENTIAL')):os.environ.pop(key,None)
def deny(*a,**k):raise RuntimeError('AUDIT_OFFLINE_NETWORK_DENIED')
socket.socket.connect=deny;socket.create_connection=deny;socket.getaddrinfo=deny;socket.gethostbyname=deny
root=os.environ['AUDIT_WORK_ROOT'];tree=root+'/tree';original=os.environ.get('AUDIT_PROTECTED_REPO','');immutable=os.environ['AUDIT_IMMUTABLE_ROOT']
def forbidden(path,dir_fd=None):
    if not isinstance(path,(str,bytes,os.PathLike)):return False
    path=os.fsdecode(path)
    if path.startswith('file:'):
        parsed=urlsplit(path)
        if parsed.netloc not in ('','localhost'):return True
        path=unquote(parsed.path)
    if not os.path.isabs(path) and isinstance(dir_fd,int) and dir_fd>=0:
        path=os.path.join(os.readlink('/proc/self/fd/'+str(dir_fd)),path)
    path=os.path.realpath(path)
    if path==immutable or path.startswith(immutable+'/'):return True
    if original and (path==original or path.startswith(original+'/')):return True
    if path==tree or path.startswith(tree+'/'):
        prefix=tree+'/policy_v6/case_evidence'
        return not (path==prefix or (os.path.dirname(path)==prefix and path.endswith('.json')) or path==tree+'/policy_v6/validator_results.json')
    return False

def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto'):deny()
    if event=='open' and args:
        mode=args[1];flags=args[2] or 0
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        if writing and forbidden(args[0]):raise RuntimeError('AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED')
    if event in ('os.mkdir','os.remove','os.rmdir','os.chmod','os.truncate') and args:
        pos=2 if event in ('os.mkdir','os.chmod') else 1
        fd=args[pos] if len(args)>pos else None
        if forbidden(args[0],fd):raise RuntimeError('AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED')
    if event in ('os.rename','os.link') and (forbidden(args[0],args[2] if len(args)>2 else None) or forbidden(args[1],args[3] if len(args)>3 else None)):
        raise RuntimeError('AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED')
    if event=='os.symlink' and forbidden(args[1],args[2] if len(args)>2 else None):
        raise RuntimeError('AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED')
    if event=='sqlite3.connect' and args and forbidden(args[0]):
        raise RuntimeError('AUDIT_SOURCE_OR_CANONICAL_WRITE_DENIED')
sys.addaudithook(audit)
