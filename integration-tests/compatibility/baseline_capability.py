#!/usr/bin/env python3
"""Check offline baseline capability discovery and fail-closed team CI preflight."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import threading
import time


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cjpm', type=Path, required=True)
    parser.add_argument('--old-cjpm', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Windows Cangjie execution is paused')
    root = Path(__file__).resolve().parents[2]
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    client, old_client = args.cjpm.resolve(), args.old_cjpm.resolve()
    started = time.monotonic()
    checks, requests = [], []
    private = 'synthetic-private-' + secrets.token_hex(12)
    base_env = {k: v for k, v in os.environ.items()
                if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_')) and k not in ('CJPM_CONFIG', 'CANGJIE_HOME')}
    base_env['PATH'] = '/usr/bin:/bin'
    assert shutil.which('cjc', path=base_env['PATH']) is None

    class Registry(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(500)
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Registry)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def record(name, operation):
        failure = ''
        try:
            operation()
        except Exception as error:
            failure = type(error).__name__ + ': ' + str(error)
        checks.append(dict(name=name, passed=not failure, error=failure))
        print(('FAIL ' if failure else 'PASS ') + name + (': ' + failure if failure else ''), flush=True)

    def invoke(folder, label, command, extra=None):
        (folder / '.home').mkdir(exist_ok=True)
        env = dict(base_env, HOME=str(folder / '.home'), USERPROFILE=str(folder / '.home'))
        env.update(extra or {})
        result = subprocess.run(list(map(str, command)), cwd=folder, env=env,
                                capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        (report / (label + '.log')).write_text(output.replace(private, '[REDACTED]'))
        assert private not in output, 'diagnostic exposed private configuration or argument'
        return result.returncode, result.stdout, result.stderr

    def query(name, arguments, *, success=False, poisoned=False, selected=None, token='source-baseline-v1'):
        folder = report / name
        folder.mkdir()
        (folder / '.home').mkdir()
        (folder / 'cangjie-repo.toml').write_text(
            'invalid = ["' + private if poisoned else
            f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "http://127.0.0.1:{server.server_port}"\n')
        if poisoned:
            (folder / 'cjpm.toml').write_text('invalid = ["' + private)
            (folder / 'build.cj').write_text('invalid build script ' + private)
            config = folder / 'unrelated-config'
            config.mkdir()
            (config / 'config.toml').write_text('invalid = ["' + private)
        snapshot = lambda: {f.relative_to(folder).as_posix(): sha(f) for f in folder.rglob('*') if f.is_file()}
        before = snapshot()
        code, output, _ = invoke(folder, name, [selected or client, *arguments],
                              dict(CJPM_CONFIG=str(folder / 'unrelated-config')) if poisoned else None)
        if success:
            assert code == 0 and output.strip() == token, 'offline capability query not recognized'
        else:
            assert code != 0 and output.strip() != token, 'unsupported form reported support'
        assert snapshot() == before, 'capability query changed workspace files'
        assert not requests, 'offline query contacted registry'

    fake = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> calls
if [[ "$1" == repo && "${2:-}" == supports ]]; then
    case "$TEST_SUPPORT" in
        supported) printf '%s\n' "$3"; exit 0 ;;
        main-only) [[ "$3" == source-baseline-v1 ]] && { printf 'source-baseline-v1\n'; exit 0; }; exit 1 ;;
        wrapped) printf 'PASS: client bundle integrity\nsource-baseline-v1\n'; exit 0 ;;
        suffix) printf 'source-baseline-v1\nunexpected suffix\n'; exit 0 ;;
        wrong) printf 'some-other-feature\n'; exit 0 ;;
        empty) exit 0 ;;
        failed) printf 'source-baseline-v1\n'; exit 7 ;;
        *) exit 1 ;;
    esac
fi
if [[ "$1" == build ]]; then
    touch build-started
    mkdir -p target/release/bin
    printf '#!/usr/bin/env bash\nexit 0\n' > target/release/bin/main
    chmod +x target/release/bin/main
fi
'''

    def consumer(name, support, *, enabled=True, selected=None, expected=2, script=False):
        folder = report / name
        folder.mkdir()
        shutil.copyfile(root / 'examples/team/consumer/run.sh', folder / 'run.sh')
        wrapper = folder / 'client'
        wrapper.write_text(fake)
        wrapper.chmod(0o755)
        approved = folder / 'approved.json'
        approved.write_text('{"formatVersion":1,"packages":[]}\n')
        digest = sha(approved)
        extra = dict(CJREPO_READ_TOKEN='synthetic-read', CJREPOMESH_CJPM=str(selected or wrapper), TEST_SUPPORT=support)
        if enabled:
            extra['CJREPOMESH_SOURCE_BASELINE'] = '' if name == 'explicit-empty-old-client' else str(approved)
        if script:
            extra['CJREPOMESH_SCRIPT_SOURCE_BASELINE'] = str(approved)
        code, stdout, stderr = invoke(folder, name, ['bash', 'run.sh'], extra)
        output = stdout + stderr
        assert code == expected, f'expected exit {expected}, got {code}'
        assert sha(approved) == digest, 'preflight changed approval'
        if expected == 0:
            assert (folder / 'build-started').exists(), 'unprotected or supported build did not run'
        else:
            assert not (folder / 'build-started').exists() and not (folder / 'target').exists(), 'unsupported client began build'
            expected_message = 'Protected consumer requires' if script else 'requires source-baseline-v1'
            assert expected_message in output, 'missing actionable preflight diagnostic'
        if not selected:
            if script and not enabled:
                assert not (folder / 'calls').exists(), 'missing main approval reached client'
                return
            calls = (folder / 'calls').read_text().splitlines()
            if enabled:
                assert calls[0] == 'repo supports source-baseline-v1'
                if expected:
                    assert len(calls) == (2 if script and support == 'main-only' else 1), 'unsupported preflight continued to another command'
            else:
                assert calls[0] == 'build', 'unconfigured flow gained capability dependency'

    def query_with_stderr():
        wrapper = report / 'stderr-wrapper.sh'
        wrapper.write_text('#!/bin/sh\nprintf "wrapper verification notice\\n" >&2\nexec ' +
                           shlex.quote(str(client)) + ' "$@"\n')
        wrapper.chmod(0o755)
        query('query-stderr-wrapper', ['repo', 'supports', 'source-baseline-v1'], success=True, selected=wrapper)

    try:
        for name, poisoned in (('query-script-no-sdk', False), ('query-script-poisoned-config', True)):
            record(name, lambda name=name, poisoned=poisoned: query(name,
                   ['repo', 'supports', 'script-source-baseline-v1'], success=True,
                   poisoned=poisoned, token='script-source-baseline-v1'))
        record('query-script-extra-argument', lambda: query('query-script-extra-argument',
               ['repo', 'supports', 'script-source-baseline-v1', 'extra'], token='script-source-baseline-v1'))
        record('consumer-script-main-only', lambda: consumer('consumer-script-main-only', 'main-only', script=True))
        record('consumer-script-supported', lambda: consumer('consumer-script-supported', 'supported', script=True, expected=0))
        record('consumer-script-missing-main', lambda: consumer('consumer-script-missing-main', 'supported',
               enabled=False, script=True))
        record('query-no-sdk', lambda: query('query-no-sdk', ['repo', 'supports', 'source-baseline-v1'], success=True))
        record('query-poisoned-config', lambda: query('query-poisoned-config', ['repo', 'supports', 'source-baseline-v1'], success=True, poisoned=True))
        record('query-unknown-feature', lambda: query('query-unknown-feature', ['repo', 'supports', private], poisoned=True))
        record('query-help-feature', lambda: query('query-help-feature', ['repo', 'supports', '--help']))
        record('query-short-help-feature', lambda: query('query-short-help-feature', ['repo', 'supports', '-h']))
        record('query-stderr-wrapper', query_with_stderr)
        record('query-extra-argument', lambda: query('query-extra-argument', ['repo', 'supports', 'source-baseline-v1', 'extra']))
        record('online-explain-still-needs-sdk', lambda: query('online-explain-still-needs-sdk', ['repo', 'explain', 'meshdep']))
        record('old-query-unsupported', lambda: query('old-query-unsupported', ['repo', 'supports', 'source-baseline-v1'], selected=old_client))
        for support in ('unsupported', 'wrong', 'empty', 'failed', 'suffix'):
            record('consumer-' + support, lambda support=support: consumer('consumer-' + support, support))
        record('consumer-unconfigured', lambda: consumer('consumer-unconfigured', 'unsupported', enabled=False, expected=0))
        record('consumer-supported', lambda: consumer('consumer-supported', 'supported', expected=0))
        record('consumer-prefix', lambda: consumer('consumer-prefix', 'wrapped'))
        record('explicit-empty-old-client', lambda: consumer('explicit-empty-old-client', 'unsupported'))
        record('consumer-real-old-client', lambda: consumer('consumer-real-old-client', '', selected=old_client))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    result = dict(success=bool(checks) and all(c['passed'] for c in checks), passed=sum(c['passed'] for c in checks),
                  total=len(checks), cases=checks, registryRequests=len(requests), seconds=round(time.monotonic()-started, 2),
                  clientSha256=sha(client), oldClientSha256=sha(old_client), runnerSha256=sha(Path(__file__)),
                  consumerSha256=sha(root/'examples/team/consumer/run.sh'),
                  limits=['Capability is a compatibility signal, not binary authentication. Synthetic consumer controls do not replace real team builds.'])
    (report / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    return int(not result['success'])


if __name__ == '__main__':
    raise SystemExit(main())
