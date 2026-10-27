#!/usr/bin/env python3
"""Owned loopback acceptance for stopped token and staged public-CA replacement.

This is a rehearsal using synthetic credentials/PKI, not production rotation,
hot reload, physical-host networking, or an automatic rotation utility.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS))
from lib.harness import ManagedProcesses, publish_frame, remove_within, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cjpm', required=True, type=Path)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--portable-bundle', type=Path,
                        help='optional actual verified new server bundle; exercise its offline rotation CLI')
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('use the existing Linux SDK; do not run Windows Cangjie')
    client, server, report = args.cjpm.resolve(), args.server.resolve(), args.evidence_dir.resolve()
    if not client.is_file() or not server.is_file():
        parser.error('existing client and server binaries are required')
    report.mkdir(parents=True, exist_ok=False)
    root = TESTS/'.tmp'/('credential-rotation-'+uuid.uuid4().hex)
    root.mkdir(parents=True, mode=0o700)
    cert = root/'certificates'; cert.mkdir(mode=0o700)
    empty = cert/'empty'; empty.mkdir()
    old_read, old_publish, new_read, new_publish = [secrets.token_hex(32) for _ in range(4)]
    private_values = (old_read, old_publish, new_read, new_publish)
    base = {k: v for k, v in os.environ.items() if k.upper() not in
            {'CJPM_CONFIG', 'SSL_CERT_FILE', 'SSL_CERT_DIR'} and
            not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    cases, cleanup, error = [], [], ''
    gateway = None; gateway_thread = None
    processes = ManagedProcesses()
    storage = root/'storage'
    started = time.monotonic()

    def sanitize(text):
        for value in private_values:
            text = text.replace(value, '[REDACTED]')
        return text

    def command(label, job, arguments, *, token='', trust=None):
        home = job/'.home'; home.mkdir(exist_ok=True)
        env = dict(base, HOME=str(home), USERPROFILE=str(home),
                   ROTATION_TEST_TOKEN=token, SSL_CERT_DIR=str(empty))
        if trust is not None:
            env['SSL_CERT_FILE'] = str(trust)
        result = subprocess.run([str(client), *arguments], cwd=job, env=env,
                                capture_output=True, text=True, timeout=120)
        output = sanitize(result.stdout+result.stderr)
        (report/(label+'.log')).write_text(output, encoding='utf-8')
        return result.returncode, output

    def case(name, action):
        facts = action()
        assert all(facts.values()), name+': '+repr(facts)
        cases.append(dict(name=name, passed=True, facts=facts))
        print('PASS '+name, flush=True)

    def request(port, method, path, token, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={'Authorization': token})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def start_server(label, read, publish, port=None):
        if port is None:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        job = root/label; job.mkdir()
        env = dict(base, HOME=str(job), USERPROFILE=str(job), CJREPO_ADDRESS='127.0.0.1',
                   CJREPO_PORT=str(port), CJREPO_STORAGE=str(storage),
                   CJREPO_READ_TOKEN=read, CJREPO_PUBLISH_TOKEN=publish)
        process = processes.start([server], cwd=job, env=env, output_path=report/(label+'.log'))
        for _ in range(200):
            if process.poll() is not None:
                break
            try:
                if request(port, 'GET', '/health', '')[0] == 200:
                    return process, port
            except OSError:
                pass
            time.sleep(.02)
        raise AssertionError('owned server did not become healthy')

    def storage_state():
        return {p.relative_to(storage).as_posix(): sha256(p)
                for p in storage.rglob('*') if p.is_file()}

    try:
        if args.portable_bundle is not None:
            deployment = root/'portable-deployment'
            shutil.copytree(args.portable_bundle.resolve(), deployment)
            assert not (deployment/'.env').exists() and not (deployment/'trust').exists()
            (deployment/'trust').mkdir()
            configuration = ('COMPOSE_PROJECT_NAME=cjrepomesh-'+secrets.token_hex(8)+'\n'
                'CJREPO_HOST_PORT=18080\nCJREPO_READ_TOKEN='+old_read+'\n'
                'CJREPO_PUBLISH_TOKEN='+old_publish+'\nCJREPO_CA_SHA256=\n').encode()
            (deployment/'.env').write_bytes(configuration); (deployment/'.env').chmod(0o600)
            prepared = root/'rotation-candidate'
            for label, arguments in (
                ('prepare-rotation', ['prepare-rotation', '--rotate-tokens', '--output', str(prepared)]),
                ('verify-rotation', ['verify-rotation', '--prepared', str(prepared)])):
                result = subprocess.run([sys.executable, '-B', str(deployment/'maintenance.py'), *arguments],
                    cwd=deployment, env=base, capture_output=True, text=True, timeout=60)
                (report/(label+'.log')).write_text(sanitize(result.stdout+result.stderr), encoding='utf-8')
                assert result.returncode == 0, 'actual bundled offline rotation CLI did not pass'
                receipt = json.loads(result.stdout)
                assert receipt['runtimeApplied'] is False and receipt['deploymentModified'] is False
            values = dict(line.split('=', 1) for line in (prepared/'.env').read_text().splitlines())
            new_read, new_publish = values['CJREPO_READ_TOKEN'], values['CJREPO_PUBLISH_TOKEN']
            private_values += (new_read, new_publish)
            case('actual-bundle-offline-rotation-preparation', lambda: dict(
                source_unchanged=(deployment/'.env').read_bytes() == configuration,
                distinct_fresh_tokens=len({old_read, old_publish, new_read, new_publish}) == 4,
                image_matches_server=json.loads((deployment/'manifest.json').read_text())['image']['serverSha256'] == sha256(server)))
        publisher = root/'publisher'; publisher.mkdir()
        source = TESTS.parent/'examples/team/publisher'
        shutil.copyfile(source/'cjpm.toml', publisher/'cjpm.toml')
        shutil.copytree(source/'src', publisher/'src')
        (publisher/'README.md').write_text('Owned synthetic credential/CA replacement rehearsal package.\n')
        (publisher/'cangjie-repo.toml').write_text('[repository.cache]\npath="cache"\n')
        code, _ = command('bundle', publisher, ['bundle'])
        assert code == 0, 'real synthetic team package did not bundle'
        metadata = json.loads((publisher/'target/meta-data.json').read_text())
        artifact = (publisher/'target/teamhello-1.0.0.cjp').read_bytes()
        assert hashlib.sha256(artifact).hexdigest() == metadata['index']['sha256sum']
        frame = publish_frame(json.dumps(metadata).encode(), artifact)
        index_path = '/index/te/am/teamhello?organization=company'
        artifact_path = '/pkg/teamhello/1.0.0?organization=company'
        publish_path = '/pkg/teamhello?organization=company'
        process, port = start_server('old-server', old_read, old_publish)
        case('initial-publish', lambda: dict(published=request(port, 'POST', publish_path, old_publish, frame)[0] == 200))
        before = storage_state()
        case('roles-remain-separated', lambda: dict(
            read_cannot_publish=request(port, 'POST', publish_path, old_read, frame)[0] == 401,
            publish_cannot_read=request(port, 'GET', index_path, old_publish)[0] == 401,
            unchanged=storage_state() == before))
        processes.stop(process)
        process, port = start_server('new-server', new_read, new_publish, port)
        case('retired-tokens-rejected-after-restart', lambda: dict(
            old_read_rejected=request(port, 'GET', index_path, old_read)[0] == 401,
            old_publish_rejected=request(port, 'POST', publish_path, old_publish, frame)[0] == 401,
            unchanged=storage_state() == before))
        case('new-tokens-and-storage-retained', lambda: dict(
            new_read_works=request(port, 'GET', artifact_path, new_read) == (200, artifact),
            new_publish_authenticated=request(port, 'POST', publish_path, new_publish, frame)[0] == 409,
            unchanged=storage_state() == before))

        def openssl(*arguments):
            result = subprocess.run(['openssl', *arguments], cwd=cert, capture_output=True, timeout=30)
            assert result.returncode == 0, 'synthetic certificate generation/verification failed'

        for number, name in enumerate(('old', 'new'), 1):
            openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-subj',
                    '/CN=CjRepoMesh synthetic '+name+' CA', '-days', '1',
                    '-keyout', name+'-ca.key', '-out', name+'-ca.pem',
                    '-addext', 'basicConstraints=critical,CA:TRUE')
            openssl('req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
                    '-keyout', name+'.key', '-out', name+'.csr')
            (cert/(name+'.ext')).write_text('subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n')
            openssl('x509', '-req', '-in', name+'.csr', '-CA', name+'-ca.pem',
                    '-CAkey', name+'-ca.key', '-set_serial', str(number), '-days', '1',
                    '-extfile', name+'.ext', '-out', name+'.pem')
            openssl('verify', '-CAfile', name+'-ca.pem', '-purpose', 'sslserver', name+'.pem')
        for key in cert.glob('*.key'):
            key.chmod(0o600)
        (cert/'bridge.pem').write_bytes((cert/'old-ca.pem').read_bytes()+(cert/'new-ca.pem').read_bytes())
        observations = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                status, data = request(port, 'GET', self.path, self.headers.get('Authorization', ''))
                observations.append(dict(status=status, tls=self.connection.version()))
                self.send_response(status); self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)

        gateway = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert/'old.pem', cert/'old.key')
        gateway.socket = context.wrap_socket(gateway.socket, server_side=True)
        gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True); gateway_thread.start()
        url = 'https://127.0.0.1:'+str(gateway.server_port)

        def client_case(label, trust, succeeds, operation='doctor', token=None):
            job = root/label; job.mkdir()
            template = TESTS.parent/'examples/team/consumer'
            shutil.copyfile(template/'cjpm.toml', job/'cjpm.toml')
            shutil.copytree(template/'src', job/'src')
            (job/'cangjie-repo.toml').write_text('[repository.cache]\npath="cache"\n'
                '[repository.internal]\nregistry='+json.dumps(url)+'\ntoken-env="ROTATION_TEST_TOKEN"\n'
                '[[route]]\nnamespace="company::*"\nregistry="internal"\nexclusive=true\n')
            observations.clear()
            arguments = ['repo', 'doctor', 'company::teamhello'] if operation == 'doctor' else ['run']
            code, output = command(label, job, arguments, token=token or new_read, trust=cert/trust)
            facts = dict(exit_matches=(code == 0) == succeeds)
            if succeeds:
                facts['verified_https_reached_server'] = bool(observations) and all(r['tls'] and r['status'] == 200 for r in observations)
                if operation == 'run':
                    facts['real_cold_build'] = 'CjRepoMesh team 1.0.0: CI' in output
                    facts['source_digest'] = json.loads((job/'cjpm-provenance.json').read_text())['packages'][0]['sha256'] == metadata['index']['sha256sum']
            else:
                facts['zero_http_after_tls_rejection'] = not observations
                facts['no_success_provenance'] = not (job/'cjpm-provenance.json').exists()
            return facts

        case('old-ca-and-old-leaf', lambda: client_case('old-ca-and-old-leaf', 'old-ca.pem', True))
        case('new-ca-does-not-trust-old-leaf', lambda: client_case('new-ca-does-not-trust-old-leaf', 'new-ca.pem', False))
        case('overlap-trust-old-leaf', lambda: client_case('overlap-trust-old-leaf', 'bridge.pem', True))
        context.load_cert_chain(cert/'new.pem', cert/'new.key')
        case('overlap-trust-new-leaf', lambda: client_case('overlap-trust-new-leaf', 'bridge.pem', True))
        case('retired-ca-does-not-trust-new-leaf', lambda: client_case('retired-ca-does-not-trust-new-leaf', 'old-ca.pem', False))
        case('new-ca-real-cold-build', lambda: client_case('new-ca-real-cold-build', 'new-ca.pem', True, 'run'))
        case('rotation-kept-storage-bytes', lambda: dict(unchanged=storage_state() == before))
    except Exception as failure:
        error = sanitize(type(failure).__name__+': '+str(failure))
        print('FAIL '+error, flush=True)
    finally:
        if gateway is not None:
            gateway.shutdown(); gateway.server_close()
        if gateway_thread is not None:
            gateway_thread.join(timeout=3)
            if gateway_thread.is_alive(): cleanup.append('owned gateway thread did not stop')
        try: processes.close()
        except Exception: cleanup.append('owned server cleanup failed')
        for path in report.glob('*.log'):
            path.write_text(sanitize(path.read_text(errors='replace')), encoding='utf-8')
        expected = 12 if args.portable_bundle is not None else 11
        success = not error and not cleanup and len(cases) == expected
        summary = dict(success=success, cases=cases, expectedCases=expected, error=error, cleanupErrors=cleanup,
            durationSeconds=round(time.monotonic()-started, 2), clientSha256=sha256(client),
            serverSha256=sha256(server), runnerSha256=sha256(Path(__file__)),
            scope='owned loopback TLS gateway, stopped token replacement, synthetic CA overlap; not production or cross-physical-host acceptance')
        (report/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
        if success: remove_within(root, (TESTS/'.tmp',))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
