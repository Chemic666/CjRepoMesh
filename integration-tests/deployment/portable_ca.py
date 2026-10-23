#!/usr/bin/env python3
"""Verify standard Compose CA import and genuine HTTPS proxy/cache behavior."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

FIXTURE = r'''
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,os,ssl,subprocess,sys
cert=Path('/cert')
if sys.argv[1]=='prepare':
 def openssl(*args):
  r=subprocess.run(['/tools/openssl',*args],cwd=cert,env=dict(os.environ,OPENSSL_CONF='/dev/null'),capture_output=True)
  assert r.returncode==0,'synthetic certificate generation failed'
 openssl('req','-x509','-newkey','rsa:2048','-nodes','-subj','/CN=CjRepoMesh synthetic CA','-days','1',
         '-addext','basicConstraints=critical,CA:TRUE','-keyout','ca.key','-out','ca.pem')
 for number,(name,san) in enumerate((('good','DNS:localhost,IP:127.0.0.1'),('wrong','DNS:wrong.invalid')),1):
  openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',name+'.key','-out',name+'.csr')
  (cert/(name+'.ext')).write_text('subjectAltName='+san+'\nextendedKeyUsage=serverAuth\n')
  openssl('x509','-req','-in',name+'.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial',str(number),
          '-days','1','-extfile',name+'.ext','-out',name+'.pem')
 for path in cert.glob('*.key'):path.chmod(0o600)
 raise SystemExit(0)
package=Path('/package');meta=json.loads((package/'meta-data.json').read_text())
name,version=meta['name'],meta['version'];artifact=(package/(name+'-'+version+'.cjp')).read_bytes()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  authorized=self.headers.get('Authorization')==os.environ['FIXTURE_TOKEN']
  with Path('/state/requests.jsonl').open('a') as stream:stream.write(json.dumps(dict(path=self.path,authorized=authorized))+'\n')
  payload=(json.dumps(meta['index'])+'\n').encode() if self.path.startswith('/index/') else artifact
  self.send_response(200 if authorized else 401);self.send_header('Content-Length',str(len(payload)))
  self.send_header('Connection','close');self.end_headers();self.wfile.write(payload)
 def log_message(self,*args):pass
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def get_request(self):
  raw,address=super().get_request();raw.settimeout(5)
  try:
   choice=Path('/state/mode').read_text().strip()
   context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
   context.load_cert_chain(cert/(choice+'.pem'),cert/(choice+'.key'))
   return context.wrap_socket(raw,server_side=True),address
  except Exception:raw.close();raise
server=Server(('127.0.0.1',44443),Handler);print('READY',flush=True);server.serve_forever()
'''


def safe_error(failure, secrets_to_hide):
    text = type(failure).__name__+': '+str(failure)
    for secret in secrets_to_hide:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


def restore_configuration(original: bytes, project: str) -> bytes:
    """Change only the owned drill's project, retaining credential bytes."""
    pattern = rb'COMPOSE_PROJECT_NAME=(cjrepomesh-[a-f0-9]{16})'
    lines = original.splitlines(keepends=True)
    identities = [line.rstrip(b'\r\n') for line in lines
                  if line.startswith(b'COMPOSE_PROJECT_NAME=')]
    if (len(identities) != 1 or not re.fullmatch(pattern, identities[0]) or
            not re.fullmatch(r'cjrepomesh-[a-f0-9]{16}', project) or
            identities[0].split(b'=', 1)[1] == project.encode()):
        raise ValueError('recovery requires distinct, unambiguous owned project identities')
    return b''.join(line.replace(identities[0], b'COMPOSE_PROJECT_NAME='+project.encode(), 1)
                    if line.rstrip(b'\r\n') == identities[0] else line for line in lines)


