#!/usr/bin/env python3
"""Verify an opt-in source baseline before repository artifact downloads."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import argparse
import copy
import hashlib
import json
import os
import secrets
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cjpm', 'package-dir', 'evidence-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--case', action='append', help='Run selected checks plus the required unconfigured control')
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Windows Cangjie execution is paused')
    client = args.cjpm.resolve()
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    seed_meta = json.loads((args.package_dir / 'meta-data.json').read_text())
    seed = (args.package_dir / 'meshdep-1.0.0.cjp').read_bytes()
    assert seed_meta['name'] == 'meshdep' and seed_meta['version'] == '1.0.0' and not seed_meta['organization']
    assert hashlib.sha256(seed).hexdigest() == seed_meta['index']['sha256sum']
    packages = {('', 'meshdep'): (seed_meta['index'], seed)}
    requests = []
    cases = []
    nonce = 'synthetic-private-' + secrets.token_hex(12)
    base_env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_')) and k != 'CJPM_CONFIG'}
    started = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            url = urlsplit(self.path)
            segments = url.path.split('/')
            organization = parse_qs(url.query).get('organization', [''])[0]
            name = segments[-1] if url.path.startswith('/index/') else segments[-2]
            item = packages.get((organization, name))
            body = b'' if item is None else (json.dumps(item[0]) + '\n').encode() if url.path.startswith('/index/') else item[1]
            self.send_response(200 if body else 404)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass

    fixture = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{fixture.server_port}'
    repository = f'[repository.cache]\npath = "cache"\n[repository.home]\nregistry = "{endpoint}"\n'

    def invoke(folder, label, command, env=None):
        (folder / '.home').mkdir(exist_ok=True)
        environment = dict(base_env, HOME=str(folder / '.home'), USERPROFILE=str(folder / '.home'))
        environment.update(env or {})
        result = subprocess.run(list(map(str, command)), cwd=folder, env=environment, capture_output=True, text=True, timeout=100)
        original = result.stdout + result.stderr
        (folder / (label + '.log')).write_text(original.replace(nonce, '[REDACTED]'))
        assert nonce not in original, 'diagnostic exposed synthetic private input'
        return result.returncode, original

    def app(label, empty=False):
        folder = report / label
        (folder / 'src').mkdir(parents=True)
        text = '[package]\ncjc-version = "1.0.0"\nname = "baseline_app"\nversion = "1.0.0"\noutput-type = "executable"\n'
        if not empty:
            text += '\n[dependencies]\n"company::baselineparent" = "1.0.0"\n'
        (folder / 'cjpm.toml').write_text(text)
        (folder / 'cangjie-repo.toml').write_text(repository)
        (folder / 'src/main.cj').write_text('package baseline_app\n' +
            ('import company::baselineparent.*\n' if not empty else '') +
            'main(): Int64 {\n println(' + ('baselineMarker()' if not empty else '"empty graph"') + ')\n return 0\n}\n')
        return folder

    def record(label, operation):
        if args.case and label != 'unconfigured' and label not in args.case:
            return
        error = ''
        try:
            operation()
        except Exception as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        cases.append(dict(name=label, passed=not error, error=error))
        print(('PASS ' if not error else 'FAIL ') + label, flush=True)

    try:
        # Build a genuine parent CJP whose metadata has a genuine transitive
        # meshdep dependency. The final consumer imports the parent's function.
        parent = report / 'parent'
        (parent / 'src').mkdir(parents=True)
        (parent / 'cjpm.toml').write_text('[package]\ncjc-version = "1.0.0"\nname = "baselineparent"\norganization = "company"\nversion = "1.0.0"\noutput-type = "static"\ndescription = "Synthetic transitive baseline fixture"\n\n[dependencies]\nmeshdep = "1.0.0"\n')
        (parent / 'src/parent.cj').write_text('package company::baselineparent\nimport meshdep.*\npublic func baselineMarker(): String { return "baseline:" + registryMarker() }\n')
        (parent / 'cangjie-repo.toml').write_text(repository)
        (parent / 'README.md').write_text('# Synthetic baseline parent\n\nOwned integration fixture.\n')
        assert invoke(parent, 'bundle', [client, 'bundle'])[0] == 0, 'parent fixture failed'
        parent_meta = json.loads((parent / 'target/meta-data.json').read_text())
        parent_bytes = (parent / 'target/baselineparent-1.0.0.cjp').read_bytes()
        assert hashlib.sha256(parent_bytes).hexdigest() == parent_meta['index']['sha256sum']
        packages[('company', 'baselineparent')] = (parent_meta['index'], parent_bytes)
        original = app('unconfigured')
        def unconfigured():
            assert invoke(original, 'build', [client, 'build'])[0] == 0
            assert 'baseline:high-1.0.0' in invoke(original, 'application', [original / 'target/release/bin/main'])[1]
        record('unconfigured', unconfigured)
        approved = json.loads((original / 'cjpm-provenance.json').read_text())
        assert {entry['package'] for entry in approved['packages']} == {'meshdep', 'company::baselineparent'}

        def check(label, baseline, *, success=False, value=None, empty=False,
                  baseline_name='approved.json', link=None, warm=False, replace=False):
            folder = original if warm else app(label, empty)
            if replace:
                with (folder / 'cjpm.toml').open('a') as stream:
                    stream.write('\n[replace]\nmeshdep = "1.0.0"\n')
            path = folder / baseline_name
            if link:
                target = folder / link
                target.write_text(json.dumps(baseline))
                path.symlink_to(target.name)
            if baseline is not None:
                path.write_text(baseline if isinstance(baseline, str) else json.dumps(baseline))
            before = path.read_bytes() if path.exists() else None
            previous = (folder / 'cjpm-provenance.json').read_bytes() if (folder / 'cjpm-provenance.json').exists() else None
            offset = len(requests)
            code, output = invoke(folder, label, [client, 'build'], {'CJREPOMESH_SOURCE_BASELINE': value if value is not None else path.name})
            assert (code == 0) == success, 'unexpected build status'
            if before is not None:
                assert path.read_bytes() == before, 'approved baseline changed'
            if success:
                marker = 'empty graph' if empty else 'baseline:high-1.0.0'
                assert marker in invoke(folder, 'application', [folder / 'target/release/bin/main'])[1]
            else:
                assert 'repository source baseline' in output.lower()
                assert not any(urlsplit(url).path.startswith('/pkg/') for url in requests[offset:]), 'artifact requested before rejection'
                actual = folder / 'cjpm-provenance.json'
                assert (actual.read_bytes() if actual.exists() else None) == previous, 'rejected check replaced old result'

        record('matching', lambda: check('matching', approved, success=True))
        reversed_baseline = copy.deepcopy(approved)
        reversed_baseline['packages'].reverse()
        record('order-independent', lambda: check('order-independent', reversed_baseline, success=True))
        for field, replacement in (('version', '2.0.0'), ('repository', 'other'), ('registry', endpoint + '/other'), ('sha256', '0' * 64)):
            document = copy.deepcopy(approved)
            document['packages'][0][field] = replacement
            record('changed-' + field, lambda field=field, document=document: check('changed-' + field, document))
        missing = copy.deepcopy(approved)
        missing['packages'] = [item for item in missing['packages'] if item['package'] != 'meshdep']
        record('missing-transitive', lambda: check('missing-transitive', missing))
        extra = copy.deepcopy(approved)
        extra['packages'].append(dict(extra['packages'][0], package='unexpected'))
        record('unexpected-package', lambda: check('unexpected-package', extra))
        duplicate = copy.deepcopy(approved)
        duplicate['packages'].append(copy.deepcopy(duplicate['packages'][0]))
        record('duplicate-package', lambda: check('duplicate-package', duplicate))
        invalid = copy.deepcopy(approved)
        invalid['packages'][0]['registry'] = 'https://user:' + nonce + '@invalid.example'
        record('unsafe-registry', lambda: check('unsafe-registry', invalid))
        unknown = copy.deepcopy(approved)
        unknown['formatVersion'] = 2
        record('unknown-format', lambda: check('unknown-format', unknown))
        wrong = copy.deepcopy(approved)
        wrong['formatVersion'] = True
        record('wrong-format-type', lambda: check('wrong-format-type', wrong))
        record('malformed-private', lambda: check('malformed-private', '{"private":"' + nonce))
        record('missing-file', lambda: check('missing-file', None))
        record('empty-setting', lambda: check('empty-setting', approved, value=''))
        record('oversized-baseline', lambda: check('oversized-baseline', ' ' * (1024 * 1024 + 1)))
        record('baseline-is-output', lambda: check('baseline-is-output', approved, baseline_name='cjpm-provenance.json'))
        record('baseline-is-temporary', lambda: check('baseline-is-temporary', approved, baseline_name='cjpm-provenance.json.tmp'))
        record('baseline-output-alias', lambda: check('baseline-output-alias', approved, link='cjpm-provenance.json'))
        record('baseline-temporary-alias', lambda: check('baseline-temporary-alias', approved, link='cjpm-provenance.json.tmp'))
        record('matching-replace', lambda: check('matching-replace', approved, replace=True, success=True))
        replaced = copy.deepcopy(approved)
        next(item for item in replaced['packages'] if item['package'] == 'meshdep')['sha256'] = '0' * 64
        record('changed-replace', lambda: check('changed-replace', replaced, replace=True))
        mistyped = copy.deepcopy(approved)
        mistyped['formatVersion'] = 1.0
        record('floating-format-type', lambda: check('floating-format-type', mistyped))
        invalid_sha = copy.deepcopy(approved)
        invalid_sha['packages'][0]['sha256'] = 'invalid'
        record('invalid-sha256', lambda: check('invalid-sha256', invalid_sha))
        empty_field = copy.deepcopy(approved)
        empty_field['packages'][0]['repository'] = ''
        record('empty-required-field', lambda: check('empty-required-field', empty_field))
        record('private-missing-path', lambda: check('private-missing-path', None, value=nonce))
        record('missing-packages', lambda: check('missing-packages', dict(formatVersion=1)))
        record('null-packages', lambda: check('null-packages', dict(formatVersion=1, packages=None)))
        for field in ('package', 'version', 'repository', 'registry', 'sha256'):
            typed = copy.deepcopy(approved)
            typed['packages'][0][field] = True
            record('nonstring-' + field, lambda field=field, typed=typed: check('nonstring-' + field, typed))
        record('empty-graph-mismatch', lambda: check('empty-graph-mismatch', approved, empty=True))
        record('empty-graph-match', lambda: check('empty-graph-match', dict(formatVersion=1, packages=[]), empty=True, success=True))
        drift = copy.deepcopy(approved)
        drift['packages'][0]['sha256'] = '0' * 64
        record('warm-cache-mismatch', lambda: check('warm-cache-mismatch', drift, warm=True))
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=3)
    summary = dict(success=bool(cases) and all(case['passed'] for case in cases), passed=sum(case['passed'] for case in cases), total=len(cases),
        cases=cases, seconds=round(time.monotonic() - started, 2), clientSha256=hashlib.sha256(client.read_bytes()).hexdigest(),
        runnerSha256=runner_sha256,
        limits=['Owned HTTP registry and genuine two-package transitive build; no build-script sandbox, Git/local input or unpacked-cache authenticity guarantee.'])
    (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return int(not summary['success'])


if __name__ == '__main__':
    raise SystemExit(main())
