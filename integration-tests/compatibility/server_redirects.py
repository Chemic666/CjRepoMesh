#!/usr/bin/env python3
"""Exercise server outbound redirects using owned loopback fixtures and a real CJP."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import ManagedProcesses


def sha(data):
    return hashlib.sha256(data).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--package-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    args = parser.parse_args()
    if os.name == 'nt':
        parser.error('Windows native execution is paused; use the existing Linux validation environment')
    server = args.server.resolve()
    metadata = json.loads((args.package_dir/'meta-data.json').read_text())
    name, version = metadata['name'], metadata['version']
    if metadata['organization'] or len(name) < 4:
        parser.error('use an existing default-organization fixture with a name of at least four characters')
    artifact = (args.package_dir/f'{name}-{version}.cjp').read_bytes()
    assert sha(artifact) == metadata['index']['sha256sum']
    index = json.dumps(metadata['index']).encode()+b'\n'
    index_path, artifact_path = f'/index/{name[:2]}/{name[2:4]}/{name}', f'/pkg/{name}/{version}'
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    results = []
    started = time.monotonic()

    def get(url, token=''):
        request = urllib.request.Request(url, headers={'Authorization': token} if token else {})
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def files(folder):
        return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in folder.rglob('*') if p.is_file()}

    def real_frame(body):
        try:
            size = struct.unpack_from('<I', body, 1)[0]
            value = json.loads(body[5:5+size])
            offset = 5+size
            length = struct.unpack_from('<I', body, offset+1)[0]
            return (body[0] == body[offset] == 1 and body[offset+5:] == artifact and length == len(artifact)
                    and value['name'] == name and value['version'] == version
                    and value['index']['sha256sum'] == sha(artifact))
        except (ValueError, IndexError, KeyError, struct.error):
            return False

    class Fixture:
        def __init__(self, redirects=None, destination=False):
            self.requests = []
            self.redirects = redirects or {}
            fixture = self
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.handle_request()
                def do_POST(self):
                    self.handle_request()
                def handle_request(self):
                    body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    expected = ('fixture-publish' if self.command == 'POST' else 'fixture-read') if destination else 'fixture-source'
                    fixture.requests.append(dict(method=self.command, path=self.path,
                        authorizationPresent=bool(self.headers.get('Authorization')),
                        expectedAuthorization=self.headers.get('Authorization') == expected,
                        bodyBytes=len(body), bodySha256=sha(body) if body else None,
                        realPublishFrame=real_frame(body) if body else False))
                    redirect = fixture.redirects.get((self.command, self.path))
                    existing = any(method == 'GET' for method, path in fixture.redirects)
                    status = redirect[0] if redirect else 404 if destination and self.path == index_path and not existing else 200
                    self.send_response(status)
                    if redirect: self.send_header('Location', redirect[1])
                    self.end_headers()
                    self.wfile.write(index if self.path == index_path else artifact if self.path == artifact_path else b'{"ok":true}')
                def log_message(self, *args):
                    pass
            self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.http.daemon_threads = True
            self.base = f'http://127.0.0.1:{self.http.server_port}'
            self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
            self.thread.start()
        def close(self):
            self.http.shutdown()
            self.thread.join(timeout=3)
            self.http.server_close()

    cases = [('proxy', m) for m in ('direct', 'source-index', 'source-artifact')]
    cases += [('mirror', m) for m in ('direct', 'source-index', 'source-artifact')]
    cases += [('sync', m) for m in ('direct', 'source-index', 'source-artifact', 'destination-index', 'destination-artifact', 'publish')]
    for command, mode in cases:
        label = command+'-'+mode
        folder = report/label
        folder.mkdir()
        storage = folder/'storage'
        storage.mkdir()
        target, source, destination = Fixture(), None, None
        facts = dict(command=command, mode=mode)
        passed, error = False, ''
        try:
            source_redirects, destination_redirects = {}, {}
            selected = index_path if mode.endswith('index') else artifact_path
            status = 302 if mode.endswith('index') else 307
            if mode.startswith('source-'): source_redirects[('GET', selected)] = (status, target.base+selected)
            if mode.startswith('destination-'): destination_redirects[('GET', selected)] = (status, target.base+selected)
            if mode == 'publish': destination_redirects[('POST', '/pkg/'+name)] = (307, target.base+'/pkg/'+name)
            source = Fixture(source_redirects)
            destination = Fixture(destination_redirects, destination=True)
            env = dict(environment, CJREPO_STORAGE=str(storage), CJREPO_UPSTREAM_TOKEN='fixture-source',
                CJREPO_SYNC_DESTINATION_TOKEN='fixture-publish', CJREPO_SYNC_DESTINATION_READ_TOKEN='fixture-read')
            if command == 'proxy':
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
                env.update(CJREPO_ADDRESS='127.0.0.1', CJREPO_PORT=str(port), CJREPO_UPSTREAM=source.base,
                           CJREPO_READ_TOKEN='fixture-local-read', CJREPO_PUBLISH_TOKEN='fixture-local-publish')
                with ManagedProcesses() as processes:
                    process = processes.start((server,), cwd=folder, env=env, output_path=folder/'server.log')
                    for _ in range(50):
                        try:
                            if get(f'http://127.0.0.1:{port}/health')[0] == 200: break
                        except OSError: pass
                        if process.poll() is not None: raise AssertionError('owned proxy stopped before ready')
                        time.sleep(.1)
                    else: raise AssertionError('owned proxy readiness timeout')
                    code, body = get(f'http://127.0.0.1:{port}'+index_path, 'fixture-local-read')
                    facts['indexStatus'] = code
                    if mode != 'source-index':
                        assert code == 200 and json.loads(body)['sha256sum'] == sha(artifact)
                        before = files(storage)
                        code, body = get(f'http://127.0.0.1:{port}'+artifact_path, 'fixture-local-read')
                        facts['artifactStatus'] = code
                        if mode == 'direct': assert code == 200 and body == artifact
                        else: assert code == status and files(storage) == before
                    else: assert code == status and not files(storage)
            else:
                arguments = [str(server), command, source.base]
                if command == 'sync': arguments.append(destination.base)
                arguments += [name, version]
                result = subprocess.run(arguments, cwd=folder, env=env, capture_output=True, text=True, timeout=30)
                output = result.stdout+result.stderr
                (folder/'command.log').write_text(output)
                facts['exitCode'] = result.returncode
                if mode == 'direct':
                    assert result.returncode == 0 and 'result=SYNCED' in output
                    if command == 'mirror': assert any(p.endswith('.cjp') and digest == sha(artifact) for p, digest in files(storage).items())
                    else: assert any(r['method'] == 'POST' and r['realPublishFrame'] for r in destination.requests)
                else:
                    assert result.returncode != 0 and f'status {status}' in output
                    assert 'result=SYNCED' not in output and 'result=SKIP' not in output and not files(storage)
            assert not target.requests, 'redirect target was contacted'
            assert source.requests and all(r['expectedAuthorization'] for r in source.requests)
            if mode == 'source-artifact': assert any(r['path'] == artifact_path for r in source.requests)
            if mode.startswith('destination-'): assert any(r['path'] == selected for r in destination.requests)
            if mode == 'publish': assert any(r['method'] == 'POST' and r['realPublishFrame'] for r in destination.requests)
            assert all(r['expectedAuthorization'] for r in destination.requests)
            passed = True
        except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as failure:
            error = str(failure) or type(failure).__name__
        finally:
            facts.update(sourceRequests=source.requests if source else [], destinationRequests=destination.requests if destination else [],
                         redirectTargetRequests=target.requests, storage=files(storage))
            for fixture in (destination, source, target):
                if fixture: fixture.close()
        results.append(dict(name=label, passed=passed, error=error, facts=facts))
        print(('PASS ' if passed else 'FAIL ')+label+(' '+error if error else ''), flush=True)
    success = all(r['passed'] for r in results)
    summary = dict(success=success, passed=sum(r['passed'] for r in results), total=len(results),
        seconds=round(time.monotonic()-started, 2), serverSha256=sha(server.read_bytes()),
        realArtifactSha256=sha(artifact), runnerSha256=sha(Path(__file__).read_bytes()), cases=results,
        limits=['Owned HTTP loopback fixtures; no TLS or cross-host acceptance.',
                'Sync publication is checked as a real frame at a protocol fixture; core suites cover actual destination storage.',
                'Default organization only; no Windows Cangjie execution.'])
    (report/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(f'Server redirects: {summary["passed"]}/{len(results)}; success={success}', flush=True)
    return int(not success)


if __name__ == '__main__':
    raise SystemExit(main())
