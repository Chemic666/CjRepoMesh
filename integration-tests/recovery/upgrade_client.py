"""Optional cold consumers for the owned upgrade drill, never business volumes."""
import hashlib
import json
from pathlib import Path
import runpy


def verify_inputs(args, parser):
    if not args.client_bundle:
        if args.client_sdk or args.client_native:
            parser.error('client-sdk/client-native require client-bundle')
        return None
    if not args.client_sdk or not (args.client_sdk / 'envsetup.sh').is_file():
        parser.error('client-bundle requires an existing client-sdk')
    if not args.client_native or not all((args.client_native / 'bin' / name).is_file() for name in ('ar', 'ld')):
        parser.error('client-bundle requires existing client-native ar/ld')
    verifier = Path(__file__).resolve().parents[2] / 'deployment/client/verify.py'
    try:
        return runpy.run_path(str(verifier))['verify_bundle'](args.client_bundle)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error('invalid client bundle: ' + str(error))


def consume(*, name, server, image, packages, args, manifest, report,
            docker, inspect, register, label_key, scope, secret_values):
    evidence = report / ('consumer-' + name)
    evidence.mkdir(exist_ok=False)
    job = evidence / 'job'
    (job / 'src').mkdir(parents=True)
    (job / '.home').mkdir()
    registry = 'http://127.0.0.1:8080'
    qualified = lambda p: (p['organization'] + '::' if p['organization'] else '') + p['name']
    approved = dict(formatVersion=1, packages=[dict(package=qualified(p), version=p['version'],
        repository='home', registry=registry, sha256=p['sha256']) for p in packages])
    approved['packages'].sort(key=lambda p: p['package'])
    approval = evidence / 'approved-source.json'
    approval.write_text(json.dumps(approved, indent=2) + '\n', encoding='utf-8')
    original = approval.read_bytes()
    config = ('[package]\ncjc-version = "1.0.0"\nname = "upgrade_consumer"\n'
              'version = "1.0.0"\noutput-type = "executable"\n\n[dependencies]\n')
    config += ''.join(json.dumps(qualified(p)) + ' = ' + json.dumps(p['version']) + '\n' for p in packages)
    (job / 'cjpm.toml').write_text(config, encoding='utf-8')
    (job / 'cangjie-repo.toml').write_text('[repository.cache]\npath = "cache"\n'
        '[repository.home]\nregistry = "' + registry + '"\ntoken-env = "CJREPO_READ_TOKEN"\n', encoding='utf-8')
    source = 'package upgrade_consumer\n' + ''.join('import ' + qualified(p) + '.*\n' for p in packages)
    source += 'main(): Int64 {\n    println(registryMarker())\n'
    expected = [args.expected_output]
    if len(packages) == 2:
        source += '    println(teamGreeting("upgrade"))\n'
        expected.append('CjRepoMesh team 1.0.0: upgrade')
    source += '    return 0\n}\n'
    (job / 'src/main.cj').write_text(source, encoding='utf-8')
    if any((job / n).exists() for n in ('cache', 'target', 'cjpm.lock', 'cjpm-provenance.json')):
        raise ValueError('consumer must start with fresh dependency/build state')
    command = ['create', '--pull=never', '--label', label_key + '=' + scope,
        '--network', 'container:' + server, '--read-only', '--cap-drop=ALL',
        '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=128m,mode=1777',
        '--workdir', '/job', '--env', 'HOME=/job/.home', '--env', 'USERPROFILE=/job/.home',
        '--env', 'CJREPO_READ_TOKEN', '--env', 'CJREPOMESH_SOURCE_BASELINE=/approved/source.json']
    for path, target, readonly in ((job, '/job', False), (approval, '/approved/source.json', True),
            (args.client_bundle, '/client', True), (args.client_sdk, '/opt/cangjie', True),
            (args.client_native, '/opt/native', True)):
        command += ['--mount', 'type=bind,source=' + str(path.resolve()) + ',target=' + target + (',readonly' if readonly else '')]
    for path in sorted((args.client_native / 'system').rglob('*')):
        if path.is_file():
            command += ['--mount', 'type=bind,source=' + str(path.resolve()) + ',target=/' +
                        path.relative_to(args.client_native / 'system').as_posix() + ',readonly']
    script = ('source /opt/cangjie/envsetup.sh; '
        'export PATH="/opt/native/bin:$PATH" LD_LIBRARY_PATH="/opt/native/lib:$LD_LIBRARY_PATH"; '
        'set -eu; /client/run.sh repo supports source-baseline-v1; /client/run.sh build; '
        './target/release/bin/main; /client/run.sh repo explain meshdep --recorded')
    command += ['--entrypoint', '/bin/bash', image, '-ec', script]
    identifier = docker(*command).decode().strip()
    register(identifier)  # Must precede start, inspect, output decoding and logging.
    output = docker('start', '--attach', identifier, timeout=180, include_stderr=True).decode('utf-8', 'replace')
    redacted = output
    for value in secret_values:
        redacted = redacted.replace(value, '[REDACTED]')
    (evidence / 'client.log').write_text(redacted, encoding='utf-8')
    if redacted != output:
        raise ValueError('client diagnostics exposed a generated credential; saved output redacted')
    state = inspect(identifier)['State']
    if state['Running'] or state['ExitCode'] != 0:
        raise ValueError('cold consumer failed; inspect retained redacted client log')
    client_sha = manifest['files']['cjpm']['sha256']
    if 'PASS: client bundle integrity; cjpm SHA-256 ' + client_sha not in output:
        raise ValueError('complete fixed client integrity result absent')
    if 'source-baseline-v1' not in output.splitlines() or any(line not in output.splitlines() for line in expected):
        raise ValueError('capability or actual application output differs')
    actual = json.loads((job / 'cjpm-provenance.json').read_text(encoding='utf-8'))
    actual['packages'].sort(key=lambda p: p['package'])
    if actual != approved or approval.read_bytes() != original:
        raise ValueError('actual source graph or independent approval changed')
    return dict(clientSha256=client_sha, applicationOutput=expected, packages=approved['packages'],
        approvalSha256=hashlib.sha256(original).hexdigest(), freshCache=True,
        freshTarget=True, freshLock=True, approvalMountedReadOnly=True, consumer=identifier)
