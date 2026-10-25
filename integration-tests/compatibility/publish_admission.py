#!/usr/bin/env python3
"""Bound active publish handlers using owned partial HTTP requests on Linux."""
from contextlib import contextmanager
from pathlib import Path
import argparse,copy,hashlib,http.client,json,os,secrets,socket,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses,publish_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('server','package-dir','evidence-dir'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows Cangjie execution is paused')
    report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    meta=json.loads((args.package_dir/'meta-data.json').read_text())
    artifact=(args.package_dir/(meta['name']+'-'+meta['version']+'.cjp')).read_bytes()
    assert meta['name']=='meshdep' and hashlib.sha256(artifact).hexdigest()==meta['index']['sha256sum']
    token=secrets.token_hex(32);variable='CJREPO_MAX_CONCURRENT_PUBLISHES';cases=[];cleanup=[];started=time.monotonic()
    base={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    def frame(name='meshdep',version='1.0.0',org='',data=artifact,wrong=False):
        value=copy.deepcopy(meta);value.update(name=name,version=version,organization=org)
        value['index'].update(name=name,version=version,organization=org,
            sha256sum='0'*64 if wrong else hashlib.sha256(data).hexdigest())
        return publish_frame(json.dumps(value).encode(),data)
    def request(port,data,*,path='/pkg/meshdep',authorized=True):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            c.request('POST',path,body=data,headers={'Authorization':token} if authorized else {})
            r=c.getresponse();return r.status,r.read(),dict((k.lower(),v) for k,v in r.getheaders())
        finally:c.close()
    def files(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    @contextmanager
    def owned(label,limit=None,extra=None):
        folder=report/label;folder.mkdir();storage=folder/'storage'
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env=dict(base,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),
            CJREPO_STORAGE=str(storage),CJREPO_READ_TOKEN=token,CJREPO_PUBLISH_TOKEN=token)
        if limit is not None:env[variable]=str(limit)
        env.update(extra or {})
        processes=ManagedProcesses();process=None
        try:
            process=processes.start([args.server.resolve()],cwd=folder,env=env,output_path=folder/'server.log')
            ready=False
            for _ in range(100):
                if process.poll() is not None:break
                c=http.client.HTTPConnection('127.0.0.1',port,timeout=.1)
                try:c.request('GET','/health');r=c.getresponse();ready=r.status==200;r.read()
                except OSError:pass
                finally:c.close()
                if ready:break
                time.sleep(.02)
            yield port,storage,process,ready
        finally:
            try:
                processes.close()
                assert process is None or process.poll() is not None
            except Exception:cleanup.append(label+': owned process cleanup failed');raise
    @contextmanager
    def partial(port,body):
        sock=socket.create_connection(('127.0.0.1',port),timeout=5)
        sock.sendall(('POST /pkg/meshdep HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: '+token+
            '\r\nContent-Length: '+str(len(body))+'\r\nConnection: close\r\n\r\n').encode()+body[:1])
        # Let this partial request enter before a complete malformed probe can
        # legitimately acquire the same last slot and reject the intended holder.
        time.sleep(.05)
        try:yield sock
        finally:sock.close()
    def busy(port):
        end=time.monotonic()+3
        while time.monotonic()<end:
            status,_,headers=request(port,b'\0')
            if status==429:
                assert headers.get('retry-after')=='1' and headers.get('connection','').lower()=='close'
                return
            assert status==400,'unexpected safe admission probe response'
            time.sleep(.01)
        raise AssertionError('partial authorized request did not occupy admission capacity')
    def available(port):
        end=time.monotonic()+3
        while time.monotonic()<end:
            status=request(port,b'\0')[0]
            if status==400:return
            assert status==429
            time.sleep(.01)
        raise AssertionError('closed upload did not release admission capacity')
    def finish(sock,body):
        sock.sendall(body[1:]);r=http.client.HTTPResponse(sock);r.begin()
        try:assert r.status==200;r.read()
        finally:r.close()
    def case(name,fn):
        error=''
        try:fn()
        except Exception as e:error=type(e).__name__+': '+str(e)
        cases.append(dict(name=name,passed=not error,error=error));print(('FAIL ' if error else 'PASS ')+name,flush=True)
    for name,raw in (('empty',''),('zero','0'),('negative','-1'),('text','synthetic-private-admission'),('large','65')):
        def invalid(name=name,raw=raw):
            with owned('invalid-'+name,raw) as (_,_,p,ready):assert not ready and p.poll()==2,'invalid admission limit must exit2'
            text=(report/('invalid-'+name)/'server.log').read_text()
            assert variable in text and (not raw.startswith('synthetic-') or raw not in text)
        case('invalid-'+name,invalid)
    def max_limit():
        with owned('maximum',64) as (_,_,_,ready):assert ready
    case('maximum-accepted',max_limit)
    def held_one():
        with owned('held-one',1) as (port,storage,_,ready):
            assert ready;body=frame()
            with partial(port,body) as sock:
                busy(port);before=files(storage)
                assert request(port,frame('othrdep'),path='/pkg/othrdep')[0]==429
                assert request(port,frame(org='company'),path='/pkg/meshdep?organization=company')[0]==429
                assert request(port,frame(),authorized=False)[0]==401
                assert files(storage)==before
                finish(sock,body)
            assert request(port,frame(version='2.0.0'))[0]==200
    case('one-slot-cross-package-org-auth-and-success-release',held_one)
    def aborted():
        with owned('aborted',1) as (port,storage,_,ready):
            assert ready
            with partial(port,frame()):busy(port)
            available(port);assert not files(storage)
            assert request(port,frame())[0]==200
    case('disconnect-releases-slot-without-publication',aborted)
    def defaults():
        with owned('default') as (port,_,_,ready):
            assert ready;holders=[]
            try:
                for version in range(1,9):
                    body=frame(version=str(version)+'.0.0')
                    manager=partial(port,body);holders.append((manager,manager.__enter__(),body))
                busy(port);finish(holders[0][1],holders[0][2])
                assert request(port,frame('othrdep'),path='/pkg/othrdep')[0]==200
                # Every intended holder must have entered, not just the first.
                for _,sock,body in holders[1:]:finish(sock,body)
            finally:
                for manager,_,_ in reversed(holders):manager.__exit__(None,None,None)
    case('default-eight-active-and-success-releases-only-owned-slot',defaults)
    def errors():
        with owned('errors',1,{'CJREPO_MAX_ARTIFACT_BYTES':str(len(artifact))}) as (port,_,_,ready):
            assert ready and request(port,frame())[0]==200
            for data,status in ((frame(),409),(frame(wrong=True),400),(frame(data=artifact+b'x'),413),(b'\0',400)):
                assert request(port,data)[0]==status
                assert request(port,b'\0')[0]==400,'error leaked a slot'
            assert request(port,frame('othrdep'),path='/pkg/othrdep')[0]==200
    case('duplicate-integrity-payload-and-malformed-errors-release',errors)
    def index_error():
        with owned('index-error',1,{'CJREPO_MAX_HOSTED_INDEX_BYTES':'1'}) as (port,storage,_,ready):
            assert ready and request(port,frame())[0]==413
            assert request(port,b'\0')[0]==400 and not files(storage)
    case('hosted-index413-releases-slot',index_error)
    def io_error():
        with owned('io-error',1) as (port,storage,_,ready):
            assert ready and request(port,frame())[0]==200
            blocker=storage/'artifacts/default/meshdep/2.0.0';blocker.write_bytes(b'owned-write-blocker')
            assert request(port,frame(version='2.0.0'))[0]==400
            assert request(port,b'\0')[0]==400
            blocker.unlink();assert request(port,frame(version='2.0.0'))[0]==200
    case('filesystem-failure-releases-slot-and-retry-succeeds',io_error)
    result=dict(success=all(c['passed'] for c in cases) and not cleanup,passed=sum(c['passed'] for c in cases),total=len(cases),cases=cases,
        cleanupErrors=cleanup,seconds=round(time.monotonic()-started,2),serverSha256=hashlib.sha256(args.server.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (report/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('success','passed','total','cleanupErrors')}),flush=True)
    return int(not result['success'])


if __name__=='__main__':raise SystemExit(main())
