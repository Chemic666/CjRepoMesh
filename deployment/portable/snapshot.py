#!/usr/bin/env python3
"""Export, verify and seed one independently approved repository package set."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
import tarfile
from urllib.parse import urlsplit

# Read-only CLI operations must not create import caches in the delivery directory.
sys.dont_write_bytecode = True

from maintenance import (MaintenanceError, archive_manifest, create_restore_volume, deployment,
                         helper, image_identity, ordinary_directory, private_file, require_absent,
                         read_configuration_bytes, require_stopped, verify_backup, write_private)
from verify import digest, regular_file, verify_bundle

CAPABILITY = 'approved-set-v1'
SET_CAPABILITY = 'approved-origins-v2'
SEED_CHECK_CAPABILITY = 'offline-inputs-v1'
SHA256 = r'[a-f0-9]{64}'
SEGMENT = r'[A-Za-z0-9][A-Za-z0-9._+-]*'


class SnapshotError(ValueError):
    """Static diagnostics only: approvals, paths and source metadata are private."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError('duplicate JSON object field')
        result[key] = value
    return result


def parse_json(data: bytes):
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise SnapshotError('invalid or ambiguous JSON metadata') from None


def bounded_bytes(path: Path, limit: int) -> bytes:
    if not regular_file(path) or path.stat().st_size > limit:
        raise SnapshotError('metadata must be a bounded ordinary file')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SnapshotError('metadata exceeds its size limit')
    return data


def package_parts(full: str) -> tuple[str, str]:
    parts = full.split('::')
    if len(parts) == 1:
        org, name = '', parts[0]
    elif (len(parts) == 2 and 3 <= len(parts[0]) <= 64 and
          parts[0].lower() != 'default' and re.fullmatch(r'_*[A-Za-z][_A-Za-z0-9]*', parts[0])):
        org, name = parts
    else:
        raise SnapshotError('invalid package storage identity')
    if len(name) < 3 or not re.fullmatch(SEGMENT, name):
        raise SnapshotError('invalid package storage identity')
    return org, name


def approved_graph(path: Path) -> tuple[bytes, dict[str, dict]]:
    data = bounded_bytes(path, 1024 * 1024)
    value = parse_json(data)
    if (not isinstance(value, dict) or type(value.get('formatVersion')) is not int or
            value['formatVersion'] != 1 or not isinstance(value.get('packages'), list) or not value['packages']):
        raise SnapshotError('approval requires a nonempty provenance-v1 package set')
    entries, repositories = {}, {}
    for entry in value['packages']:
        if (not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) or not entry[key]
                for key in ('package', 'version', 'repository', 'registry', 'sha256')) or
                not re.fullmatch(SEGMENT, entry['version']) or not re.fullmatch(SHA256, entry['sha256'])):
            raise SnapshotError('invalid approval package fields')
        package_parts(entry['package'])
        if entry['package'] in entries:
            raise SnapshotError('duplicate approved package')
        address = entry['registry']
        try:
            url = urlsplit(address)
            if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or
                    url.password is not None or url.query or url.fragment or
                    any(c.isspace() or ord(c) < 32 or c == '\\' for c in address) or
                    (url.port is not None and not 1 <= url.port <= 65535)):
                raise ValueError()
        except ValueError:
            raise SnapshotError('approval registry requires a credential-free HTTP(S) address') from None
        if entry['repository'] in repositories and repositories[entry['repository']] != address:
            raise SnapshotError('one approved repository name identifies multiple registry addresses')
        repositories[entry['repository']] = address
        entries[entry['package']] = entry
    return data, dict(sorted(entries.items()))


def approval(path: Path) -> tuple[bytes, dict[str, dict], str]:
    data, entries = approved_graph(path)
    origins = {entry['registry'] for entry in entries.values()}
    if len(origins) != 1:
        raise SnapshotError('snapshot requires one exact registry origin; no source merging')
    return data, entries, origins.pop()


def storage_paths(entry: dict) -> tuple[str, str]:
    org, name = package_parts(entry['package'])
    version = entry['version']
    org = org or 'default'
    return (f'index/{org}/{name[:2]}/{name[2:4]}/{name}',
            f'artifacts/{org}/{name}/{version}/{name}-{version}.cjp')


def member_map(archive) -> dict:
    # archive_manifest has already rejected links, duplicates and canonical aliases.
    return {PurePosixPath(item.name).as_posix(): item for item in archive if item.isfile()}


