#!/usr/bin/env python3
"""Verify standard Compose CA import and genuine HTTPS proxy/cache behavior."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','package-dir','native','openssl','evidence-dir'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();bundle=args.bundle.resolve();report=args.evidence_dir.resolve()
    if not (args.native/'bin/python3').is_file() or not args.openssl.is_file(): parser.error('existing Linux Python/native tools and OpenSSL are required')
    metadata=json.loads((args.package_dir/'meta-data.json').read_text());name,version=metadata['name'],metadata['version']
    if metadata['organization'] or len(name)<4:parser.error('use an existing default-organization CJP')
    artifact=(args.package_dir/f'{name}-{version}.cjp').read_bytes();artifact_sha=hashlib.sha256(artifact).hexdigest()
    assert artifact_sha==metadata['index']['sha256sum']
    report.mkdir(parents=True,exist_ok=False);installation=report/'installation';shutil.copytree(bundle,installation)
    state=report/'state';state.mkdir();(state/'mode').write_text('wrong');cert=report/'cert';cert.mkdir()
    tools=report/'tools';tools.mkdir();shutil.copyfile(args.openssl,tools/'openssl');(tools/'fixture.py').write_text(FIXTURE)
    environment={k:v for k,v in os.environ.items() if not k.upper().startswith(('CJREPO_','CJREPOMESH_','COMPOSE_'))}
    token=secrets.token_hex(32);secrets_to_hide=[token];project='';containers=[];stages=[];cleanup=[];error='';started=time.monotonic()
    manifest=json.loads((installation/'manifest.json').read_text());image=manifest['image'];opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def run(label,arguments,*,success=True,log=True,timeout=120):
        result=subprocess.run(list(map(str,arguments)),cwd=installation,env=environment,capture_output=True,text=True,timeout=timeout)
        text=result.stdout+result.stderr
        for secret in secrets_to_hide:text=text.replace(secret,'[REDACTED]')
        if log:(report/(label+'.log')).write_text(text,encoding='utf-8')
        assert (result.returncode==0)==success,label+' failed; inspect retained log'
        return result.stdout
    def compose(label,*arguments,**options):return run(label,['docker','compose','-p',project,'-f','compose.yaml','--env-file','.env',*arguments],**options)
    def passed(label,**facts):
        stages.append(dict(name=label,facts=facts));print(f'PASS {len(stages)}/10 {label}',flush=True)
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
    except Exception as failure:error=safe_error(failure,secrets_to_hide);print('FAIL '+error,flush=True)
    finally:
        for name in reversed(containers):
            try:run('cleanup-'+name,['docker','rm','--force',name])
            except Exception:cleanup.append('fixture container cleanup failed')
        if project:
            try:compose('cleanup-service','down','-v','--remove-orphans')
            except Exception:cleanup.append('owned Compose cleanup failed')
        for path in cert.glob('*.key'):
            try:path.chmod(0o600);path.unlink()
            except OSError:cleanup.append('synthetic key cleanup failed')
    summary=dict(success=len(stages)==10 and not error and not cleanup,passed=len(stages),total=10,seconds=round(time.monotonic()-started,2),
      image=image,runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),stages=stages,error=error,cleanupErrors=cleanup,
      limits=['Existing Docker engine, standard Compose and same-network-namespace TLS fixture; no cross-host or inbound TLS gateway.',
              'Read-only existing Python/OpenSSL fixture tools; no SDK, image changes or system CA installation.',
              'New installation only; no in-place CA rotation, fresh host, production trust distribution, Windows Cangjie or complete Maple.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return int(not summary['success'])


if __name__=='__main__':raise SystemExit(main())
