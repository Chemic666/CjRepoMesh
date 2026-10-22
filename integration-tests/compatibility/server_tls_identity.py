#!/usr/bin/env python3
"""Exercise real server HTTPS upstreams with owned certificates and a genuine CJP."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix': parser.error('use the existing Linux SDK; Windows Cangjie execution is paused')
    server = args.server.resolve()
    metadata = json.loads((args.package_dir/'meta-data.json').read_text())
    name, version = metadata['name'], metadata['version']
    if metadata['organization'] or len(name) < 4: parser.error('use an existing default-organization CJP')
    artifact = (args.package_dir/f'{name}-{version}.cjp').read_bytes()
    assert digest(artifact) == metadata['index']['sha256sum']
    index = json.dumps(metadata['index']).encode()+b'\n'
    index_path, artifact_path = f'/index/{name[:2]}/{name[2:4]}/{name}', f'/pkg/{name}/{version}'
    report = args.evidence_dir.resolve(); report.mkdir(parents=True, exist_ok=False)
    environment = {k:v for k,v in os.environ.items() if k.upper() not in ('SSL_CERT_FILE','SSL_CERT_DIR')
                   and not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    source_token, read_token, publish_token = [secrets.token_hex(32) for _ in range(3)]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results=[]; started=time.monotonic()

    def clean(output):
        for token in (source_token, read_token, publish_token): output=output.replace(token,'[REDACTED]')
        return output

    def files(folder):
        return {p.relative_to(folder).as_posix():digest(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}

    def frame_valid(body):
        try:
            size=struct.unpack_from('<I',body,1)[0]; value=json.loads(body[5:5+size]); offset=5+size
            length=struct.unpack_from('<I',body,offset+1)[0]
            return (body[0] == body[offset] == 1 and length == len(artifact) and body[offset+5:] == artifact
                    and value['name'] == name and value['version'] == version and value['organization'] == ''
                    and value['index']['sha256sum'] == digest(artifact))
        except (ValueError, IndexError, KeyError, struct.error): return False

    def get(url):
        try:
            with opener.open(url,timeout=10) as response: return response.status,response.read()
        except urllib.error.HTTPError as error:
            with error: return error.code,error.read()

    with tempfile.TemporaryDirectory(prefix='cjrepomesh-server-tls-') as temporary:
        cert=Path(temporary); cert.chmod(0o700)
        def openssl(*arguments):
            result=subprocess.run(['openssl',*arguments],cwd=cert,capture_output=True,timeout=30)
            assert result.returncode == 0,'synthetic certificate generation failed'
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-subj','/CN=CjRepoMesh synthetic CA',
                '-days','1','-keyout','ca.key','-out','ca.pem','-addext','basicConstraints=critical,CA:TRUE')
        for number,(label,san) in enumerate((('good','DNS:localhost,IP:127.0.0.1'),
                ('wrongip','IP:127.0.0.2'),('wrongdns','DNS:wrong.invalid'),
                ('clientonly','DNS:localhost,IP:127.0.0.1'),('expired','DNS:localhost,IP:127.0.0.1')),1):
            openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',label+'.key','-out',label+'.csr')
            (cert/(label+'.ext')).write_text('subjectAltName='+san+'\nextendedKeyUsage='+
                ('clientAuth' if label == 'clientonly' else 'serverAuth')+'\n')
            openssl('x509','-req','-in',label+'.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial',str(number),
                    '-days','-1' if label == 'expired' else '1','-extfile',label+'.ext','-out',label+'.pem')
        for key in cert.glob('*.key'): key.chmod(0o600)
        (cert/'empty-ca').mkdir()
        # Prove the negative fixture differs in validity, not trust/name/purpose.
        openssl('verify','-CAfile','ca.pem','-purpose','sslserver','good.pem')
        expiry=subprocess.run(['openssl','verify','-CAfile','ca.pem','-purpose','sslserver','expired.pem'],
            cwd=cert,capture_output=True,timeout=30)
        assert expiry.returncode != 0 and b'error 10 at 0 depth' in expiry.stdout+expiry.stderr,'expired leaf fixture was not validated'

        class Fixture:
            def __init__(self, certificate='good', *, destination=False, existing=False, flip=None, dns=False):
                self.requests=[]; self.handshakes=[]; self.handshake_changed=threading.Condition(); fixture=self
                self.context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                self.context.minimum_version=ssl.TLSVersion.TLSv1_2
                self.context.load_cert_chain(cert/(certificate+'.pem'),cert/(certificate+'.key'))
                class Handler(BaseHTTPRequestHandler):
                    def handle_registry(self):
                        body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                        wanted=(publish_token if self.command == 'POST' else read_token) if destination else source_token
                        authorized=self.headers.get('Authorization') == wanted
                        status=401 if not authorized else 404 if destination and not existing and self.path == index_path else 200
                        fixture.requests.append(dict(method=self.command,path=self.path,authorized=authorized,
                            status=status,tls=self.connection.version(),realPublishFrame=frame_valid(body) if body else False))
                        if flip and self.path == index_path:
                            fixture.context.load_cert_chain(cert/(flip+'.pem'),cert/(flip+'.key'))
                        payload=index if self.path == index_path else artifact if self.path == artifact_path else b'{}'
                        self.send_response(status); self.send_header('Content-Length',str(len(payload)))
                        self.send_header('Connection','close'); self.end_headers(); self.wfile.write(payload)
                        self.close_connection=True
                    do_GET=do_POST=handle_registry
                    def log_message(self,*args): pass
                class HttpsServer(ThreadingHTTPServer):
                    daemon_threads=True
                    def get_request(self):
                        raw,address=super().get_request();raw.settimeout(5)
                        event=dict(status='attempted')
                        with fixture.handshake_changed:fixture.handshakes.append(event)
                        try:
                            connection=fixture.context.wrap_socket(raw,server_side=True)
                        except OSError as failure:
                            with fixture.handshake_changed:
                                event.update(status='failed',reason=getattr(failure,'reason',type(failure).__name__))
                                fixture.handshake_changed.notify_all()
                            raw.close();raise
                        with fixture.handshake_changed:
                            event.update(status='succeeded',tls=connection.version())
                            fixture.handshake_changed.notify_all()
                        return connection,address
                self.http=HttpsServer(('127.0.0.1',0),Handler)
                self.base=f'https://{"localhost" if dns else "127.0.0.1"}:{self.http.server_port}'
                self.thread=threading.Thread(target=self.http.serve_forever,daemon=True); self.thread.start()
            def close(self):
                self.http.shutdown(); self.thread.join(timeout=3); self.http.server_close()

        cases=[('mirror',mode) for mode in ('trusted-ip','trusted-dns','untrusted-ca','wrong-ip','wrong-dns','client-only','source-artifact')]
        cases += [('proxy',mode) for mode in ('trusted-ip','wrong-ip','source-artifact')]
        cases += [('sync',mode) for mode in ('trusted-ip','trusted-dns','source-index','source-artifact','destination-index','destination-artifact','publish-ip','publish-dns')]
        cases += [('mirror','expired-ip'),('mirror','expired-dns'),('proxy','expired-ip'),
                  ('sync','expired-source-artifact'),('sync','expired-destination-index'),('sync','expired-publish')]
        for operation,mode in cases:
            label=operation+'-'+mode; folder=report/label; folder.mkdir(); (folder/'home').mkdir()
            storage=folder/'storage'; storage.mkdir(); source=destination=None; facts={}; passed=False; error=''
            try:
                dns=mode in ('trusted-dns','wrong-dns','publish-dns','expired-dns')
                certificate={'wrong-ip':'wrongip','wrong-dns':'wrongdns','client-only':'clientonly','source-index':'wrongip',
                    'expired-ip':'expired','expired-dns':'expired'}.get(mode,'good')
                source=Fixture(certificate,flip='expired' if mode == 'expired-source-artifact' else
                    'wrongip' if mode == 'source-artifact' else None,dns=dns)
                destination=Fixture('expired' if mode == 'expired-destination-index' else
                    'wrongip' if mode == 'destination-index' else 'good',destination=True,
                    existing=mode == 'destination-artifact',flip='expired' if mode == 'expired-publish' else
                    'wrongdns' if mode == 'publish-dns' else
                    'wrongip' if mode in ('destination-artifact','publish-ip') else None,dns=dns)
                env=dict(environment,HOME=str(folder/'home'),USERPROFILE=str(folder/'home'),CJREPO_STORAGE=str(storage),
                    CJREPO_UPSTREAM_TOKEN=source_token,CJREPO_SYNC_DESTINATION_TOKEN=publish_token,
                    CJREPO_SYNC_DESTINATION_READ_TOKEN=read_token,CJREPO_CONNECT_TIMEOUT_SECONDS='2',
                    SSL_CERT_DIR=str(cert/'empty-ca'),SSL_CERT_FILE=str(cert/('missing.pem' if mode == 'untrusted-ca' else 'ca.pem')))
                good=mode.startswith('trusted-')
                if operation == 'proxy':
                    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
                    env.update(CJREPO_ADDRESS='127.0.0.1',CJREPO_PORT=str(port),CJREPO_UPSTREAM=source.base)
                    with ManagedProcesses() as processes:
                        process=processes.start((server,),cwd=folder,env=env,output_path=folder/'server.log')
                        for _ in range(50):
                            try:
                                if get(f'http://127.0.0.1:{port}/health')[0] == 200: break
                            except OSError: pass
                            assert process.poll() is None,'proxy stopped before ready'
                            time.sleep(.1)
                        else: raise AssertionError('proxy not ready')
                        code,body=get(f'http://127.0.0.1:{port}'+index_path); facts['indexStatus']=code
                        if good or mode == 'source-artifact':
                            assert code == 200 and json.loads(body)['sha256sum'] == digest(artifact)
                            before=files(storage)
                            code,body=get(f'http://127.0.0.1:{port}'+artifact_path); facts['artifactStatus']=code
                            if good: assert code == 200 and body == artifact
                            else: assert code == 502 and files(storage) == before
                        else: assert code == 502 and not files(storage)
                else:
                    arguments=[str(server),operation,source.base]
                    if operation == 'sync': arguments.append(destination.base)
                    result=subprocess.run(arguments+[name,version],cwd=folder,env=env,capture_output=True,text=True,timeout=30)
                    output=clean(result.stdout+result.stderr); (folder/'command.log').write_text(output)
                    facts.update(exitCode=result.returncode,tlsNotConfigured='TLS must be configured' in output)
                    if good:
                        assert result.returncode == 0 and 'result=SYNCED' in output
                        if operation == 'mirror': assert any(n.endswith('.cjp') and h == digest(artifact) for n,h in files(storage).items())
                        else: assert any(r['method'] == 'POST' and r['realPublishFrame'] for r in destination.requests)
                    else: assert result.returncode != 0 and 'result=SYNCED' not in output and not files(storage)
                wanted_source=([index_path,artifact_path] if good or mode.startswith('publish-') or mode == 'expired-publish'
                    else [index_path] if mode in ('source-artifact','destination-index','destination-artifact',
                    'expired-source-artifact','expired-destination-index') else [])
                wanted_destination=([index_path,'/pkg/'+name] if good else [index_path] if mode in
                    ('source-artifact','destination-artifact','publish-ip','publish-dns','expired-source-artifact','expired-publish')
                    else []) if operation == 'sync' else []
                assert [r['path'] for r in source.requests] == wanted_source,'source HTTP stage mismatch'
                assert [r['path'] for r in destination.requests] == wanted_destination,'destination HTTP stage mismatch'
                assert all(r['authorized'] and r['tls'] for r in source.requests+destination.requests)
                if mode.startswith('expired-'):
                    target=destination if mode in ('expired-destination-index','expired-publish') else source
                    with target.handshake_changed:
                        observed=target.handshake_changed.wait_for(lambda:any(
                            h.get('status') == 'failed' and h.get('reason') in
                            ('SSLV3_ALERT_CERTIFICATE_EXPIRED','TLSV1_ALERT_CERTIFICATE_EXPIRED')
                            for h in target.handshakes),timeout=2)
                    assert observed,'target connection did not report a certificate-expired TLS alert'
                    facts['expiredTlsAlertObserved']=True
                passed=True
            except (AssertionError,OSError,ValueError,subprocess.SubprocessError) as failure:
                error=str(failure) or type(failure).__name__
            finally:
                facts.update(sourceRequests=source.requests if source else [],destinationRequests=destination.requests if destination else [],storage=files(storage))
                facts.update(sourceHandshakes=source.handshakes if source else [],destinationHandshakes=destination.handshakes if destination else [])
                for fixture in (destination,source):
                    if fixture: fixture.close()
                if (folder/'server.log').exists(): (folder/'server.log').write_text(clean((folder/'server.log').read_text()))
            results.append(dict(name=label,passed=passed,error=error,facts=facts))
            print(('PASS ' if passed else 'FAIL ')+label+(' '+error if error else ''),flush=True)
    summary=dict(success=all(r['passed'] for r in results),passed=sum(r['passed'] for r in results),total=len(results),
        seconds=round(time.monotonic()-started,2),serverSha256=digest(server.read_bytes()),runnerSha256=digest(Path(__file__).read_bytes()),
        realArtifactSha256=digest(artifact),cases=results,limits=[
            'Owned localhost/IPv4 HTTPS protocol fixtures; process-only CA, temporary keys removed; no OS trust changes.',
            'Successful Sync POST validates the real frame, not fixture persistence; core Sync covers genuine destination storage.',
            'Expired leaf fixtures are checked by OpenSSL; no future-validity, expired-root, revocation or clock-change acceptance.',
            'No production gateway, cross-host, IPv6, mTLS, Windows Cangjie or complete Maple acceptance.'])
    (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(f'Server HTTPS identity: {summary["passed"]}/{len(results)}; success={summary["success"]}',flush=True)
    return int(not summary['success'])


if __name__ == '__main__': raise SystemExit(main())
