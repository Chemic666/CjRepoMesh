#!/usr/bin/env python3
"""Small-byte Hosted artifact budget and lease lifetime regressions on owned Linux services."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import argparse,hashlib,http.client,json,os,secrets,socket,struct,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses,publish_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('server','evidence-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows Cangjie execution is paused')
    report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    token=secrets.token_hex(32);variable='CJREPO_MAX_INFLIGHT_ARTIFACT_BYTES';cases=[];cleanup=[];started=time.perf_counter()
    base={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    def frame(size=32,name='budgetprobe',org='',wrong=False):
        data=bytes(range(size));digest='0'*64 if wrong else hashlib.sha256(data).hexdigest()
        row=dict(name=name,version='1.0.0',organization=org,sha256sum=digest,dependencies=[])
        return publish_frame(json.dumps(dict(name=name,version='1.0.0',organization=org,index=row)).encode(),data)
    def path(name='budgetprobe',org=''):return '/pkg/'+name+('?organization='+org if org else '')
    def request(port,body,*,name='budgetprobe',org='',authorized=True):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            connection.request('POST',path(name,org),body=body,headers={'Authorization':token} if authorized else {})
            response=connection.getresponse();return response.status,response.read(),{k.lower():v for k,v in response.getheaders()}
        finally:connection.close()
    def stored(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    def verify(port,size=32,name='budgetprobe',org=''):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            query='?organization='+org if org else ''
            connection.request('GET','/pkg/'+name+'/1.0.0'+query,headers={'Authorization':token})
            response=connection.getresponse();assert response.status==200 and response.read()==bytes(range(size))
        finally:connection.close()
    @contextmanager
    def owned(label,budget=64,extra=None):
        folder=report/label;folder.mkdir();storage=folder/'storage'
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env=dict(base,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),CJREPO_STORAGE=str(storage),CJREPO_PUBLISH_TOKEN=token,CJREPO_READ_TOKEN=token,CJREPO_MAX_ARTIFACT_BYTES='1024',CJREPO_MAX_CONCURRENT_PUBLISHES='8')
        env[variable]=str(budget);env.update(extra or {})
        processes=ManagedProcesses();process=None
        try:
            process=processes.start([args.server.resolve()],cwd=folder,env=env,output_path=folder/'server.log')
            ready=False
            for _ in range(100):
                if process.poll() is not None:break
                connection=http.client.HTTPConnection('127.0.0.1',port,timeout=.1)
                try:connection.request('GET','/health');response=connection.getresponse();ready=response.status==200;response.read()
                except OSError:pass
                finally:connection.close()
                if ready:break
                time.sleep(.02)
            yield port,storage,process,ready
        finally:
            try:
                processes.close();assert process is None or process.poll() is not None
                assert token not in (folder/'server.log').read_text(errors='replace')
            except Exception:cleanup.append(label+': owned cleanup or privacy check failed');raise
    @contextmanager
    def partial(port,body,*,name='budgetprobe',org=''):
        cut=5+int.from_bytes(body[1:5],'little')+5+1
        sock=socket.create_connection(('127.0.0.1',port),timeout=5)
        try:
            header=(f'POST {path(name,org)} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: {token}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()
            sock.sendall(header+body[:cut]);time.sleep(.05)
            yield sock,body[cut:]
        finally:sock.close()
    def finish(held):
        sock,tail=held;sock.sendall(tail);response=http.client.HTTPResponse(sock);response.begin()
        try:assert response.status==200;response.read()
        finally:response.close()
    def rejected(port,size=33,name='otherprobe',org='company'):
        status,_,headers=request(port,frame(size,name,org),name=name,org=org)
        assert status==429,f'expected occupied byte budget429, got {status}'
        assert headers.get('retry-after')=='1' and headers.get('connection','').lower()=='close'
    def case(name,action):
        error=''
        try:action()
        except Exception as failure:error=type(failure).__name__+': '+str(failure)
        cases.append(dict(name=name,passed=not error,error=error));print(('FAIL ' if error else 'PASS ')+name,flush=True)
    for label,value in [('empty',''),('zero','0'),('negative','-1'),('text','synthetic-private-buffer'),('large','1073741825'),('overflow','9223372036854775808')]:
        def invalid(label=label,value=value):
            with owned('invalid-'+label,value) as (_,_,process,ready):assert not ready and process.poll()==2,'invalid buffer budget must exit2'
            text=(report/('invalid-'+label)/'server.log').read_text();assert variable in text
            assert not value.startswith('synthetic-') or value not in text
        case('invalid-'+label,invalid)
    def largest():
        with owned('largest',1073741824) as (_,_,_,ready):assert ready
    case('largest-configuration-without-allocation',largest)
    def exact():
        with owned('exact') as (port,_,_,ready):
            assert ready and request(port,frame(64))[0]==200;verify(port,64)
            assert request(port,frame(64))[0]==409
            assert request(port,frame(64,'otherprobe'),name='otherprobe')[0]==200;verify(port,64,'otherprobe')
    case('exact-budget-and-success-duplicate-release',exact)
    def over():
        with owned('over') as (port,storage,_,ready):
            assert ready and request(port,frame(65))[0]==413 and not stored(storage)
            assert request(port,frame(64))[0]==200;verify(port,64)
    case('single-over-budget413-before-storage',over)
    def cross():
        with owned('cross') as (port,storage,_,ready):
            assert ready
            with partial(port,frame()) as held:
                rejected(port);rejected(port)
                assert not stored(storage)
                assert request(port,frame(33),authorized=False)[0]==401
                assert request(port,b'\0')[0]==400
                assert request(port,frame(32,'otherprobe'),name='otherprobe')[0]==200
                rejected(port);finish(held)
            assert request(port,frame(64,'freedprobe'),name='freedprobe')[0]==200;verify(port,64,'freedprobe')
    case('cross-org-budget-refusal-never-releases-other-lease',cross)
    def two():
        with owned('two') as (port,storage,_,ready), ExitStack() as stack:
            assert ready
            first=stack.enter_context(partial(port,frame()))
            second=stack.enter_context(partial(port,frame(org='company'),org='company'))
            rejected(port,1);assert not stored(storage);finish(first)
            rejected(port,33)
            assert request(port,frame(32,'otherprobe'),name='otherprobe')[0]==200
            finish(second);verify(port,org='company')
    case('two-leases-exact-total-and-independent-release',two)
    def aborted():
        with owned('aborted') as (port,storage,_,ready):
            assert ready
            with partial(port,frame()) as held:rejected(port)
            assert not stored(storage)
            for _ in range(100):
                status=request(port,frame(64))[0]
                if status==200:break
                assert status==429;time.sleep(.01)
            else:raise AssertionError('disconnect did not release byte budget')
            verify(port,64)
    case('disconnect-releases-reserved-bytes',aborted)
    for label,data in [('hash',frame(wrong=True)),('truncated',frame(64)[:-1]),('trailing',frame()+b'x')]:
        def failed_frame(label=label,data=data):
            with owned('error-'+label) as (port,storage,_,ready):
                assert ready and request(port,data)[0]==400 and not stored(storage)
                assert request(port,frame(64))[0]==200;verify(port,64)
        case(label+'-failure-releases-bytes',failed_frame)
    def index():
        with owned('index',extra={'CJREPO_MAX_HOSTED_INDEX_BYTES':'1'}) as (port,storage,_,ready):
            assert ready and request(port,frame(64))[0]==413
            assert request(port,frame(64,'otherprobe'),name='otherprobe')[0]==413 and not stored(storage)
    case('index413-releases-bytes',index)
    def io():
        with owned('io') as (port,storage,_,ready):
            assert ready;block=storage/'artifacts/default/budgetprobe/1.0.0';block.parent.mkdir(parents=True);block.write_bytes(b'owned-blocker')
            assert request(port,frame(64))[0]==400
            assert request(port,frame(64,'otherprobe'),name='otherprobe')[0]==200;verify(port,64,'otherprobe')
    case('storage-failure-releases-bytes',io)
    def slots():
        with owned('slots',extra={'CJREPO_MAX_CONCURRENT_PUBLISHES':'1'}) as (port,_,_,ready):
            assert ready
            with partial(port,frame()) as held:rejected(port,1);finish(held)
            assert request(port,frame(64,'otherprobe'),name='otherprobe')[0]==200
    case('handler-slot-limit-remains-independent',slots)
    result=dict(success=all(c['passed'] for c in cases) and not cleanup,passed=sum(c['passed'] for c in cases),total=len(cases),cases=cases,cleanupErrors=cleanup,serverSha256=hashlib.sha256(args.server.read_bytes()).hexdigest(),seconds=round(time.perf_counter()-started,2))
    (report/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return int(not result['success'])


if __name__=='__main__':raise SystemExit(main())
