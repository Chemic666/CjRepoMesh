#!/usr/bin/env python3
"""Exercise source admission across workspace and build-script graphs on Linux."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import argparse
import copy
import hashlib
import json
import os
import subprocess
import threading
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cjpm', 'package-dir', 'evidence-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--case', action='append', help='Run only named cases')
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('Windows Cangjie execution is paused')
    client = args.cjpm.resolve()
    report = args.evidence_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    seed_meta = json.loads((args.package_dir / 'meta-data.json').read_text())
    seed_file = args.package_dir / 'meshdep-1.0.0.cjp'
    assert seed_meta['name'] == 'meshdep' and seed_meta['version'] == '1.0.0' and not seed_meta['organization']
    assert sha(seed_file) == seed_meta['index']['sha256sum']
    packages = {('', 'meshdep'): (seed_meta['index'], seed_file.read_bytes())}
    requests, cases, known_cases = [], [], []
    base_env = {k: v for k, v in os.environ.items()
                if not k.upper().startswith(('CJREPO_', 'CJREPOMESH_')) and k != 'CJPM_CONFIG'}
    started = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            parts = url.path.split('/')
            is_index = url.path.startswith('/index/')
            name = parts[-1] if is_index else parts[-2]
            org = parse_qs(url.query).get('organization', [''])[0]
            requests.append(dict(kind='index' if is_index else 'artifact', package=name))
            item = packages.get((org, name))
            body = b'' if item is None else ((json.dumps(item[0]) + '\n').encode() if is_index else item[1])
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

    def configure(folder):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'cangjie-repo.toml').write_text(
            f'[repository.cache]\npath = "{folder / "cache"}"\n[repository.home]\nregistry = "{endpoint}"\n')

    def package(folder, name, dependency='', executable=True):
        (folder / 'src').mkdir(parents=True)
        (folder / 'cjpm.toml').write_text(
            f'[package]\ncjc-version = "1.0.0"\nname = "{name}"\nversion = "1.0.0"\n'
            f'output-type = "{"executable" if executable else "static"}"\n'
            'description = "Owned graph compatibility fixture"\n' + dependency)
        (folder / 'README.md').write_text('# Owned graph fixture\n')
        return folder

    def invoke(folder, label, command, baseline=None, relative=False):
        home = folder / '.home'
        home.mkdir(exist_ok=True)
        env = dict(base_env, HOME=str(home), USERPROFILE=str(home))
        if baseline is not None:
            env['CJREPOMESH_SOURCE_BASELINE'] = baseline.name if relative else str(baseline)
        result = subprocess.run(list(map(str, command)), cwd=folder, env=env,
                                capture_output=True, text=True, timeout=100)
        output = result.stdout + result.stderr
        (folder / (label + '.log')).write_text(output)
        return result.returncode, output

    def entry(name, digest):
        return dict(package=name, version='1.0.0', repository='home', registry=endpoint, sha256=digest)

    def workspace(folder):
        configure(folder)
        (folder / 'cjpm.toml').write_text('[workspace]\nmembers = ["app_a", "app_b"]\n')
        for name, dep, imported, marker in (
                ('app_a', 'meshdep', 'meshdep', 'registryMarker()'),
                ('app_b', '"company::baselineparent"', 'company::baselineparent', 'baselineMarker()')):
            member = package(folder / name, name, f'\n[dependencies]\n{dep} = "1.0.0"\n')
            (member / 'src/main.cj').write_text(
                f'package {name}\nimport {imported}.*\nmain(): Int64 {{ println({marker}); return 0 }}\n')

    def scripted(folder, script_dependency):
        configure(folder)
        package(folder, 'graph_app', '\n[dependencies]\n"company::baselineparent" = "1.0.0"\n')
        (folder / 'src/main.cj').write_text('package graph_app\nimport company::baselineparent.*\n'
                                         'main(): Int64 { println(baselineMarker()); return 0 }\n')
        script_import, marker = '', '"no-script-dependencies"'
        if script_dependency:
            with (folder / 'cjpm.toml').open('a') as stream:
                stream.write(f'\n[script-dependencies]\n"{script_dependency}" = "1.0.0"\n')
            script_import = f'import {script_dependency}.*\n'
            marker = 'registryMarker()' if script_dependency == 'meshdep' else 'baselineMarker()'
        (folder / 'build.cj').write_text(
            'import std.fs.*\n' + script_import + 'main(args: Array<String>): Int64 {\n'
            f' File.appendTo("script-events", (args[0] + ":" + {marker} + "\\n").toArray())\n return 0\n}}\n')

    def run_case(label, setup, baseline, *, reject=False, script_marker=None,
                 relative=False, member=None, allowed_artifacts=()):
        known_cases.append(label)
        if args.case and label not in args.case:
            return
        folder = report / label
        error = ''
        before = len(requests)
        try:
            setup(folder)
            path = None
            if baseline is not None:
                # Synthetic approvals come from owned fixture metadata, never from
                # the output under test. This is not an approval workflow for users.
                path = folder / 'approved.json'
                path.write_text(json.dumps(baseline))
                approved_bytes = path.read_bytes()
            output_path = folder / 'cjpm-provenance.json'
            old_output = b'previous source output\n'
            output_path.write_bytes(old_output)
            command = [client, 'build'] + (['--member', member] if member else [])
            code, output = invoke(folder, 'build', command, path, relative)
            events = requests[before:]
            artifacts = [event['package'] for event in events if event['kind'] == 'artifact']
            if reject:
                assert code != 0 and 'repository source baseline rejected' in output, 'expected baseline rejection'
                assert sorted(artifacts) == sorted(allowed_artifacts), f'unexpected artifact requests: {artifacts}'
                if not allowed_artifacts:
                    assert output_path.read_bytes() == old_output, 'rejection replaced previous source output'
                else:
                    assert json.loads(output_path.read_text()) == baseline, 'earlier admitted script provenance missing'
            else:
                assert code == 0, 'build failed; inspect build.log'
                assert artifacts, 'cold build made no artifact requests'
                if member:
                    executables = [folder / 'target/release/bin' / member]
                elif (folder / 'app_a').exists():
                    executables = [folder / 'target/release/bin' / name for name in ('app_a', 'app_b')]
                else:
                    executables = [folder / 'target/release/bin/main']
                for number, executable in enumerate(executables):
                    status, text = invoke(folder, f'application-{number}', [executable])
                    assert status == 0 and 'high-1.0.0' in text, 'compiled application marker missing'
                actual = json.loads(output_path.read_text())
                expected = baseline or union
                assert sorted(actual['packages'], key=lambda x: x['package']) == sorted(
                    expected['packages'], key=lambda x: x['package']), 'final provenance differs'
            marker_path = folder / 'script-events'
            if script_marker is not None:
                assert marker_path.is_file() and script_marker in marker_path.read_text(), 'script did not run as expected'
                if reject:
                    assert 'post-build:' not in marker_path.read_text(), 'failed main graph ran post-build script'
                else:
                    assert script_marker.replace('pre-build:', 'post-build:') in marker_path.read_text(), 'post-build script missing'
            elif reject:
                assert not marker_path.exists(), 'rejected script graph ran its script'
            if path:
                assert path.read_bytes() == approved_bytes, 'approved baseline changed'
        except Exception as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        cases.append(dict(name=label, passed=not error, error=error, requests=requests[before:]))
        print(('FAIL ' if error else 'PASS ') + label + (': ' + error if error else ''), flush=True)

    preparation_error = ''
    try:
        parent = report / 'parent'
        configure(parent)
        package(parent, 'baselineparent', '\n[dependencies]\nmeshdep = "1.0.0"\n', executable=False)
        config = parent / 'cjpm.toml'
        config.write_text(config.read_text().replace('name = "baselineparent"', 'name = "baselineparent"\norganization = "company"'))
        (parent / 'src/parent.cj').write_text('package company::baselineparent\nimport meshdep.*\n'
                                           'public func baselineMarker(): String { return "baseline:" + registryMarker() }\n')
        assert invoke(parent, 'bundle', [client, 'bundle'])[0] == 0, 'parent fixture failed; inspect bundle.log'
        metadata = json.loads((parent / 'target/meta-data.json').read_text())
        archive = parent / 'target/baselineparent-1.0.0.cjp'
        assert sha(archive) == metadata['index']['sha256sum']
        packages[('company', 'baselineparent')] = (metadata['index'], archive.read_bytes())
        mesh = dict(formatVersion=1, packages=[entry('meshdep', sha(seed_file))])
        union = copy.deepcopy(mesh)
        union['packages'].append(entry('company::baselineparent', sha(archive)))
        drift = copy.deepcopy(union)
        drift['packages'][0]['sha256'] = '0' * 64
        run_case('workspace-unconfigured', workspace, None)
        run_case('workspace-union', workspace, union)
        run_case('workspace-incomplete-graph', workspace, mesh, reject=True)
        run_case('workspace-member-union-rejected', workspace, union, member='app_a', reject=True)
        run_case('workspace-member-approved', workspace, mesh, member='app_a')
        run_case('workspace-transitive-member', workspace, union, member='app_b')
        run_case('workspace-relative-baseline', workspace, union, relative=True)
        run_case('script-same-unconfigured', lambda f: scripted(f, 'company::baselineparent'), None,
                 script_marker='pre-build:baseline:high-1.0.0')
        run_case('script-same-approved', lambda f: scripted(f, 'company::baselineparent'), union,
                 script_marker='pre-build:baseline:high-1.0.0')
        run_case('script-relative-baseline', lambda f: scripted(f, 'company::baselineparent'), union,
                 relative=True, script_marker='pre-build:baseline:high-1.0.0')
        run_case('script-subset-unconfigured', lambda f: scripted(f, 'meshdep'), None,
                 script_marker='pre-build:high-1.0.0')
        run_case('script-subset-rejected', lambda f: scripted(f, 'meshdep'), union, reject=True)
        run_case('script-empty-before-main-rejection', lambda f: scripted(f, ''), drift, reject=True,
                 script_marker='pre-build:no-script-dependencies')
        run_case('script-approved-before-main-rejection', lambda f: scripted(f, 'meshdep'), mesh, reject=True,
                 allowed_artifacts=('meshdep',), script_marker='pre-build:high-1.0.0')
        if args.case and set(args.case) - set(known_cases):
            raise ValueError('unknown case selection')
    except Exception as failure:
        preparation_error = type(failure).__name__ + ': ' + str(failure)
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=3)
    summary = dict(success=bool(cases) and all(case['passed'] for case in cases) and not preparation_error,
                   passed=sum(case['passed'] for case in cases), total=len(cases), cases=cases,
                   preparationError=preparation_error, seconds=round(time.monotonic() - started, 2),
                   clientSha256=sha(client), runnerSha256=sha(Path(__file__)),
                   seedSha256=sha(seed_file), limits=['Per-analysis admission, not whole-command atomicity or a script sandbox.'])
    (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(f'{summary["passed"]}/{summary["total"]}; preparation error: {preparation_error}', flush=True)
    return int(not summary['success'])


if __name__ == '__main__':
    raise SystemExit(main())
