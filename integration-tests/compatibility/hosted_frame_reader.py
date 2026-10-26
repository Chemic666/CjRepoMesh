#!/usr/bin/env python3
"""Framing/short-read regressions on owned Linux Hosted processes; no SDK downloads."""
from pathlib import Path
import argparse,hashlib,http.client,json,os,secrets,socket,struct,sys,time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses,publish_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows Cangjie execution is paused')
    server=args.server.resolve();report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    token=secrets.token_hex(32);artifact=hashlib.shake_256(b'CjRepoMesh frame reader').digest(16384)
    digest=hashlib.sha256(artifact).hexdigest();started=time.monotonic();cases=[]
    def metadata(version='1.0.0',padding=None):
        row=dict(name='frameprobe',version=version,organization='',sha256sum=digest,dependencies=[])
        result=dict(name='frameprobe',version=version,organization='',index=row)
        if padding is not None:result['padding']=padding
        return json.dumps(result,separators=(',',':')).encode()
    meta=metadata();frame=publish_frame(meta,artifact)
    exact=metadata(padding='');exact=metadata(padding='x'*(1048576-len(exact)));assert len(exact)==1048576
    artifact_header=5+len(meta)
    definitions=[('fixed-length',frame,200,None),('chunked-byte-boundaries',frame,200,'byte'),
        ('chunked-part-boundaries',frame,200,'part'),('exact-metadata-limit',publish_frame(exact,artifact),200,None),
        ('empty',b'',400,None),('short-first-header',frame[:4],400,None),
        ('wrong-first-version',b'\x02'+frame[1:],400,None),
        ('zero-metadata',b'\x01'+struct.pack('<I',0)+b'\x01'+struct.pack('<I',len(artifact))+artifact,400,None),
        ('truncated-metadata',frame[:5+len(meta)-1],400,None),
        ('short-artifact-header',frame[:artifact_header+4],400,None),
        ('wrong-artifact-version',frame[:artifact_header]+b'\x02'+frame[artifact_header+1:],400,None),
        ('zero-artifact',publish_frame(meta,b''),400,None),('truncated-artifact',frame[:-1],400,None),
        ('trailing-artifact-byte',frame+b'x',400,None),
        ('declared-metadata-over-limit',b'\x01'+struct.pack('<I',1048577)+b'xxxxxx',413,None),
        ('declared-artifact-over-limit',frame[:artifact_header+1]+struct.pack('<I',len(artifact)+1),413,None),
        ('malformed-chunked-total-over-limit',b'x'*(len(artifact)+1048576+11),413,'part'),
        ('valid-frame-chunked-trailing-total-over-limit',frame+b'x'*(1048576-len(meta)+1),413,'part'),
        ('disconnect-after-valid-headers',frame[:artifact_header+5+17],200,'disconnect')]
    original={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    def stored(folder):return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
    for label,data,expected,chunking in definitions:
        folder=report/label;folder.mkdir();storage=folder/'storage';error=''
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env=dict(original,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),
                 CJREPO_STORAGE=str(storage),CJREPO_PUBLISH_TOKEN=token,CJREPO_READ_TOKEN=token,
                 CJREPO_MAX_ARTIFACT_BYTES=str(len(artifact)),CJREPO_MAX_CONCURRENT_PUBLISHES='1')
        def request(path,data=None,chunks=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.request('GET' if data is None else 'POST',path,body=chunks if chunks is not None else data,
                                   headers={'Authorization':token},encode_chunked=chunks is not None)
                response=connection.getresponse();return response.status,response.read()
            finally:connection.close()
        try:
            with ManagedProcesses() as processes:
                process=processes.start([server],cwd=folder,env=env,output_path=folder/'server.log')
                for _ in range(100):
                    try:
                        if request('/health')[0]==200:break
                    except OSError:pass
                    if process.poll() is not None:raise AssertionError('server exited')
                    time.sleep(.03)
                else:raise AssertionError('readiness deadline')
                chunks=None
                if chunking and chunking!='disconnect':
                    cuts=([1,2,3,4,5,6,artifact_header-1,artifact_header,artifact_header+1,artifact_header+2,
                           artifact_header+3,artifact_header+4,artifact_header+5,len(data)-1,len(data)] if chunking=='byte' else
                          list(range(3,len(data),8191))+[len(data)])
                    cuts=sorted({n for n in cuts if 0<n<=len(data)})
                    def pieces():
                        position=0
                        for end in cuts:
                            yield data[position:end];position=end;time.sleep(.001)
                    chunks=pieces()
                if chunking=='disconnect':
                    partial=socket.create_connection(('127.0.0.1',port),timeout=5)
                    try:
                        headers=(f'POST /pkg/frameprobe HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: {token}\r\n'
                                 f'Content-Length: {len(frame)}\r\n\r\n').encode()
                        partial.sendall(headers+data)
                        # Give the partial request the same head start as the admission
                        # regression: a competing full probe can otherwise win the slot.
                        time.sleep(.05)
                        for _ in range(100):
                            busy,_=request('/pkg/differentroute',frame)
                            if busy==429:break
                            assert busy==400
                            time.sleep(.01)
                        else:raise AssertionError('partial valid frame did not hold its sole slot')
                    finally:partial.close()
                    assert stored(storage)=={},'partial body wrote storage'
                    for _ in range(100):
                        status,_=request('/pkg/frameprobe',frame)
                        if status==200:break
                        assert status==429
                        time.sleep(.01)
                    else:raise AssertionError('disconnect did not release its sole slot')
                else:
                    status,_=request('/pkg/frameprobe',data,chunks)
                assert status==expected,f'returned {status}, expected {expected}'
                if expected!=200:
                    assert stored(storage)=={},'rejected frame changed storage'
                    assert request('/pkg/frameprobe',frame)[0]==200,'slot was not released after rejected frame'
                status,content=request('/pkg/frameprobe/1.0.0');assert status==200 and content==artifact
                status,index=request('/index/fr/am/frameprobe');assert status==200
                assert [json.loads(line) for line in index.splitlines()]==[json.loads(meta)['index']]
                before=stored(storage)
                assert request('/pkg/frameprobe',frame)[0]==409 and stored(storage)==before
            assert token not in (folder/'server.log').read_text(errors='replace')
        except Exception as failure:error=type(failure).__name__+': '+str(failure)
        cases.append(dict(name=label,passed=not error,error=error));print(('FAIL ' if error else 'PASS ')+label,flush=True)
    result=dict(success=all(c['passed'] for c in cases),passed=sum(c['passed'] for c in cases),total=len(cases),
                cases=cases,serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),seconds=round(time.monotonic()-started,2))
    (report/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return int(not result['success'])


if __name__=='__main__':raise SystemExit(main())