def selected_index(archive, member, entry: dict, packages: dict, *, single: bool) -> bytes:
    if member.size > 64 * 1024 * 1024:
        raise SnapshotError('package index exceeds 64 MiB')
    org, name = package_parts(entry['package'])
    selected, versions = None, set()
    with archive.extractfile(member) as stream:
        for line in stream:
            if not line.strip():
                continue
            value = parse_json(line)
            if (not isinstance(value, dict) or value.get('organization') != org or value.get('name') != name or
                    not isinstance(value.get('version'), str) or not re.fullmatch(SEGMENT, value['version']) or
                    value['version'] in versions):
                raise SnapshotError('package index has wrong identity or duplicate versions')
            versions.add(value['version'])
            if value['version'] == entry['version']:
                selected = value
    if (selected is None or (single and versions != {entry['version']}) or
            selected.get('sha256sum') != entry['sha256'] or selected.get('yanked') is not False or
            type(selected.get('index-version')) is not int or selected['index-version'] != 1 or
            not isinstance(selected.get('cjc-version'), str) or not selected['cjc-version']):
        raise SnapshotError('selected package index differs from approval or supported index format')
    for field in ('dependencies', 'test-dependencies', 'script-dependencies'):
        if not isinstance(selected.get(field), list):
            raise SnapshotError('invalid index dependency metadata')
        for dep in selected[field]:
            if (not isinstance(dep, dict) or not isinstance(dep.get('name'), str) or
                    not isinstance(dep.get('require'), str) or not dep['require'] or
                    any(dep.get(key) is not None and not isinstance(dep[key], str)
                        for key in ('target', 'type', 'output-type'))):
                raise SnapshotError('invalid index dependency metadata')
            package_parts(dep['name'])
            if (field == 'dependencies' and dep.get('target') is None and dep.get('type') is None and
                    dep['name'] not in packages):
                raise SnapshotError('approved set is missing an unconditional runtime dependency')
    return (json.dumps(selected, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')


def selected_files(archive, members: dict, storage: dict, entries: dict, *, single: bool,
                   full_graph: dict | None = None) -> dict[str, bytes]:
    indexes = {}
    for entry in entries.values():
        index, artifact = storage_paths(entry)
        if index not in members or artifact not in members:
            raise SnapshotError('approved package is missing from stored index or artifacts')
        if storage['files'][artifact]['sha256'] != entry['sha256']:
            raise SnapshotError('stored artifact differs from independently approved SHA-256')
        indexes[index] = selected_index(archive, members[index], entry,
                                        entries if full_graph is None else full_graph, single=single)
    return indexes


def expected_directories(paths) -> list[str]:
    return sorted({parent.as_posix() for path in paths for parent in PurePosixPath(path).parents
                   if parent.as_posix() != '.'})


def require_external_output(output: Path, backups) -> None:
    require_absent(output)
    if any(output.resolve().is_relative_to(backup.resolve()) for backup in backups):
        raise SnapshotError('snapshot output must be outside all source backups')


def preflight(backup: Path, entries: dict, full_graph: dict) -> tuple[dict, dict]:
    source = verify_backup(backup)
    with tarfile.open(backup/'data.tar', 'r:') as archive:
        indexes = selected_files(archive, member_map(archive), source['storage'], entries,
                                 single=False, full_graph=full_graph)
    return source, indexes


def write_snapshot(backup: Path, source: dict, approved: bytes, entries: dict, indexes: dict,
                   registry: str, output: Path, *, version: int) -> None:
    with tarfile.open(backup/'data.tar', 'r:') as archive:
        members = member_map(archive)
        paths = sorted(path for entry in entries.values() for path in storage_paths(entry))
        output.mkdir(mode=0o700)
        with private_file(output/'data.tar') as stream, tarfile.open(fileobj=stream, mode='w:') as target:
            for name in expected_directories(paths):
                item = tarfile.TarInfo(name); item.type = tarfile.DIRTYPE; item.mode = 0o755
                target.addfile(item)
            for name in paths:
                item = tarfile.TarInfo(name); item.mode = 0o644
                item.uid = item.gid = 10001
                if name in indexes:
                    item.size = len(indexes[name]); target.addfile(item, io.BytesIO(indexes[name]))
                else:
                    item.size = members[name].size
                    with archive.extractfile(members[name]) as content:
                        target.addfile(item, content)
    storage = archive_manifest(output/'data.tar')
    value = dict(formatVersion=version, kind='cjrepomesh-dependency-snapshot',
        createdAtUtc=datetime.now(timezone.utc).isoformat(), registry=registry, image=source['image'],
        baselineSha256=hashlib.sha256(approved).hexdigest(), storage=storage,
        files={'data.tar': dict(bytes=(output/'data.tar').stat().st_size, sha256=digest(output/'data.tar'))})
    if version == 2:
        value['selection'] = 'exact-registry-v1'
    write_private(output/'snapshot.json', (json.dumps(value, indent=2) + '\n').encode('utf-8'))


def export_snapshot(backup: Path, baseline: Path, output: Path) -> dict:
    require_external_output(output, [backup])
    approved, entries, registry = approval(baseline)
    source, indexes = preflight(backup, entries, entries)
    write_snapshot(backup, source, approved, entries, indexes, registry, output, version=1)
    return verify_snapshot(output, baseline)


def verify_snapshot(root: Path, baseline: Path) -> dict:
    if (not root.is_dir() or not ordinary_directory(root) or
            {item.name for item in root.iterdir()} != {'snapshot.json', 'data.tar'}):
        raise SnapshotError('snapshot requires exactly its manifest and data archive')
    value = parse_json(bounded_bytes(root/'snapshot.json', 16 * 1024 * 1024))
    if (not isinstance(value, dict) or type(value.get('formatVersion')) is not int or
            value['formatVersion'] not in (1, 2)):
        raise SnapshotError('unsupported snapshot format')
    if value['formatVersion'] == 1:
        approved, entries, registry = approval(baseline)
        full_graph = entries
    else:
        approved, full_graph = approved_graph(baseline)
        registry = value.get('registry')
        if not isinstance(registry, str) or value.get('selection') != 'exact-registry-v1':
            raise SnapshotError('invalid snapshot origin selection')
        entries = {name: entry for name, entry in full_graph.items() if entry['registry'] == registry}
        if not entries:
            raise SnapshotError('snapshot origin is absent from independent approval')
    if (
            value.get('kind') != 'cjrepomesh-dependency-snapshot' or value.get('registry') != registry or
            value.get('baselineSha256') != hashlib.sha256(approved).hexdigest() or
            not isinstance(value.get('files'), dict) or set(value['files']) != {'data.tar'}):
        raise SnapshotError('snapshot identity or independent approval differs')
    image_identity(value.get('image'))
    recorded, path = value['files']['data.tar'], root/'data.tar'
    if (not isinstance(recorded, dict) or not regular_file(path) or type(recorded.get('bytes')) is not int or
            recorded['bytes'] != path.stat().st_size or recorded.get('sha256') != digest(path)):
        raise SnapshotError('snapshot data archive integrity differs')
    storage = archive_manifest(path)
    paths = {path for entry in entries.values() for path in storage_paths(entry)}
    if (value.get('storage') != storage or set(storage['files']) != paths or
            storage['directories'] != expected_directories(paths)):
        raise SnapshotError('snapshot storage is not exactly the independently approved set')
    with tarfile.open(path, 'r:') as archive:
        selected_files(archive, member_map(archive), storage, entries, single=True, full_graph=full_graph)
    return value


def export_set(backups: dict[str, Path], baseline: Path, output: Path) -> dict:
    require_external_output(output, backups.values())
    approved, full_graph = approved_graph(baseline)
    repositories = {entry['repository']: entry['registry'] for entry in full_graph.values()}
    origins = {entry['registry'] for entry in full_graph.values()}
    sources = {}
    for name, backup in backups.items():
        if name not in repositories or repositories[name] in sources:
            raise SnapshotError('each approved original registry requires exactly one source backup')
        sources[repositories[name]] = backup
    if set(sources) != origins:
        raise SnapshotError('source backups do not exactly cover all approved registry origins')
    prepared = []
    for registry in sorted(origins):
        entries = {name: entry for name, entry in full_graph.items() if entry['registry'] == registry}
        source, indexes = preflight(sources[registry], entries, full_graph)
        prepared.append((registry, entries, source, indexes))
    # Every origin passed before output exists. Later failures retain partial
    # output; protect backups, approval and Docker administration from mutation.
    output.mkdir(mode=0o700)
    components = []
    for number, (registry, entries, source, indexes) in enumerate(prepared, 1):
        directory = f'origin-{number:04d}'
        write_snapshot(sources[registry], source, approved, entries, indexes, registry, output/directory, version=2)
        components.append(dict(directory=directory, registry=registry,
                               snapshotManifestSha256=digest(output/directory/'snapshot.json')))
    value = dict(formatVersion=1, kind='cjrepomesh-dependency-snapshot-set',
        createdAtUtc=datetime.now(timezone.utc).isoformat(),
        baselineSha256=hashlib.sha256(approved).hexdigest(), origins=components)
    write_private(output/'snapshot-set.json', (json.dumps(value, indent=2)+'\n').encode('utf-8'))
    return verify_set(output, baseline)


def verify_set(root: Path, baseline: Path) -> dict:
    approved, full_graph = approved_graph(baseline)
    if not root.is_dir() or not ordinary_directory(root):
        raise SnapshotError('snapshot set requires an ordinary directory')
    value = parse_json(bounded_bytes(root/'snapshot-set.json', 16 * 1024 * 1024))
    if (not isinstance(value, dict) or type(value.get('formatVersion')) is not int or value['formatVersion'] != 1 or
            value.get('kind') != 'cjrepomesh-dependency-snapshot-set' or
            value.get('baselineSha256') != hashlib.sha256(approved).hexdigest() or
            not isinstance(value.get('origins'), list)):
        raise SnapshotError('snapshot set format or complete independent approval differs')
    directories, origins = set(), set()
    for origin in value['origins']:
        if (not isinstance(origin, dict) or not isinstance(origin.get('directory'), str) or
                not re.fullmatch(r'origin-[0-9]{4}', origin['directory']) or
                not isinstance(origin.get('registry'), str) or
                not isinstance(origin.get('snapshotManifestSha256'), str) or
                not re.fullmatch(SHA256, origin['snapshotManifestSha256']) or
                origin['directory'] in directories or origin['registry'] in origins):
            raise SnapshotError('snapshot set has invalid or duplicate origin bindings')
        directories.add(origin['directory']); origins.add(origin['registry'])
    if (origins != {entry['registry'] for entry in full_graph.values()} or
            {path.name for path in root.iterdir()} != directories | {'snapshot-set.json'}):
        raise SnapshotError('snapshot set does not exactly cover the complete approved origins')
    for origin in value['origins']:
        child = root/origin['directory']
        selected = verify_snapshot(child, baseline)
        if (selected['formatVersion'] != 2 or selected['registry'] != origin['registry'] or
                digest(child/'snapshot.json') != origin['snapshotManifestSha256']):
            raise SnapshotError('snapshot set component binding differs')
    return value


def seed_inputs(root: Path, source: Path, baseline: Path, *, check_docker: bool) -> tuple:
    # Invalid input is rejected before any Docker invocation or target mutation.
    value = verify_snapshot(source, baseline)
    require_absent(root/'snapshot-import.json')
    manifest = verify_bundle(root)
    capability = manifest.get('dependencySnapshot')
    if (capability not in (CAPABILITY, SET_CAPABILITY) or
            (value['formatVersion'] == 2 and capability != SET_CAPABILITY)):
        raise SnapshotError('target bundle does not support approved dependency snapshots')
    if manifest['image'] != value['image']:
        raise SnapshotError('snapshot seed requires the exact exported image and server identity')
    _, configuration, values, _ = deployment(root, check_docker=check_docker)
    if values.get('CJREPO_UPSTREAM') or values.get('CJREPO_UPSTREAM_TOKEN'):
        raise SnapshotError('snapshot seed requires a new Hosted configuration without an upstream')
    return manifest, value, configuration, values


def check_seed(root: Path, source: Path, baseline: Path) -> dict:
    """Inspect local inputs only; never contact Docker or modify a target."""
    manifest, value, _, _ = seed_inputs(root, source, baseline, check_docker=False)
    if manifest.get('snapshotSeedPreflight') != SEED_CHECK_CAPABILITY:
        raise SnapshotError('target bundle does not declare offline snapshot seed preflight')
    return dict(formatVersion=1, kind='cjrepomesh-snapshot-seed-input-check', inputChecksPassed=True,
        imageId=manifest['image']['id'], serverSha256=manifest['image']['serverSha256'],
        storageFiles=len(value['storage']['files']),
        storageBytes=sum(item['bytes'] for item in value['storage']['files'].values()),
        dockerChecked=False, targetModified=False, serviceStarted=False)


def seed(root: Path, source: Path, baseline: Path) -> dict:
    manifest, value, configuration, values = seed_inputs(root, source, baseline, check_docker=True)
    project, operation = values['COMPOSE_PROJECT_NAME'], secrets.token_hex(16)
    volume = create_restore_volume(manifest['image'], project, operation)
    require_stopped(volume)
    if helper(manifest['image']['id'], volume, '/bin/ls', '-A', '/var/lib/cjrepo', readonly=False).strip():
        raise SnapshotError('new snapshot volume is not empty; no extraction attempted')
    verify_snapshot(source, baseline)
    with (source/'data.tar').open('rb') as stream:
        helper(manifest['image']['id'], volume, '/bin/tar', '-C', '/var/lib/cjrepo',
               '--no-same-owner', '--no-same-permissions', '-xf', '-', readonly=False, stdin=stream)
    require_stopped(volume)
    check = root/('snapshot-check-' + operation + '.tar')
    with private_file(check) as stream:
        helper(manifest['image']['id'], volume, '/bin/tar', '-C', '/var/lib/cjrepo', '-cf', '-', '.',
               readonly=True, stdout=stream)
    if archive_manifest(check) != value['storage'] or read_configuration_bytes(root/'.env') != configuration:
        raise SnapshotError('seeded storage or configuration differs; retain failed target for inspection')
    require_stopped(volume)
    result = dict(formatVersion=1, project=project, volume=volume, image=manifest['image'],
        snapshotManifestSha256=digest(source/'snapshot.json'), baselineSha256=value['baselineSha256'],
        registry=value['registry'], storage=value['storage'], serviceStarted=False)
    write_private(root/'snapshot-import.json', (json.dumps(result, indent=2)+'\n').encode('utf-8'))
    check.unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='select approved packages from a verified stopped backup')
    export.add_argument('--backup', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True, help='new private output directory')
    export_group = commands.add_parser('export-set', help='preserve every original registry of a full approved graph')
    export_group.add_argument('--source', nargs=2, action='append', required=True, metavar=('REPOSITORY', 'BACKUP_DIR'))
    export_group.add_argument('--output', type=Path, required=True)
    verify_group = commands.add_parser('verify-set', help='verify complete origin coverage and all components')
    verify_group.add_argument('--snapshot-set', type=Path, required=True)
    for name in ('verify', 'seed'):
        commands.add_parser(name).add_argument('--snapshot', type=Path, required=True)
    commands.choices['seed'].add_argument('--check-only', action='store_true',
        help='validate local inputs without Docker or target writes; does not establish runtime readiness')
    for command in (export, export_group, verify_group, *[commands.choices[name] for name in ('verify', 'seed')]):
        command.add_argument('--baseline', type=Path, required=True, help='external independently approved file')
    args = parser.parse_args()
    try:
        if args.command == 'export':
            export_snapshot(args.backup.absolute(), args.baseline.absolute(), args.output.absolute())
            print('PASS: selected dependency snapshot exported; configuration and unrelated packages excluded')
        elif args.command == 'export-set':
            sources = {name: Path(path).absolute() for name, path in args.source}
            if len(sources) != len(args.source):
                raise SnapshotError('duplicate source repository mapping')
            export_set(sources, args.baseline.absolute(), args.output.absolute())
            print('PASS: complete approved origin set exported; original registry identities preserved')
        elif args.command == 'verify-set':
            verify_set(args.snapshot_set.absolute(), args.baseline.absolute())
            print('PASS: complete approved origin coverage and each selected artifact verified')
        elif args.command == 'verify':
            verify_snapshot(args.snapshot.absolute(), args.baseline.absolute())
            print('PASS: snapshot matches the external approval and selected artifact hashes')
        else:
            if args.check_only:
                result = check_seed(Path(__file__).absolute().parent, args.snapshot.absolute(), args.baseline.absolute())
                print(json.dumps(result, indent=2))
                return 0
            result = seed(Path(__file__).absolute().parent, args.snapshot.absolute(), args.baseline.absolute())
            print('PASS: snapshot seeded to new project volume ' + result['project'] + '; service remains stopped')
        print('Integrity does not authenticate publishers or certify a build; verify a protected cold build before use.')
        return 0
    except (SnapshotError, MaintenanceError) as error:
        print('FAIL: ' + str(error))
    except (OSError, ValueError, KeyError, TypeError, RecursionError, tarfile.TarError,
            RuntimeError, subprocess.SubprocessError):
        print('FAIL: snapshot operation could not complete; retain inputs and failed output for local inspection')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
