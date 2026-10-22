#!/usr/bin/env python3
"""Keep a single-package preview distinct from an actual locked build."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cjpm', 'package-dir', 'evidence-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Windows Cangjie execution is paused; use the existing Linux runtime')
    client = args.cjpm.resolve()
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    meta = json.loads((args.package_dir / 'meta-data.json').read_text())
    assert meta['name'] == 'meshdep' and meta['version'] == '1.0.0' and not meta['organization']
    artifact = (args.package_dir / 'meshdep-1.0.0.cjp').read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == meta['index']['sha256sum']
    second = copy.deepcopy(meta['index'])
    second['version'] = '2.0.0'
    # Only 1.0.0 is a real archive. The synthetic second index candidate must
    # never be downloaded; this test does not claim a real 2.0.0 build.
    index = ('\n'.join(json.dumps(value) for value in (meta['index'], second)) + '\n').encode()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = index if self.path == '/index/me/sh/meshdep' else artifact if self.path == '/pkg/meshdep/1.0.0' else b''
            self.send_response(200 if body else 404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass

    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    facts = {}
    error = ''
    started = time.monotonic()
    try:
        app = report / 'app'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'hosted-server/app', app)
        config = app / 'cjpm.toml'
        config.write_text(config.read_text().replace('meshdep = "2.0.0"', 'meshdep = "(,)"'))
        (app / 'cjpm.lock').write_text('version = 0\n\n[requires]\nmeshdep = {version = "1.0.0"}\n')
        (app / 'cangjie-repo.toml').write_text('[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "http://127.0.0.1:' + str(fixture.server_port) + '"\n')
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_'))}
        env.update(HOME=str(report / 'home'), USERPROFILE=str(report / 'home'))
        (report / 'home').mkdir()
        def run(label, command):
            result = subprocess.run(list(map(str, command)), cwd=app, env=env, capture_output=True, text=True, timeout=120)
            output = result.stdout + result.stderr
            (report / (label + '.log')).write_text(output)
            assert result.returncode == 0, label + ' failed'
            return output
        run('build', [client, 'build'])
        actual = run('application', [app / 'target/release/bin/main'])
        before = {name: (app / name).read_bytes() for name in ('cjpm.lock', 'cjpm-provenance.json')}
        preview = run('preview', [client, 'repo', 'explain', 'meshdep'])
        request_count = len(requests)
        recorded = run('recorded', [client, 'repo', 'explain', 'meshdep', '--recorded'])
        facts = dict(realLockedBuild='high-1.0.0' in actual,
            previewCandidate='selected version: 2.0.0' in preview,
            previewLabel='Candidate preview:' in preview and 'ignores cjpm.lock and transitive constraints' in preview,
            recordedVersion='version: 1.0.0' in recorded,
            recordsUnchanged=all((app / name).read_bytes() == value for name, value in before.items()),
            recordedHasNoRequests=len(requests) == request_count,
            secondArtifactNeverFetched='/pkg/meshdep/2.0.0' not in requests)
    except Exception as failure:
        error = type(failure).__name__ + ': ' + str(failure)
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=3)
    summary = dict(success=not error and bool(facts) and all(facts.values()), facts=facts, error=error,
        seconds=round(time.monotonic() - started, 2), clientSha256=hashlib.sha256(client.read_bytes()).hexdigest(),
        runnerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)
    return int(not summary['success'])


if __name__ == '__main__':
    raise SystemExit(main())
