#!/usr/bin/env python3
"""Verify per-package Hosted publication index bounds on owned Linux processes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import argparse,copy,hashlib,http.client,json,os,secrets,shutil,socket,sys,threading,time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses,publish_frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('server','package-dir','evidence-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.name!='posix':parser.error('Windows Cangjie execution is paused')
    server=args.server.resolve();report=args.evidence_dir.resolve();report.mkdir(parents=True,exist_ok=False)
    meta=json.loads((args.package_dir/'meta-data.json').read_text())
    artifact=(args.package_dir/(meta['name']+'-'+meta['version']+'.cjp')).read_bytes()
    assert meta['name']=='meshdep' and not meta['organization'] and meta['version']=='1.0.0'
    assert hashlib.sha256(artifact).hexdigest()==meta['index']['sha256sum']
    token=secrets.token_hex(32);variable='CJREPO_MAX_HOSTED_INDEX_BYTES'
    base={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_'))}
    cases=[];started=time.monotonic()
    def metadata(version='1.0.0',name='meshdep',organization='',unicode=False):
        item=copy.deepcopy(meta);item.update(version=version,name=name,organization=organization)
        item['index'].update(version=version,name=name,organization=organization)
        if unicode:item['index']['description']='仓颉私有依赖'*32
        return item
    def body(item):return publish_frame(json.dumps(item,ensure_ascii=False).encode(),artifact)
    def request(port,path,data=None,authorized=True):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            conn.request('POST' if data is not None else 'GET',path,body=data,
                headers={'Authorization':token} if authorized else {})
            response=conn.getresponse();return response.status,response.read()
        finally:conn.close()
    def publish(port,item,authorized=True):
        query='?organization='+item['organization'] if item['organization'] else ''
        return request(port,'/pkg/'+item['name']+query,body(item),authorized)[0]
    def stored(root):
        return {p.relative_to(root).as_posix():('directory' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
                for p in root.rglob('*') if p.is_file() or p.is_dir()}
    @contextmanager
    def owned(label,limit=None,storage=None,extra=None):
        folder=report/label;folder.mkdir()
        target=storage if storage is not None else folder/'storage'
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env=dict(base,HOME=str(folder),USERPROFILE=str(folder),CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),
            CJREPO_STORAGE=str(target),CJREPO_PUBLISH_TOKEN=token,CJREPO_READ_TOKEN=token)
        if limit is not None:env[variable]=str(limit)
        env.update(extra or {})
        with ManagedProcesses() as processes:
            process=processes.start([server],cwd=folder,env=env,output_path=folder/'server.log')
            ready=False
            for _ in range(100):
                if process.poll() is not None:break
                try:
                    ready=request(port,'/health')[0]==200
                    if ready:break
                except OSError:pass
                time.sleep(.02)
            yield port,target,process,ready
        assert process.poll() is not None
        text=(folder/'server.log').read_text(errors='replace')
        assert token not in text,'server log leaked test credential'
    def case(name,function):
        error=''
        try:function()
        except Exception as failure:error=type(failure).__name__+': '+str(failure)
        cases.append(dict(name=name,passed=not error,error=error));print(('FAIL ' if error else 'PASS ')+name,flush=True)
    index_rel=Path('index/default/me/sh/meshdep')
    artifact_rel=lambda version:Path('artifacts/default/meshdep')/version/('meshdep-'+version+'.cjp')
    # Use actual server serialization to establish byte boundaries, not Python JSON whitespace guesses.
    with owned('calibration',67108864) as (port,calibration,_,ready):
        assert ready and publish(port,metadata())==200
        first=request(port,'/index/me/sh/meshdep')[1]
        assert publish(port,metadata('2.0.0'))==200
        combined=request(port,'/index/me/sh/meshdep')[1]
        assert combined.startswith(first) and len(combined)>len(first)
    line2=combined[len(first):]
    (report/'calibration.json').write_text(json.dumps(dict(firstBytes=len(first),twoBytes=len(combined),
        firstSha256=hashlib.sha256(first).hexdigest(),twoSha256=hashlib.sha256(combined).hexdigest()),indent=2))
    def seed(label,*,two=False,orphan=False):
        root=report/(label+'-storage');root.mkdir()
        p=root/index_rel;p.parent.mkdir(parents=True);p.write_bytes(combined if two else first)
        for version in (('1.0.0','2.0.0') if two or orphan else ('1.0.0',)):
            p=root/artifact_rel(version);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(artifact)
        return root
    for label,raw in (('empty',''),('zero','0'),('negative','-1'),('text','synthetic-private-limit-value'),('too-large','67108865')):
        def invalid(label=label,raw=raw):
            with owned('invalid-'+label,raw) as (_,_,process,ready):
                assert not ready and process.poll()==2,'invalid limit must exit2 before serving'
            log=(report/('invalid-'+label)/'server.log').read_text()
            assert variable in log and (not raw.startswith('synthetic-') or raw not in log)
        case('invalid-'+label,invalid)
    def maximum():
        with owned('maximum',67108864) as (_,_,_,ready):assert ready
    case('maximum-accepted',maximum)
    def smallest():
        with owned('smallest',1) as (port,root,_,ready):
            before=stored(root)
            assert ready and publish(port,metadata(),authorized=False)==401
            assert stored(root)==before
            assert publish(port,metadata())==413,'index line above limit was accepted'
            assert stored(root)==before
    case('auth-before-index-one-byte-limit',smallest)
    def first_limit():
        with owned('first-exact',len(first)) as (port,root,_,ready):
            assert ready and publish(port,metadata())==200
            before=stored(root)
            assert publish(port,metadata())==409
            assert publish(port,metadata('2.0.0'))==413,'cumulative append above limit accepted'
            assert stored(root)==before and request(port,'/index/me/sh/meshdep')[1]==first
    case('first-exact-duplicate-and-overflow-preserve-original',first_limit)
    def second_limit():
        with owned('two-exact',len(combined)) as (port,root,_,ready):
            assert ready and publish(port,metadata())==publish(port,metadata('2.0.0'))==200
            assert request(port,'/index/me/sh/meshdep')[1]==combined
            before=stored(root)
            assert publish(port,metadata('3.0.0'))==413
            assert stored(root)==before and not list(root.rglob('*.tmp'))
    case('two-exact-and-third-refused-without-artifact-or-temporary',second_limit)
    def orphan_limit():
        root=seed('orphan',orphan=True);before=stored(root)
        with owned('orphan-full',len(first),root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==413
            assert stored(root)==before
        with owned('orphan-retry',len(combined),root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==200
            assert (root/index_rel).read_bytes()==combined
    case('orphan-capacity-refusal-and-larger-limit-retry',orphan_limit)
    def conflict():
        root=seed('conflict',orphan=True);(root/artifact_rel('2.0.0')).write_bytes(b'conflicting-owned-bytes');before=stored(root)
        with owned('conflict-full',len(first),root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==409,'capacity must not mask artifact conflict'
            assert stored(root)==before
    case('orphan-conflict-remains409-at-capacity',conflict)
    def recover():
        root=seed('missing',two=True);(root/artifact_rel('1.0.0')).unlink()
        with owned('missing-at-full',len(combined),root) as (port,_,_,ready):
            assert ready and publish(port,metadata())==200,'recorded missing artifact needs no index append'
            assert (root/artifact_rel('1.0.0')).read_bytes()==artifact and (root/index_rel).read_bytes()==combined
    case('full-index-still-recovers-recorded-missing-artifact',recover)
    def existing_over():
        root=seed('existing');(root/index_rel).write_bytes(first+b'\n');before=stored(root)
        with owned('existing-over',len(first),root) as (port,_,_,ready):
            assert ready and publish(port,metadata())==413
            assert stored(root)==before
    case('oversized-existing-index-refused-without-mutation',existing_over)
    def separator():
        root=seed('separator',orphan=True);(root/index_rel).write_bytes(first.rstrip(b'\n'))
        with owned('separator',len(combined),root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==200
            assert (root/index_rel).read_bytes()==combined
    case('missing-newline-separator-counted-at-exact-limit',separator)
    def unicode_limit():
        root=seed('unicode');item=json.loads(first);item['description']='仓颉依赖'*32
        raw=(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        assert len(raw)>len(raw.decode())
        (root/index_rel).write_bytes(raw);before=stored(root)
        with owned('unicode-over',len(raw)+len(line2)-1,root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==413,'UTF8 bytes were not counted'
            assert stored(root)==before
        with owned('unicode-exact',len(raw)+len(line2),root) as (port,_,_,ready):
            assert ready and publish(port,metadata('2.0.0'))==200
            assert (root/index_rel).read_bytes()==raw+line2
    case('utf8-byte-boundary-not-character-count',unicode_limit)
    def concurrent():
        root=seed('concurrent');barrier=threading.Barrier(2)
        with owned('concurrent',len(combined),root) as (port,_,_,ready):
            assert ready
            def send(version):barrier.wait(timeout=5);return version,publish(port,metadata(version))
            with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(send,('2.0.0','3.0.0')))
            assert sorted(status for _,status in values)==[200,413],values
            winner=next(version for version,status in values if status==200)
            loser=next(version for version,status in values if status==413)
            data=(root/index_rel).read_bytes();assert len(data)==len(combined)
            assert {json.loads(line)['version'] for line in data.splitlines()}=={'1.0.0',winner}
            assert (root/artifact_rel(winner)).read_bytes()==artifact and not (root/artifact_rel(loser)).exists()
            assert not (root/artifact_rel(loser)).parent.exists()
    case('concurrent-appends-cannot-cross-shared-byte-boundary',concurrent)
    def isolation():
        with owned('isolation',len(combined),extra={'CJREPO_MAX_INDEX_BYTES':'1'}) as (port,root,_,ready):
            assert ready and publish(port,metadata())==200
            original=(root/index_rel).read_bytes()
            assert publish(port,metadata(name='othrdep'))==200 and publish(port,metadata(organization='company'))==200
            assert (root/index_rel).read_bytes()==original
            assert request(port,'/index/me/sh/meshdep?organization=company')[0]==200
    case('per-package-organization-and-upstream-limit-isolation',isolation)
    summary=dict(success=all(item['passed'] for item in cases),passed=sum(item['passed'] for item in cases),total=len(cases),
        cases=cases,seconds=round(time.monotonic()-started,2),serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),cleanupErrors=[])
    (report/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('success','passed','total','cleanupErrors')}),flush=True)
    return int(not summary['success'])


if __name__=='__main__':raise SystemExit(main())
