#!/usr/bin/env python3
"""Exercise HTTP framing above the stdx default on owned Linux server processes."""
from pathlib import Path
import argparse,hashlib,http.client,json,os,secrets,socket,sys,time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses,publish_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('server','evidence-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows Cangjie execution is paused')
    report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    server=args.server.resolve();token=secrets.token_hex(32);cases=[];started=time.monotonic()
    body=hashlib.shake_256(b'CjRepoMesh owned HTTP body boundary').digest(16*1048576)
    checksum=hashlib.sha256(body).hexdigest()
    index=dict(name='httpbody',version='1.0.0',organization='',sha256sum=checksum,dependencies=[])
    frame=publish_frame(json.dumps(dict(name='httpbody',version='1.0.0',organization='',index=index)).encode(),body)
    env={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    def scenario(label,limit,authorized,expected,chunked=False):
        folder=report/label;folder.mkdir()
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        owned=dict(env,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),
                   CJREPO_STORAGE=str(folder/'storage'),CJREPO_PUBLISH_TOKEN=token,CJREPO_READ_TOKEN=token)
        if limit is not None:owned['CJREPO_MAX_ARTIFACT_BYTES']=str(limit)
        def request(path,data=None,auth=token):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=30)
            try:
                if data is not None and expected==413:
                    # An early rejection must arrive from headers alone; do not race a large send against close.
                    conn.putrequest('POST',path)
                    conn.putheader('Authorization',auth)
                    conn.putheader('Content-Length',str(len(data)))
                    conn.endheaders()
                else:
                    conn.request('GET' if data is None else 'POST',path,body=(iter([data]) if chunked and data is not None else data),
                                 headers={'Authorization':auth},encode_chunked=chunked and data is not None)
                response=conn.getresponse();return response.status,response.read()
            finally:conn.close()
        with ManagedProcesses() as processes:
            process=processes.start([server],cwd=folder,env=owned,output_path=folder/'server.log')
            for _ in range(100):
                try:
                    if request('/health')[0]==200:break
                except OSError:pass
                if process.poll() is not None:raise AssertionError('server exited before readiness')
                time.sleep(.03)
            else:raise AssertionError('server did not become healthy')
            status,_=request('/pkg/httpbody',frame,token if authorized else 'synthetic-invalid')
            assert status==expected,f'publish returned {status}, expected {expected}'
            if status==200:
                assert request('/pkg/httpbody/1.0.0')==(200,body)
                rows=[json.loads(row) for row in request('/index/ht/tp/httpbody')[1].splitlines()]
                assert rows==[index]
            else:
                assert request('/pkg/httpbody/1.0.0')[0]==404
                assert not [p for p in (folder/'storage').rglob('*') if p.is_file()]
        assert token not in (folder/'server.log').read_text(errors='replace')
    for label,limit,authorized,expected,chunked in (
        ('default-content-length-16MiB',None,True,200,False),
        ('configured-exact-artifact-16MiB',16*1048576,True,200,False),
        ('invalid-credential-large-frame',None,False,401,False),
        ('declared-frame-exceeds-configured-envelope',1048576,True,413,False),
        ('chunked-16MiB',None,True,200,True)):
        error=''
        try:scenario(label,limit,authorized,expected,chunked)
        except Exception as failure:error=type(failure).__name__+': '+str(failure)
        cases.append(dict(name=label,passed=not error,error=error));print(('FAIL ' if error else 'PASS ')+label,flush=True)
    success=all(c['passed'] for c in cases)
    (report/'summary.json').write_text(json.dumps(dict(success=success,passed=sum(c['passed'] for c in cases),total=len(cases),
        serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),artifactBytes=len(body),frameBytes=len(frame),
        seconds=round(time.monotonic()-started,2),cases=cases),indent=2)+'\n')
    return int(not success)


if __name__=='__main__':raise SystemExit(main())