def run_process(arguments, *, cwd=None, env=None, timeout=120):
    return subprocess.run(list(map(str,arguments)),cwd=cwd,env=env,capture_output=True,
                          text=True,encoding='utf-8',errors='replace',timeout=timeout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','package-dir','native','openssl','evidence-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--cold-restore',action='store_true',help='also recover owned configuration/data and build a real consumer')
    parser.add_argument('--maintenance',action='store_true',help='exercise the receiver backup/restore tool and an independent source baseline; requires cold-restore')
    parser.add_argument('--hosted-package-dir',type=Path,help='existing real company::teamhello CJP and metadata; required for maintenance')
    parser.add_argument('--client-bundle',type=Path)
    parser.add_argument('--client-sdk',type=Path)
    parser.add_argument('--expected-output',default='high-1.0.0',help='expected marker from the supplied meshdep CJP')
    args=parser.parse_args();bundle=args.bundle.resolve();report=args.evidence_dir.resolve()
    if args.maintenance and not args.cold_restore:parser.error('maintenance requires cold-restore')
    if args.maintenance and not args.hosted_package_dir:parser.error('maintenance requires hosted-package-dir')
    if args.hosted_package_dir and not args.maintenance:parser.error('hosted-package-dir requires maintenance')
    if not (args.native/'bin/python3').is_file() or not args.openssl.is_file(): parser.error('existing Linux Python/native tools and OpenSSL are required')
    source=Path(__file__).resolve().parents[2]
    verifier=runpy.run_path(str(source/'deployment/portable/verify.py'))['verify_bundle']
    verifier(bundle)
    if (bundle/'.env').exists() or (bundle/'trust').exists():parser.error('use an unconfigured seven-file bundle')
    client_manifest=None
    if args.cold_restore:
        if not args.client_bundle or not args.client_sdk or not (args.client_sdk/'envsetup.sh').is_file():
            parser.error('cold-restore requires a verified client-bundle and existing client-sdk')
        client_manifest=runpy.run_path(str(source/'deployment/client/verify.py'))['verify_bundle'](args.client_bundle)
    elif args.client_bundle or args.client_sdk:parser.error('client options require cold-restore')
    metadata=json.loads((args.package_dir/'meta-data.json').read_text());name,version=metadata['name'],metadata['version']
    if metadata['organization'] or len(name)<4:parser.error('use an existing default-organization CJP')
    if args.cold_restore and name!='meshdep':parser.error('the recovery consumer requires the meshdep fixture')
    artifact=(args.package_dir/f'{name}-{version}.cjp').read_bytes();artifact_sha=hashlib.sha256(artifact).hexdigest()
    assert artifact_sha==metadata['index']['sha256sum']
    if args.maintenance:
        hosted_metadata_bytes=(args.hosted_package_dir/'meta-data.json').read_bytes()
        hosted_metadata=json.loads(hosted_metadata_bytes)
        if (hosted_metadata['organization'],hosted_metadata['name'],hosted_metadata['version'])!=('company','teamhello','1.0.0'):
            parser.error('maintenance requires the real company::teamhello 1.0.0 example')
        hosted_artifact=(args.hosted_package_dir/'teamhello-1.0.0.cjp').read_bytes()
        hosted_sha=hashlib.sha256(hosted_artifact).hexdigest()
        assert hosted_sha==hosted_metadata['index']['sha256sum']
        frame=runpy.run_path(str(source/'integration-tests/lib/harness.py'))['publish_frame'](hosted_metadata_bytes,hosted_artifact)
    report.mkdir(parents=True,exist_ok=False);installation=report/'installation';shutil.copytree(bundle,installation)
    state=report/'state';state.mkdir();(state/'mode').write_text('wrong');cert=report/'cert';cert.mkdir()
    tools=report/'tools';tools.mkdir();shutil.copyfile(args.openssl,tools/'openssl');(tools/'fixture.py').write_text(FIXTURE)
    environment={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_','COMPOSE_'))}
    token=secrets.token_hex(32);secrets_to_hide=[token];project='';projects=[];containers=[];stages=[];cleanup=[];error='';started=time.monotonic()
    total=21 if args.maintenance else (15 if args.cold_restore else 10)
    manifest=json.loads((installation/'manifest.json').read_text());image=manifest['image'];opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def run(label,arguments,*,success=True,log=True,timeout=120,directory=None):
        result=run_process(arguments,cwd=directory or installation,env=environment,timeout=timeout)
        text=result.stdout+result.stderr
        for secret in secrets_to_hide:text=text.replace(secret,'[REDACTED]')
        if log:(report/(label+'.log')).write_text(text,encoding='utf-8')
        assert success is None or (result.returncode==0)==success,label+' failed; inspect retained log'
        return result.stdout
    def compose(label,*arguments,**options):return run(label,['docker','compose','-p',project,'-f','compose.yaml','--env-file','.env',*arguments],**options)
    def passed(label,**facts):
        stages.append(dict(name=label,facts=facts));print(f'PASS {len(stages)}/{total} {label}',flush=True)
    def helper(label,prepare=False,service=None):
        name='cjrepomesh-ca-'+uuid.uuid4().hex;command=['docker','create','--pull=never','--name',name,'--label','cjrepomesh.ca-proof='+name,
          '--read-only','--cap-drop=ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:size=16m,mode=1777',
          '--network','none' if prepare else 'container:'+service,'--env','PYTHONHOME=/native','--env','FIXTURE_TOKEN='+token]
        for source,target,readonly in ((args.native.resolve(),'/native',True),(tools,'/tools',True),(cert,'/cert',not prepare),(args.package_dir.resolve(),'/package',True),(state,'/state',False)):
            command+=['--mount',f'type=bind,source={source},target={target}'+(',readonly' if readonly else '')]
        command+=['--entrypoint','/lib64/ld-linux-x86-64.so.2',image['id'],'--library-path','/native/lib','/native/bin/python3','/tools/fixture.py','prepare' if prepare else 'serve']
        run(label+'-create',command);containers.append(name)
        run(label+'-start',['docker','start',*(['--attach'] if prepare else []),name])
        if prepare:
            item=json.loads(run(label+'-inspect',['docker','inspect',name],log=False))[0];assert item['State']['ExitCode']==0
        else:
            for _ in range(50):
                if 'READY' in run(label+'-ready',['docker','logs',name],log=False):break
                time.sleep(.1)
            else:raise AssertionError('owned TLS fixture not ready')
        return name
    def get(path,credential=''):
        request=urllib.request.Request(base+path,headers={'Authorization':credential} if credential else {})
        try:
            with opener.open(request,timeout=6) as response:return response.status,response.read()
        except urllib.error.HTTPError as failure:
            with failure:return failure.code,failure.read()
    def ready():
        for _ in range(60):
            identifier=compose('service-id','ps','-q','cjrepo',log=False).strip()
            if identifier and run('health',['docker','inspect','--format','{{.State.Health.Status}}',identifier],log=False).strip()=='healthy':return identifier
            time.sleep(.5)
        raise AssertionError('service did not become healthy')
    def requests():return [json.loads(line) for line in (state/'requests.jsonl').read_text().splitlines()] if (state/'requests.jsonl').exists() else []
    try:
        run('verify-files',[sys.executable,'verify.py']);helper('certificates',prepare=True)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        run('configure',[sys.executable,'configure.py','--port',port,'--ca-file',cert/'ca.pem'])
        values=dict(line.split('=',1) for line in (installation/'.env').read_text().splitlines());project=values['COMPOSE_PROJECT_NAME']
        projects.append((installation,project))
        secrets_to_hide += [values['CJREPO_READ_TOKEN'],values['CJREPO_PUBLISH_TOKEN']]
        with (installation/'.env').open('a') as stream:stream.write('CJREPO_UPSTREAM=https://localhost:44443\nCJREPO_UPSTREAM_TOKEN='+token+'\n')
        env_sha=hashlib.sha256((installation/'.env').read_bytes()).hexdigest();ca_sha=hashlib.sha256((cert/'ca.pem').read_bytes()).hexdigest()
        assert values['CJREPO_CA_SHA256']==ca_sha
        passed('certificate-imported-with-private-configuration',caSha256=ca_sha)
        run('verify-image',[sys.executable,'verify.py','--docker']);passed('loaded-image-and-server-identity-verified',image=image['id'])
        compose('up','up','-d','--no-build','--pull','never');identifier=ready();fixture=helper('fixture',service=identifier);passed('standard-compose-and-owned-tls-fixture-ready')
        run('running-ca',[sys.executable,'verify.py','--running']);passed('running-ca-digest-and-readonly-bind-verified')
        index_path=f'/index/{name[:2]}/{name[2:4]}/{name}';artifact_path=f'/pkg/{name}/{version}'
        assert get(index_path)[0]==401 and not requests();passed('unauthorized-read-does-not-reach-upstream')
        assert get(index_path,values['CJREPO_READ_TOKEN'])[0]==502 and not requests()
        assert not run('failed-storage',['docker','exec',identifier,'find','/var/lib/cjrepo','-type','f'],log=False).strip()
        passed('wrong-dns-certificate-rejected-before-http-and-cache')
        (state/'mode').write_text('good')
        code,body=get(index_path,values['CJREPO_READ_TOKEN']);assert code==200 and json.loads(body)['sha256sum']==artifact_sha
        assert get(artifact_path,values['CJREPO_READ_TOKEN'])==(200,artifact)
        assert [item['path'] for item in requests()]==[index_path,artifact_path] and all(item['authorized'] for item in requests())
        passed('same-proxy-recovers-and-verifies-real-cjp-over-https',artifactSha256=artifact_sha)
        imported=installation/'trust/ca.pem';original=imported.read_bytes()
        try:
            imported.chmod(0o600);imported.write_bytes(b'synthetic-corruption')
            run('tampered-ca',[sys.executable,'verify.py','--running'],success=False)
        finally:imported.write_bytes(original);imported.chmod(0o444)
        run('restored-ca',[sys.executable,'verify.py','--running']);passed('host-ca-tamper-rejected-and-restored')
        run('fixture-remove',['docker','rm','--force',fixture]);containers.remove(fixture)
        assert get(index_path,values['CJREPO_READ_TOKEN'])[0]==200 and get(artifact_path,values['CJREPO_READ_TOKEN'])==(200,artifact)
        passed('verified-cache-survives-upstream-offline')
        compose('recreate','up','-d','--force-recreate','--no-build','--pull','never');ready()
        run('recreated-ca',[sys.executable,'verify.py','--running'])
        assert get(artifact_path,values['CJREPO_READ_TOKEN'])==(200,artifact) and hashlib.sha256((installation/'.env').read_bytes()).hexdigest()==env_sha
        passed('recreated-service-retains-ca-credentials-and-cache')
        if args.maintenance:
            def publish(credential):
                request=urllib.request.Request(base+'/pkg/teamhello?organization=company',data=frame,
                    headers={'Authorization':credential},method='POST')
                try:
                    with opener.open(request,timeout=6) as response:return response.status
                except urllib.error.HTTPError as failure:
                    with failure:return failure.code
            status=publish(values['CJREPO_READ_TOKEN']);assert status==401,f'read-only publish returned {status}; expected 401'
            status=publish(values['CJREPO_PUBLISH_TOKEN']);assert status==200,f'private publish returned {status}; expected 200'
            status=publish(values['CJREPO_PUBLISH_TOKEN']);assert status==409,f'duplicate publish returned {status}; expected 409'
            assert get('/pkg/teamhello/1.0.0?organization=company')[0]==401
            assert get('/pkg/teamhello/1.0.0?organization=company',values['CJREPO_READ_TOKEN'])==(200,hosted_artifact)
            passed('real-private-company-cjp-published-with-readonly-denial-and-duplicate-conflict',artifactSha256=hosted_sha)
        if args.cold_restore:
            archive_manifest=runpy.run_path(str(source/'integration-tests/recovery/docker_backup.py'))['archive_manifest']
            original_installation,original_project=installation,project
            original_env=(installation/'.env').read_bytes()
            original_manifest=hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()
            backup_config=report/'configuration-backup'
            if args.maintenance:
                live_output=report/'refused-live-backup'
                run('live-backup-refused',[sys.executable,'maintenance.py','backup','--output',live_output],success=False)
                assert not live_output.exists()
                passed('receiver-tool-refuses-backup-with-live-writer')
            else:
                shutil.copytree(bundle,backup_config)
                # Configure protects the file before writing any backed-up secret.
                run('backup-private-file',[sys.executable,backup_config/'configure.py','--port',port,'--ca-file',imported],directory=backup_config)
                (backup_config/'.env').write_bytes(original_env)
            compose('stop-source','down')
            assert not compose('source-offline','ps','-a','-q',log=False).strip()
            def transfer(label,volume,archive,extract=False):
                helper_name='cjrepomesh-restore-'+uuid.uuid4().hex
                command=['docker','create','--pull=never','--name',helper_name,'--network','none','--read-only',
                  '--label','cjrepomesh.ca-proof='+helper_name,'--cap-drop=ALL','--security-opt','no-new-privileges:true','--mount',
                  f'type=volume,source={volume},target=/data'+('' if extract else ',readonly')]
                if extract:command+=['--interactive']
                command+=['--entrypoint','/bin/tar',image['id'],'-C','/data','-xf' if extract else '-cf','-']
                if not extract:command+=['.']
                run(label+'-create',command);containers.append(helper_name)
                with archive.open('rb' if extract else 'wb') as stream:
                    result=subprocess.run(['docker','start','--attach',*(['--interactive'] if extract else []),helper_name],
                      env=environment,stdin=stream if extract else None,stdout=subprocess.PIPE if extract else stream,
                      stderr=subprocess.PIPE,timeout=60)
                assert result.returncode==0,label+' transfer failed'
                item=json.loads(run(label+'-exit',['docker','inspect',helper_name],log=False))[0]
                assert item['State']['ExitCode']==0,label+' helper failed'
            if args.maintenance:
                writer='cjrepomesh-writer-'+uuid.uuid4().hex
                run('writer-create',['docker','create','--pull=never','--name',writer,
                    '--label','cjrepomesh.ca-proof='+writer,'--network','none','--read-only',
                    '--cap-drop=ALL','--security-opt','no-new-privileges:true','--mount',
                    'type=volume,source='+original_project+'_cjrepo-data,target=/var/lib/cjrepo',
                    '--entrypoint','/bin/sleep',image['id'],'120'])
                containers.append(writer);run('writer-start',['docker','start',writer])
                refused=report/'refused-foreign-writer'
                run('foreign-writer-refused',[sys.executable,'maintenance.py','backup','--output',refused],success=False)
                assert not refused.exists()
                run('writer-stop',['docker','rm','--force',writer]);containers.remove(writer)
                passed('receiver-tool-refuses-a-running-foreign-volume-writer')
                run('receiver-backup',[sys.executable,'maintenance.py','backup','--output',backup_config])
                run('receiver-backup-verify',[sys.executable,'maintenance.py','verify-backup','--backup',backup_config])
                backup=backup_config/'data.tar'
            else:
                backup=report/'data-backup.tar';transfer('export',original_project+'_cjrepo-data',backup)
            backup_env_sha=hashlib.sha256((backup_config/'.env').read_bytes()).hexdigest()
            files=archive_manifest(backup);assert len(files)==(4 if args.maintenance else 2)
            backup_sha=hashlib.sha256(backup.read_bytes()).hexdigest()
            passed('stopped-source-data-and-private-ca-configuration-backed-up',files=files,archiveSha256=backup_sha,configurationSha256=backup_env_sha)
            installation=report/'restored-installation';shutil.copytree(bundle,installation)
            if args.maintenance:
                before_volumes=run('volumes-before-rejections',['docker','volume','ls','--quiet'],log=False)
                damaged=report/'damaged-backup';shutil.copytree(backup_config,damaged)
                (damaged/'data.tar').write_bytes(b'synthetic damaged archive')
                run('corrupt-backup-refused',[sys.executable,'maintenance.py','restore','--backup',damaged],success=False)
                assert not (installation/'.env').exists() and not (installation/'trust').exists()
                run('configured-target-refused',[sys.executable,original_installation/'maintenance.py','restore','--backup',backup_config],success=False)
                assert (original_installation/'.env').read_bytes()==original_env
                assert run('volumes-after-rejections',['docker','volume','ls','--quiet'],log=False)==before_volumes
                passed('corrupt-backup-and-existing-configuration-refused-without-mutation')
                wrong=report/'wrong-image-backup';shutil.copytree(backup_config,wrong)
                wrong_value=json.loads((wrong/'backup.json').read_text())
                wrong_value['image']={**image,'id':'sha256:'+'0'*64,'tag':'cjrepomesh-portable:sha256-'+'0'*64}
                (wrong/'backup.json').write_text(json.dumps(wrong_value))
                run('wrong-image-refused',[sys.executable,'maintenance.py','restore','--backup',wrong],success=False)
                assert not (installation/'.env').exists() and not (installation/'trust').exists()
                assert run('volumes-after-wrong-image',['docker','volume','ls','--quiet'],log=False)==before_volumes
                passed('receiver-tool-refuses-a-different-image-before-creating-config-or-volume')
                run('receiver-restore',[sys.executable,'maintenance.py','restore','--backup',backup_config])
                new_values=dict(line.split('=',1) for line in (installation/'.env').read_text().splitlines())
                project=new_values['COMPOSE_PROJECT_NAME'];assert project!=original_project
                recovered_env=restore_configuration(original_env,project)
                assert (installation/'.env').read_bytes()==recovered_env
            else:
                run('configure-recovery',[sys.executable,'configure.py','--port',port,'--ca-file',backup_config/'trust/ca.pem'])
                new_values=dict(line.split('=',1) for line in (installation/'.env').read_text().splitlines());project=new_values['COMPOSE_PROJECT_NAME']
                assert project!=original_project
                recovered_env=restore_configuration((backup_config/'.env').read_bytes(),project)
                (installation/'.env').write_bytes(recovered_env)
            projects.append((installation,project))
            assert (installation/'trust/ca.pem').read_bytes()==(backup_config/'trust/ca.pem').read_bytes()==original
            compose('create-recovery','create','--no-build','--pull','never')
            if not args.maintenance:transfer('import',project+'_cjrepo-data',backup,extract=True)
            restored_tar=report/'restored-before-start.tar';transfer('compare-restored',project+'_cjrepo-data',restored_tar)
            assert archive_manifest(restored_tar)==files
            passed('separate-project-and-volume-restored-with-identical-data-ca-and-credentials')
            compose('start-recovery','up','-d','--no-build','--pull','never');recovered=ready()
            run('verify-recovery',[sys.executable,'verify.py','--running'])
            assert get(artifact_path)[0]==401 and get(artifact_path,values['CJREPO_READ_TOKEN'])==(200,artifact)
            if args.maintenance:
                assert get('/pkg/teamhello/1.0.0?organization=company')[0]==401
                assert get('/pkg/teamhello/1.0.0?organization=company',values['CJREPO_READ_TOKEN'])==(200,hosted_artifact)
            assert not run('original-offline',['docker','compose','-p',original_project,'-f',original_installation/'compose.yaml',
              '--env-file',original_installation/'.env','ps','-a','-q'],log=False).strip()
            passed('restored-standard-compose-serves-private-cache-with-original-offline')
            consumer=report/'fresh-consumer';consumer.mkdir()
            fixture=source/'integration-tests/hosted-server/app'
            shutil.copytree(fixture/'src',consumer/'src')
            shutil.copyfile(fixture/'cjpm.toml',consumer/'cjpm.toml')
            assert not (consumer/'cache').exists() and not (consumer/'target').exists()
            config=consumer/'cjpm.toml';config.write_text(config.read_text().replace('meshdep = "2.0.0"',f'meshdep = "{version}"'))
            if args.maintenance:
                with config.open('a') as stream:stream.write('"company::teamhello" = "1.0.0"\n')
                application=consumer/'src/main.cj'
                application.write_text(application.read_text().replace('import meshdep.*','import meshdep.*\nimport company::teamhello.*').replace(
                    '    return 0','    println(teamGreeting("recovered"))\n    return 0'))
            (consumer/'cangjie-repo.toml').write_text('[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "http://127.0.0.1:8080"\ntoken-env = "CJREPOMESH_RECOVERY_READ_TOKEN"\n')
            approval=report/'approved-recovery-source.json'
            if args.maintenance:
                approved=dict(formatVersion=1,packages=[dict(package=name,version=version,repository='home',
                    registry='http://127.0.0.1:8080',sha256=artifact_sha),
                    dict(package='company::teamhello',version='1.0.0',repository='home',
                         registry='http://127.0.0.1:8080',sha256=hosted_sha)])
                approved['packages'].sort(key=lambda item:item['package'])
                with approval.open('x',encoding='utf-8') as stream:json.dump(approved,stream)
                approval_sha=hashlib.sha256(approval.read_bytes()).hexdigest()
            job='cjrepomesh-consumer-'+uuid.uuid4().hex
            command=['docker','create','--pull=never','--name',job,'--network','container:'+recovered,'--read-only',
              '--label','cjrepomesh.ca-proof='+job,'--cap-drop=ALL','--security-opt','no-new-privileges:true',
              '--tmpfs','/tmp:size=128m,mode=1777','--workdir','/job']
            for host,target in ((consumer,'/job'),(args.client_bundle.resolve(),'/client'),(args.client_sdk.resolve(),'/opt/cangjie'),(args.native.resolve(),'/opt/native')):
                command+=['--mount',f'type=bind,source={host},target={target}'+('' if host==consumer else ',readonly')]
            for host in sorted((args.native/'system').rglob('*')):
                if host.is_file():command+=['--mount',f'type=bind,source={host.resolve()},target=/{host.relative_to(args.native/"system").as_posix()},readonly']
            if args.maintenance:
                command+=['--mount',f'type=bind,source={approval},target=/approved/source.json,readonly',
                    '--env','CJREPOMESH_SOURCE_BASELINE=/approved/source.json']
            job_script='source /opt/cangjie/envsetup.sh; export PATH="/opt/native/bin:$PATH" LD_LIBRARY_PATH="/opt/native/lib:$LD_LIBRARY_PATH"; '
            job_script+=('set -u; /client/run.sh repo supports source-baseline-v1; /client/run.sh build; ./target/release/bin/main'
                         if args.maintenance else 'exec /client/run.sh run')
            command+=['--env','HOME=/job/.home','--env','CJREPOMESH_RECOVERY_READ_TOKEN='+values['CJREPO_READ_TOKEN'],
              '--entrypoint','/bin/bash',image['id'],'-ec',job_script]
            run('consumer-create',command);containers.append(job)
            run('consumer-build-run',['docker','start','--attach',job],timeout=180)
            output=(report/'consumer-build-run.log').read_text(encoding='utf-8')
            item=json.loads(run('consumer-exit',['docker','inspect',job],log=False))[0]
            assert item['State']['ExitCode']==0 and args.expected_output in output
            assert 'PASS: client bundle integrity; cjpm SHA-256 '+client_manifest['files']['cjpm']['sha256'] in output
            if args.maintenance:
                assert 'CjRepoMesh team 1.0.0: recovered' in output
                assert json.loads((consumer/'cjpm-provenance.json').read_text())==approved
                assert hashlib.sha256(approval.read_bytes()).hexdigest()==approval_sha
            passed('delivered-client-builds-and-runs-from-restored-cache-with-no-upstream',clientSha256=client_manifest['files']['cjpm']['sha256'],expectedOutput=args.expected_output)
            if args.maintenance:
                refused_consumer=report/'drift-consumer';refused_consumer.mkdir()
                shutil.copytree(consumer/'src',refused_consumer/'src')
                for filename in ('cjpm.toml','cangjie-repo.toml'):shutil.copyfile(consumer/filename,refused_consumer/filename)
                drift=report/'approved-drift-source.json'
                drift_value=json.loads(approval.read_text());drift_value['packages'][0]['sha256']='0'*64
                drift.write_text(json.dumps(drift_value));drift_sha=hashlib.sha256(drift.read_bytes()).hexdigest()
                drift_job='cjrepomesh-drift-'+uuid.uuid4().hex
                drift_command=[str(value).replace(job,drift_job).replace(str(consumer),str(refused_consumer)).replace(str(approval),str(drift)) for value in command]
                run('drift-create',drift_command);containers.append(drift_job)
                run('drift-build',['docker','start','--attach',drift_job],success=None,timeout=180)
                drift_state=json.loads(run('drift-exit',['docker','inspect',drift_job],log=False))[0]['State']
                drift_output=(report/'drift-build.log').read_text()
                assert drift_state['ExitCode']!=0 and 'repository source baseline rejected' in drift_output
                assert not (refused_consumer/'cjpm-provenance.json').exists()
                assert not (refused_consumer/'target/release/bin/main').exists()
                assert hashlib.sha256(drift.read_bytes()).hexdigest()==drift_sha
                assert hashlib.sha256(approval.read_bytes()).hexdigest()==approval_sha
                passed('restored-registry-cold-job-rejects-baseline-drift-and-retains-independent-approvals')
            compose('recreate-recovery','up','-d','--force-recreate','--no-build','--pull','never');ready()
            run('recreated-recovery',[sys.executable,'verify.py','--running'])
            assert get(artifact_path,values['CJREPO_READ_TOKEN'])==(200,artifact)
            assert (installation/'.env').read_bytes()==recovered_env
            assert (original_installation/'.env').read_bytes()==(backup_config/'.env').read_bytes()==original_env
            assert hashlib.sha256(backup.read_bytes()).hexdigest()==backup_sha
            assert hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()==original_manifest
            source_tar=report/'original-after.tar';transfer('compare-source',original_project+'_cjrepo-data',source_tar)
            assert archive_manifest(source_tar)==files
            passed('recovered-recreation-retains-state-and-source-backup-remain-unchanged')
    except Exception as failure:error=safe_error(failure,secrets_to_hide);print('FAIL '+error,flush=True)
    finally:
        for name in reversed(containers):
            try:
                if args.maintenance:
                    item=json.loads(run('cleanup-identity-'+name,['docker','inspect',name],log=False))[0]
                    assert (item.get('Config',{}).get('Labels') or {}).get('cjrepomesh.ca-proof')==name
                    run('retained-'+name,['docker','logs',name])
                run('cleanup-'+name,['docker','rm','--force',name])
            except Exception:cleanup.append('fixture container cleanup failed')
        for owned_directory,owned_project in reversed(projects):
            try:
                if args.maintenance:
                    try:
                        run('retained-'+owned_project,['docker','compose','-p',owned_project,'-f',owned_directory/'compose.yaml',
                            '--env-file',owned_directory/'.env','logs','--no-color'],directory=owned_directory)
                    except Exception:cleanup.append('owned Compose log capture failed')
                keep=args.maintenance and (bool(error) or len(stages)!=total or bool(cleanup))
                run('cleanup-'+owned_project,['docker','compose','-p',owned_project,'-f',owned_directory/'compose.yaml',
                  '--env-file',owned_directory/'.env','down',*([] if keep else ['-v']),'--remove-orphans'],directory=owned_directory)
            except Exception:cleanup.append('owned Compose cleanup failed')
        for path in cert.glob('*.key'):
            if args.maintenance and (error or len(stages)!=total):continue
            try:path.chmod(0o600);path.unlink()
            except OSError:cleanup.append('synthetic key cleanup failed')
    summary=dict(success=len(stages)==total and not error and not cleanup,passed=len(stages),total=total,seconds=round(time.monotonic()-started,2),
      image=image,runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),stages=stages,error=error,cleanupErrors=cleanup,
      limits=['Existing Docker engine, standard Compose and same-network-namespace TLS fixture; no cross-host or inbound TLS gateway.',
              'Read-only existing Python/OpenSSL tools; optional recovery consumer uses existing Linux SDK/tools read-only, no image changes or system CA installation.',
              'Owned synthetic installations only; maintenance mode exercises the receiver tool with one approved graph containing a real Hosted organization package and Proxy package; no business cutover, CA rotation, fresh host, Windows Cangjie or complete Maple.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return int(not summary['success'])


if __name__=='__main__':raise SystemExit(main())
