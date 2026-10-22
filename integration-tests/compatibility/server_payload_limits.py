#!/usr/bin/env python3
"""Exercise byte limits with real HTTP bodies and owned Linux server processes."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import copy
import hashlib
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.harness import publish_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('server', 'package-dir', 'evidence-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Windows Cangjie execution is paused')
    server = args.server.resolve()
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    meta = json.loads((args.package_dir / 'meta-data.json').read_text())
    assert meta['name'] == 'meshdep' and not meta['organization']
    artifact = (args.package_dir / ('meshdep-' + meta['version'] + '.cjp')).read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == meta['index']['sha256sum']
    frame = publish_frame(json.dumps(meta).encode(), artifact)
    token = secrets.token_hex(32)
    base = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
    cases = []
    started = time.monotonic()

    def request(port, path, body=None, *, authorized=True, chunked=False):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        headers = {'Authorization': token} if authorized else {}
        try:
            data = iter([body]) if chunked else body
            connection.request('POST' if body is not None else 'GET', path, body=data,
                headers=headers, encode_chunked=chunked)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    @contextmanager
    def owned(label, config=None, upstream=''):
        folder = report / label
        folder.mkdir()
        storage = folder / 'storage'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        env = dict(base, HOME=str(folder), USERPROFILE=str(folder), CJREPO_ADDRESS='127.0.0.1',
            CJREPO_PORT=str(port), CJREPO_STORAGE=str(storage), CJREPO_PUBLISH_TOKEN=token,
            CJREPO_READ_TOKEN=token, CJREPO_UPSTREAM=upstream)
        env.update(config or {})
        process = subprocess.Popen([str(server)], cwd=folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        ready = False
        try:
            for attempt in range(100):
                if process.poll() is not None:
                    break
                try:
                    ready = request(port, '/health')[0] == 200
                    if ready:
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            yield port, storage, process, ready
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                output = process.communicate(timeout=3)[0].decode(errors='replace')
            except subprocess.TimeoutExpired:
                process.kill()
                output = process.communicate(timeout=3)[0].decode(errors='replace')
            process.rawPrivateValueHidden = not any(value.startswith('synthetic-') and value in output for value in (config or {}).values())
            output = output.replace(token, '[REDACTED]')
            for value in (config or {}).values():
                if value.startswith('synthetic-'):
                    output = output.replace(value, '[REDACTED]')
            (folder / 'server.log').write_text(output)

    def case(label, function):
        error = ''
        try:
            function()
        except Exception as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        cases.append(dict(name=label, passed=not error, error=error))
        print(('PASS ' if not error else 'FAIL ') + label, flush=True)

    for variable, maximum in (('CJREPO_MAX_ARTIFACT_BYTES', 1073741824), ('CJREPO_MAX_INDEX_BYTES', 67108864)):
        for label, raw in (('empty', ''), ('zero', '0'), ('negative', '-1'), ('text', 'synthetic-private-' + secrets.token_hex(8)), ('too-large', str(maximum + 1))):
            name = variable.lower() + '-' + label
            def invalid(name=name, variable=variable, raw=raw):
                with owned(name, {variable: raw}) as (_, _, process, ready):
                    assert not ready and process.poll() == 2, 'invalid configuration must exit 2 before serving'
                text = (report / name / 'server.log').read_text()
                assert variable in text and process.rawPrivateValueHidden
            case(name, invalid)

    def publication(label, body, expected, *, chunked=False, authorized=True, config=None):
        with owned(label, config or {'CJREPO_MAX_ARTIFACT_BYTES': str(len(artifact))}) as (port, storage, _, ready):
            assert ready
            assert request(port, '/pkg/meshdep', body, chunked=chunked, authorized=authorized)[0] == expected
            if expected != 200:
                assert not [path for path in storage.rglob('*') if path.is_file()], 'rejected body changed storage'
                assert request(port, '/pkg/meshdep', frame)[0] == 200, 'same instance did not recover'
            assert request(port, '/pkg/meshdep/' + meta['version'])[1] == artifact
    case('publish-exact-artifact-limit', lambda: publication('publish-exact-artifact-limit', frame, 200))
    enlarged = copy.deepcopy(meta)
    enlarged['index']['sha256sum'] = hashlib.sha256(artifact + b'x').hexdigest()
    oversized = publish_frame(json.dumps(enlarged).encode(), artifact + b'x')
    case('publish-artifact-over-limit', lambda: publication('publish-artifact-over-limit', oversized, 413))
    padded = copy.deepcopy(meta)
    padded['padding'] = 'x' * (1024 * 1024)
    metadata_frame = publish_frame(json.dumps(padded).encode(), artifact)
    assert len(metadata_frame) <= len(artifact) + 4096 + 1024 * 1024 + 10
    case('publish-metadata-over-limit', lambda: publication('publish-metadata-over-limit', metadata_frame, 413,
        config={'CJREPO_MAX_ARTIFACT_BYTES': str(len(artifact) + 4096)}))
    exact = copy.deepcopy(meta)
    exact['padding'] = ''
    exact['padding'] = 'x' * (1024 * 1024 - len(json.dumps(exact).encode()))
    assert len(json.dumps(exact).encode()) == 1024 * 1024
    case('publish-exact-metadata-limit', lambda: publication('publish-exact-metadata-limit', publish_frame(json.dumps(exact).encode(), artifact), 200))
    metadata_declared = b'\x01' + (1024 * 1024 + 1).to_bytes(4, 'little') + b'xxxxxx'
    case('publish-declared-metadata-over-limit', lambda: publication('publish-declared-metadata-over-limit', metadata_declared, 413))
    body = b'x' * (len(artifact) + 1024 * 1024 + 11)
    case('publish-chunked-total-over-limit', lambda: publication('publish-chunked-total-over-limit', body, 413, chunked=True))
    declared = b'\x01\x01\x00\x00\x00' + b' ' + b'\x01' + (len(artifact) + 1).to_bytes(4, 'little')
    case('publish-declared-artifact-over-limit', lambda: publication('publish-declared-artifact-over-limit', declared, 413))
    case('unauthorized-over-limit', lambda: publication('unauthorized-over-limit', oversized, 401, authorized=False))

    state = dict(extra=False, kind='index', posts=0)
    index = (json.dumps(meta['index']) + '\n').encode()
    class Upstream(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self):
            if self.path.startswith('/destination/'):
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            is_index = self.path.startswith('/index/')
            payload = index if is_index else artifact
            if state['extra']:
                if state['kind'] == 'index' and is_index:
                    payload += b'\n'
                elif state['kind'] == 'artifact':
                    if is_index:
                        item = copy.deepcopy(meta['index'])
                        item['sha256sum'] = hashlib.sha256(artifact + b'x').hexdigest()
                        payload = (json.dumps(item) + '\n').encode()
                    else:
                        payload += b'x'
            self.send_response(200)
            if not is_index:
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for chunk in (payload[:127], payload[127:]):
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.write(b'0\r\n\r\n')
            else:
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        def do_POST(self):
            state['posts'] += 1
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args):
            pass
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        for kind in ('index', 'artifact'):
            def proxy(kind=kind):
                label = 'proxy-' + kind + '-limit-and-recovery'
                config = {'CJREPO_MAX_INDEX_BYTES': str(len(index)), 'CJREPO_MAX_ARTIFACT_BYTES': str(len(artifact)), 'CJREPO_PROXY_TTL_SECONDS': '0'}
                with owned(label, config, f'http://127.0.0.1:{upstream.server_port}') as (port, storage, _, ready):
                    assert ready
                    state.update(extra=True, kind=kind)
                    index_path = '/index/me/sh/meshdep'
                    if kind == 'artifact':
                        assert request(port, index_path)[0] == 200
                    path = index_path if kind == 'index' else '/pkg/meshdep/' + meta['version']
                    assert request(port, path)[0] == 502
                    assert not list((storage / ('index' if kind == 'index' else 'artifacts')).rglob('meshdep' if kind == 'index' else '*.cjp'))
                    state['extra'] = False
                    if kind == 'artifact':
                        assert request(port, index_path)[0] == 200
                    status, data = request(port, path)
                    assert status == 200 and (kind == 'index' or data == artifact), 'same instance failed recovery at exact byte limit'
            case('proxy-' + kind + '-limit-and-recovery', proxy)
        for command in ('mirror', 'sync'):
            for kind in ('index', 'artifact'):
                label = command + '-' + kind + '-over-limit'
                def cli(label=label, command=command, kind=kind):
                    folder = report / label
                    folder.mkdir()
                    state.update(extra=True, kind=kind)
                    before = state['posts']
                    env = dict(base, HOME=str(folder), USERPROFILE=str(folder), CJREPO_STORAGE=str(folder / 'storage'),
                        CJREPO_MAX_INDEX_BYTES=str(len(index)), CJREPO_MAX_ARTIFACT_BYTES=str(len(artifact)))
                    endpoint = f'http://127.0.0.1:{upstream.server_port}'
                    arguments = [str(server), command, endpoint]
                    if command == 'sync':
                        arguments.append(endpoint + '/destination')
                    arguments += ['meshdep', meta['version']]
                    result = subprocess.run(arguments, cwd=folder, env=env, capture_output=True, text=True, timeout=15)
                    output = result.stdout + result.stderr
                    (folder / 'command.log').write_text(output)
                    assert result.returncode == 1 and 'payload exceeds configured byte limit' in output
                    assert state['posts'] == before and not [f for f in (folder / 'storage').rglob('*') if f.is_file()]
                case(label, cli)
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=3)
    summary = dict(success=all(item['passed'] for item in cases), passed=sum(item['passed'] for item in cases), total=len(cases),
        cases=cases, seconds=round(time.monotonic() - started, 2), serverSha256=hashlib.sha256(server.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return int(not summary['success'])


if __name__ == '__main__':
    raise SystemExit(main())
