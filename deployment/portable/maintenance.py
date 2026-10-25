#!/usr/bin/env python3
"""Stopped backup and new-volume restore for a verified portable deployment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import sys
import tarfile

# Offline inspection must not create local module caches in the delivery.
sys.dont_write_bytecode = True
from configure import protect_windows_file, read_ca
from verify import check_running_credentials, digest, regular_file, verify_bundle

PROJECT = r'cjrepomesh-[a-f0-9]{16}'
SHA256 = r'[a-f0-9]{64}'
CAPABILITY = 'cold-backup-v1'
RESTORE_CHECK_CAPABILITY = 'offline-inputs-v1'
LABEL = 'io.cjrepomesh.maintenance'
MAX_CONFIGURATION_BYTES = 1024 * 1024


class MaintenanceError(ValueError):
    """Only static, non-sensitive diagnostics belong in this exception."""


def ordinary_directory(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400)


def require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise MaintenanceError('target already exists; use a new output or unconfigured deployment')


def private_file(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == 'nt':
            protect_windows_file(path)
        return os.fdopen(descriptor, 'wb')
    except BaseException:
        os.close(descriptor)
        raise


def write_private(path: Path, data: bytes) -> None:
    with private_file(path) as stream:
        stream.write(data)


def read_configuration_bytes(path: Path) -> bytes:
    if not regular_file(path) or path.stat().st_size > MAX_CONFIGURATION_BYTES:
        raise MaintenanceError('runtime configuration must be a regular file of at most 1 MiB')
    with path.open('rb') as stream:
        data = stream.read(MAX_CONFIGURATION_BYTES + 1)
    if len(data) > MAX_CONFIGURATION_BYTES:
        raise MaintenanceError('runtime configuration exceeds 1 MiB')
    return data


def read_configuration(data: bytes) -> dict[str, str]:
    if len(data) > MAX_CONFIGURATION_BYTES:
        raise MaintenanceError('runtime configuration exceeds 1 MiB')
    values = {}
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeError:
        raise MaintenanceError('invalid runtime configuration encoding') from None
    for line in lines:
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if (not separator or key in values or
                not re.fullmatch(r'COMPOSE_PROJECT_NAME|CJREPO_[A-Z0-9_]+', key) or
                any(character.isspace() or character in '\"\'`$#\\' for character in value)):
            raise MaintenanceError('configuration requires unique literal dotenv assignments; no interpolation or quoting')
        values[key] = value
    if (not re.fullmatch(PROJECT, values.get('COMPOSE_PROJECT_NAME', '')) or
            not re.fullmatch(r'[0-9]{1,5}', values.get('CJREPO_HOST_PORT', '')) or
            not 1 <= int(values['CJREPO_HOST_PORT']) <= 65535 or
            not values.get('CJREPO_READ_TOKEN') or not values.get('CJREPO_PUBLISH_TOKEN') or
            values['CJREPO_READ_TOKEN'] == values['CJREPO_PUBLISH_TOKEN'] or
            'CJREPO_CA_SHA256' not in values or
            (values['CJREPO_CA_SHA256'] and not re.fullmatch(SHA256, values['CJREPO_CA_SHA256']))):
        raise MaintenanceError('invalid deployment identity, port, private credentials or CA configuration')
    return values


def restored_configuration(data: bytes, project: str, port: int | None) -> bytes:
    values = read_configuration(data)
    if not re.fullmatch(PROJECT, project) or project == values['COMPOSE_PROJECT_NAME']:
        raise MaintenanceError('restore requires a distinct new project identity')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise MaintenanceError('restore port must be between 1 and 65535')
    result = re.sub(rb'(?m)^COMPOSE_PROJECT_NAME=[^\r\n]+',
                    b'COMPOSE_PROJECT_NAME=' + project.encode('ascii'), data)
    if port is not None:
        result = re.sub(rb'(?m)^CJREPO_HOST_PORT=[^\r\n]+',
                        b'CJREPO_HOST_PORT=' + str(port).encode('ascii'), result)
    return result


def archive_manifest(path: Path) -> dict:
    """Hash all regular files without extracting or loading them into memory."""
    files, directories, seen = {}, set(), set()
    root_seen = False
    try:
        with tarfile.open(path, 'r:') as archive:
            for item in archive:
                name = item.name
                while name.startswith('./'):
                    name = name[2:]
                if name in ('', '.'):
                    if root_seen or not item.isdir() or item.mode & 0o7000:
                        raise MaintenanceError('backup archive contains a duplicate or unsafe root directory')
                    root_seen = True
                    continue
                parts = PurePosixPath(name).parts
                if (not name or '\\' in name or name.startswith('/') or
                        '..' in parts or not parts or parts[0] not in {'index', 'artifacts'} or
                        not (item.isdir() or item.isfile()) or item.issparse() or item.mode & 0o7000):
                    raise MaintenanceError('backup archive contains an unsafe path or file type')
                canonical = PurePosixPath(name).as_posix()
                if canonical in seen or any(PurePosixPath(*parts[:i]).as_posix() in files
                                             for i in range(1, len(parts))):
                    raise MaintenanceError('backup archive contains duplicate or conflicting paths')
                if item.isfile() and (len(parts) == 1 or
                                      any(other.startswith(canonical + '/') for other in seen)):
                    raise MaintenanceError('backup archive contains conflicting storage paths')
                seen.add(canonical)
                if item.isdir():
                    directories.add(canonical)
                    continue
                checksum = hashlib.sha256()
                size = 0
                with archive.extractfile(item) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        size += len(chunk)
                        checksum.update(chunk)
                if size != item.size:
                    raise MaintenanceError('backup archive contains a truncated file')
                files[canonical] = dict(bytes=size, sha256=checksum.hexdigest())
    except (tarfile.TarError, OSError):
        raise MaintenanceError('backup data archive is unreadable or invalid') from None
    return dict(files=dict(sorted(files.items())), directories=sorted(directories))


def image_identity(image: dict) -> None:
    if (not isinstance(image, dict) or not re.fullmatch(r'sha256:' + SHA256, image.get('id', '')) or
            image.get('tag') != 'cjrepomesh-portable:sha256-' + image['id'][7:] or
            image.get('os') != 'linux' or image.get('architecture') != 'amd64' or
            not re.fullmatch(SHA256, image.get('serverSha256', ''))):
        raise MaintenanceError('invalid backup image identity')


def verify_backup(root: Path) -> dict:
    try:
        if not ordinary_directory(root) or not regular_file(root/'backup.json'):
            raise MaintenanceError('backup requires an ordinary directory and manifest')
        if (root/'backup.json').stat().st_size > 16 * 1024 * 1024:
            raise MaintenanceError('backup manifest exceeds 16 MiB')
        value = json.loads((root/'backup.json').read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or type(value.get('formatVersion')) is not int or
                value['formatVersion'] != 1 or value.get('kind') != 'cjrepomesh-cold-backup'):
            raise MaintenanceError('unsupported backup format')
        image_identity(value.get('image'))
        ca_sha = value.get('caSha256')
        if not isinstance(ca_sha, str) or (ca_sha and not re.fullmatch(SHA256, ca_sha)):
            raise MaintenanceError('invalid backup CA identity')
        names = {'data.tar', '.env'} | ({'trust/ca.pem'} if ca_sha else set())
        if not isinstance(value.get('files'), dict) or set(value['files']) != names:
            raise MaintenanceError('unexpected backup file list')
        expected_names = {'backup.json', 'data.tar', '.env'} | ({'trust'} if ca_sha else set())
        if {item.name for item in root.iterdir()} != expected_names:
            raise MaintenanceError('unexpected backup directory contents')
        if ca_sha and (not ordinary_directory(root/'trust') or
                       {item.name for item in (root/'trust').iterdir()} != {'ca.pem'}):
            raise MaintenanceError('unexpected backup CA directory')
        for name in names:
            entry, path = value['files'][name], root/name
            if (not isinstance(entry, dict) or not regular_file(path) or
                    type(entry.get('bytes')) is not int or entry['bytes'] < 0 or
                    entry['bytes'] != path.stat().st_size or entry.get('sha256') != digest(path)):
                raise MaintenanceError('backup file integrity check failed')
        configuration = read_configuration(read_configuration_bytes(root/'.env'))
        source = value.get('source')
        project = configuration['COMPOSE_PROJECT_NAME']
        if (not isinstance(source, dict) or source.get('project') != project or
                source.get('volume') != project + '_cjrepo-data' or
                type(source.get('port')) is not int or source['port'] != int(configuration['CJREPO_HOST_PORT']) or
                configuration['CJREPO_CA_SHA256'] != ca_sha):
            raise MaintenanceError('backup configuration does not match its deployment identity')
        if ca_sha and (digest(root/'trust/ca.pem') != ca_sha or not read_ca(root/'trust/ca.pem')):
            raise MaintenanceError('backup CA does not match its configuration')
        if value.get('storage') != archive_manifest(root/'data.tar'):
            raise MaintenanceError('backup storage file set does not match its manifest')
        return value
    except (OSError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
        raise MaintenanceError('backup is incomplete or malformed') from None


def docker(*arguments: str, stdin=None, stdout=None, timeout: int = 300) -> str:
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('COMPOSE_', 'CJREPO_'))}
    result = subprocess.run(('docker', *arguments), env=environment, stdin=stdin,
                            stdout=subprocess.PIPE if stdout is None else stdout,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise MaintenanceError('Docker operation failed; inspect the selected deployment locally')
    return result.stdout.decode('utf-8') if stdout is None else ''


def require_stopped(volume: str) -> None:
    identifiers = docker('ps', '--all', '--quiet', '--no-trunc', '--filter', 'volume=' + volume).split()
    if identifiers:
        for item in json.loads(docker('inspect', *identifiers)):
            if item['State'].get('Running') and any(mount.get('Type') == 'volume' and
                    mount.get('Name') == volume and mount.get('RW') is True for mount in item['Mounts']):
                raise MaintenanceError('data volume has a running writer; stop all writers before maintenance')


def helper(image: str, volume: str, *command: str, readonly: bool,
           stdin=None, stdout=None) -> str:
    operation = secrets.token_hex(16)
    mount = f'type=volume,source={volume},target=/var/lib/cjrepo'
    if readonly:
        mount += ',readonly,volume-nocopy'
    identifier = docker('create', '--pull=never', '--network=none', '--read-only',
        '--cap-drop=ALL', '--security-opt', 'no-new-privileges:true', '--label', LABEL + '=' + operation,
        '--interactive', '--mount', mount, '--entrypoint', command[0], image, *command[1:]).strip()
    if not re.fullmatch(r'[a-f0-9]{64}', identifier):
        raise MaintenanceError('cannot identify maintenance helper')
    try:
        output = docker('start', '--attach', '--interactive', identifier, stdin=stdin, stdout=stdout)
        state = json.loads(docker('inspect', identifier))[0]['State']
        if state.get('Running') or state.get('ExitCode') != 0:
            raise MaintenanceError('maintenance helper did not complete successfully')
    except BaseException as failure:
        item = json.loads(docker('inspect', identifier))[0]
        if (item.get('Config', {}).get('Labels') or {}).get(LABEL) != operation:
            raise MaintenanceError('maintenance helper identity changed; retained for inspection')
        if item.get('State', {}).get('Running'):
            docker('stop', '--time', '5', identifier)
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        # Docker retains stdout/stderr with this stopped helper. Its ID is
        # engine-generated and validated above; never include captured output.
        raise MaintenanceError('failed maintenance helper retained for local diagnosis: ' + identifier) from None
    item = json.loads(docker('inspect', identifier))[0]
    if (item.get('Config', {}).get('Labels') or {}).get(LABEL) != operation:
        raise MaintenanceError('maintenance helper identity changed; retained for inspection')
    docker('rm', identifier)
    return output


def deployment(root: Path, *, check_docker: bool = True) -> tuple[dict, bytes, dict, bytes | None]:
    manifest = verify_bundle(root, check_docker=check_docker)
    if manifest.get('maintenance') != CAPABILITY or manifest.get('caConfiguration') != 'pem-directory-v1':
        raise MaintenanceError('this bundle does not support stopped maintenance; use a verified current bundle')
    data = read_configuration_bytes(root/'.env')
    values = read_configuration(data)
    if not ordinary_directory(root/'trust'):
        raise MaintenanceError('deployment trust must be an ordinary directory')
    expected = {'ca.pem'} if values['CJREPO_CA_SHA256'] else set()
    if {item.name for item in (root/'trust').iterdir()} != expected:
        raise MaintenanceError('deployment trust directory does not match the configuration')
    ca = read_ca(root/'trust/ca.pem') if expected else None
    if ca is not None and hashlib.sha256(ca).hexdigest() != values['CJREPO_CA_SHA256']:
        raise MaintenanceError('deployment CA does not match the configuration')
    return manifest, data, values, ca


def backup(root: Path, output: Path) -> dict:
    require_absent(output)
    manifest, configuration, values, ca = deployment(root)
    project = values['COMPOSE_PROJECT_NAME']
    volume = project + '_cjrepo-data'
    item = json.loads(docker('volume', 'inspect', volume))[0]
    labels = item.get('Labels') or {}
    if (item.get('Name') != volume or labels.get('com.docker.compose.project') != project or
            labels.get('io.cjrepomesh.distribution') != manifest['image']['tag']):
        raise MaintenanceError('source volume identity does not match this deployment')
    require_stopped(volume)
    compose = ('compose', '--project-directory', str(root), '-p', project,
               '-f', str(root/'compose.yaml'), '--env-file', str(root/'.env'))
    effective = json.loads(docker(*compose, 'config', '--format', 'json'))['services']['cjrepo']['environment']
    identifiers = docker(*compose, 'ps', '--all', '--quiet', 'cjrepo').split()
    if len(identifiers) > 1:
        raise MaintenanceError('deployment container identity is ambiguous')
    if identifiers:
        item = json.loads(docker('inspect', *identifiers))[0]
        labels = item.get('Config', {}).get('Labels') or {}
        if (item['Image'] != manifest['image']['id'] or labels.get('com.docker.compose.project') != project or
                labels.get('com.docker.compose.service') != 'cjrepo' or
                not any(mount.get('Name') == volume and mount.get('Destination') == '/var/lib/cjrepo'
                        for mount in item.get('Mounts', []))):
            raise MaintenanceError('stopped container identity does not match this deployment')
        check_running_credentials(item, effective)
    output.mkdir(mode=0o700)
    write_private(output/'.env', configuration)
    if ca is not None:
        (output/'trust').mkdir(mode=0o700)
        write_private(output/'trust/ca.pem', ca)
    with private_file(output/'data.tar') as stream:
        helper(manifest['image']['id'], volume, '/bin/tar', '-C', '/var/lib/cjrepo', '-cf', '-', '.',
               readonly=True, stdout=stream)
    storage = archive_manifest(output/'data.tar')
    require_stopped(volume)
    if read_configuration_bytes(root/'.env') != configuration or (ca is not None and (root/'trust/ca.pem').read_bytes() != ca):
        raise MaintenanceError('deployment configuration changed during backup; retain the failed output')
    names = {'.env', 'data.tar'} | ({'trust/ca.pem'} if ca is not None else set())
    value = dict(formatVersion=1, kind='cjrepomesh-cold-backup',
        createdAtUtc=datetime.now(timezone.utc).isoformat(), image=manifest['image'],
        source=dict(project=project, volume=volume, port=int(values['CJREPO_HOST_PORT'])),
        caSha256=values['CJREPO_CA_SHA256'], storage=storage,
        files={name: dict(bytes=(output/name).stat().st_size, sha256=digest(output/name)) for name in sorted(names)})
    write_private(output/'backup.json', (json.dumps(value, indent=2) + '\n').encode('utf-8'))
    return verify_backup(output)


def create_restore_volume(image: dict, project: str, operation: str) -> str:
    volume = project + '_cjrepo-data'
    if volume in docker('volume', 'ls', '--quiet', '--filter', 'name=' + volume).split():
        raise MaintenanceError('restore volume already exists; no existing volume will be adopted')
    docker('volume', 'create', '--label', 'com.docker.compose.project=' + project,
           '--label', 'com.docker.compose.volume=cjrepo-data',
           '--label', 'io.cjrepomesh.distribution=' + image['tag'],
           '--label', LABEL + '=' + operation, volume)
    inspected = json.loads(docker('volume', 'inspect', volume))[0]
    if (inspected.get('Name') != volume or (inspected.get('Labels') or {}).get(LABEL) != operation):
        raise MaintenanceError('restore volume identity is not newly owned; no extraction was attempted')
    return volume


def restore_inputs(root: Path, source: Path, port: int | None = None) -> tuple[dict, dict]:
    """Validate local inputs only; allocate nothing and never contact Docker."""
    for name in ('.env', 'trust', 'restore.json'):
        require_absent(root/name)
    value = verify_backup(source)
    manifest = verify_bundle(root)
    if manifest.get('maintenance') != CAPABILITY or manifest.get('caConfiguration') != 'pem-directory-v1':
        raise MaintenanceError('target bundle does not support stopped maintenance')
    if manifest['image'] != value['image']:
        raise MaintenanceError('restore requires the exact backed-up image and server identity')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise MaintenanceError('restore port must be between 1 and 65535')
    return manifest, value


def check_restore(root: Path, source: Path, port: int | None = None) -> dict:
    manifest, value = restore_inputs(root, source, port)
    if manifest.get('restorePreflight') != RESTORE_CHECK_CAPABILITY:
        raise MaintenanceError('target bundle does not declare offline restore preflight')
    return dict(formatVersion=1, kind='cjrepomesh-restore-input-check', inputChecksPassed=True,
        imageId=manifest['image']['id'], serverSha256=manifest['image']['serverSha256'],
        port=port if port is not None else int(value['source']['port']), caConfigured=bool(value['caSha256']),
        storageFiles=len(value['storage']['files']),
        storageBytes=sum(item['bytes'] for item in value['storage']['files'].values()),
        dockerChecked=False, targetModified=False, serviceStarted=False)


def restore(root: Path, source: Path, port: int | None = None) -> dict:
    manifest, value = restore_inputs(root, source, port)
    verify_bundle(root, check_docker=True)
    project = 'cjrepomesh-' + secrets.token_hex(8)
    configuration = restored_configuration(read_configuration_bytes(source/'.env'), project, port)
    operation = secrets.token_hex(16)
    # Reserve new configuration first. Failures intentionally retain these files
    # and the new volume; retries use another unconfigured bundle directory.
    write_private(root/'.env', configuration)
    (root/'trust').mkdir(mode=0o755)
    (root/'trust').chmod(0o755)
    if value['caSha256']:
        write_private(root/'trust/ca.pem', (source/'trust/ca.pem').read_bytes())
        (root/'trust/ca.pem').chmod(0o444)
    volume = create_restore_volume(manifest['image'], project, operation)
    require_stopped(volume)
    if helper(manifest['image']['id'], volume, '/bin/ls', '-A', '/var/lib/cjrepo', readonly=False).strip():
        raise MaintenanceError('restore volume is not empty; no extraction was attempted')
    # Revalidate immediately before handing the archive to GNU tar. Both the
    # source directory and Docker administration must remain protected.
    verify_backup(source)
    with (source/'data.tar').open('rb') as stream:
        helper(manifest['image']['id'], volume, '/bin/tar', '-C', '/var/lib/cjrepo',
               '--no-same-owner', '--no-same-permissions', '-xf', '-', readonly=False, stdin=stream)
    require_stopped(volume)
    check = root/('restore-check-' + operation + '.tar')
    with private_file(check) as stream:
        helper(manifest['image']['id'], volume, '/bin/tar', '-C', '/var/lib/cjrepo', '-cf', '-', '.',
               readonly=True, stdout=stream)
    if archive_manifest(check) != value['storage']:
        raise MaintenanceError('restored storage differs; retain the new deployment and check archive for inspection')
    require_stopped(volume)
    result = dict(formatVersion=1, image=manifest['image'], project=project, volume=volume,
                  backupManifestSha256=digest(source/'backup.json'), storage=value['storage'],
                  caSha256=value['caSha256'], serviceStarted=False)
    write_private(root/'restore.json', (json.dumps(result, indent=2) + '\n').encode('utf-8'))
    check.unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('backup', help='requires all deployment writers already stopped').add_argument(
        '--output', type=Path, required=True, help='new private backup directory; existing paths are refused')
    commands.add_parser('verify-backup', help='verify a private backup without Docker').add_argument(
        '--backup', type=Path, required=True)
    restore_parser = commands.add_parser('restore', help='requires an unconfigured copy of the exact bundle')
    restore_parser.add_argument('--backup', type=Path, required=True)
    restore_parser.add_argument('--port', type=int, help='explicitly select a new loopback port')
    restore_parser.add_argument('--check-only', action='store_true',
                                help='check backup and target inputs offline; no Docker or deployment writes')
    args = parser.parse_args()
    try:
        root = Path(__file__).absolute().parent
        if args.command == 'backup':
            backup(root, args.output.absolute())
            print('PASS: stopped private backup verified; original deployment retained')
        elif args.command == 'verify-backup':
            verify_backup(args.backup.absolute())
            print('PASS: backup files and storage integrity; publisher authenticity is not established')
        elif args.check_only:
            print(json.dumps(check_restore(root, args.backup.absolute(), args.port), indent=2))
        else:
            result = restore(root, args.backup.absolute(), args.port)
            print('PASS: restored to new project ' + result['project'] + '; service remains stopped')
            print('Verify configuration, start with explicit Compose files, then test a protected cold build before switching traffic.')
        return 0
    except MaintenanceError as error:
        print('FAIL: ' + str(error))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        print('FAIL: maintenance could not complete; retain existing data and failed output for local inspection')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
