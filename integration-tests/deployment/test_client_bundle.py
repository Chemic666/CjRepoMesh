"""Offline client delivery contracts; synthetic ELF files are never executed."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'deployment/client'
FILES = {'cjpm', 'lib/libcangjie-runtime.so', 'lib/libboundscheck.so',
         'run.sh', 'verify.py', 'README.md', 'LICENSE'}
TEAM = {'prepare-team.py', 'team/prepare.py', 'team/trust.py', 'team/job.py', 'team/README.md'}
TEAM |= {'team/' + role + '/' + name for role in ('publisher', 'consumer')
         for name in ('cjpm.toml', 'README.md', 'run.sh')}
TEAM |= {'team/consumer/src/main.cj', 'team/publisher/src/teamhello.cj'}


def elf(machine=62):
    data = bytearray(64)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', data, 16, 3, machine)
    return bytes(data) + b'synthetic fixture, never executable'


class ClientBundleTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE.parents[1] / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='client-bundle-', dir=parent)
        self.work = Path(self.temporary.name)
        self.root = self.work / 'receiver'
        (self.root / 'lib').mkdir(parents=True)
        for name in FILES:
            target = self.root / name
            if name == 'verify.py':
                if (SOURCE / name).is_file(): shutil.copyfile(SOURCE / name, target)
                else: target.write_text("raise SystemExit('Client verifier not implemented')\n")
            else: target.write_bytes(elf() if name == 'cjpm' or name.endswith('.so') else b'fixture\n')
        self.manifest = dict(formatVersion=1, platform=dict(os='linux', architecture='amd64'), files={})
        self.manifest_write()

    def tearDown(self): self.temporary.cleanup()

    def manifest_write(self):
        self.manifest['files'] = {name: dict(bytes=(self.root / name).stat().st_size,
            sha256=hashlib.sha256((self.root / name).read_bytes()).hexdigest()) for name in FILES}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def verify(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'verify.py'), *args],
                              capture_output=True, text=True, timeout=20)

    def test_valid_receiver_verifies_without_sdk_or_docker(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_corrupt_client_is_rejected(self):
        (self.root / 'cjpm').write_bytes(elf() + b'changed')
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('integrity', result.stdout + result.stderr)

    def test_manifest_cannot_select_external_paths(self):
        self.manifest['files']['../outside'] = dict(bytes=0, sha256='0' * 64)
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('file list', result.stdout + result.stderr)

    def test_unknown_version_and_boolean_version_are_rejected(self):
        for version in (2, True):
            with self.subTest(version=version):
                self.manifest['formatVersion'] = version
                (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
                result = self.verify()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('version', result.stdout + result.stderr)

    def test_foreign_elf_cannot_be_relabelled_amd64(self):
        (self.root / 'cjpm').write_bytes(elf(183))
        self.manifest_write()
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ELF', result.stdout + result.stderr)

    def test_extra_credential_file_is_rejected(self):
        (self.root / '.env').write_text('SYNTHETIC_SECRET=do-not-copy')
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected', result.stdout + result.stderr)
        self.assertNotIn('do-not-copy', result.stdout + result.stderr)

    def test_runtime_directory_symlink_is_rejected(self):
        original = self.root / 'lib'
        alternate = self.work / 'alternate-lib'
        original.rename(alternate)
        try: original.symlink_to(alternate, target_is_directory=True)
        except OSError as error: self.skipTest('symlink unavailable: ' + type(error).__name__)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular', result.stdout + result.stderr)

    def package(self, output, *extra):
        return subprocess.run([sys.executable, str(SOURCE / 'package.py'),
            '--cjpm', str(self.root / 'cjpm'), '--runtime-dir', str(self.root / 'lib'),
            '--output', str(output), *map(str, extra)], capture_output=True, text=True, timeout=30)

    def test_maker_copies_only_whitelist_and_records_client(self):
        (self.root / 'lib' / '.env').write_text('not-for-delivery')
        output = self.work / 'new-output'
        result = self.package(output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
        self.assertEqual(actual, FILES | {'manifest.json'})
        self.assertEqual((output / 'cjpm').read_bytes(), (self.root / 'cjpm').read_bytes())

    def test_maker_preserves_existing_output(self):
        output = self.work / 'existing'
        output.mkdir()
        (output / 'keep').write_text('keep')
        result = self.package(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('new directory', result.stdout + result.stderr)
        self.assertEqual((output / 'keep').read_text(), 'keep')

    def team_kit(self):
        output = self.work / 'kit'
        result = self.package(output, '--include-team')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def prepare_kit(self, kit, output=None, *extra):
        return subprocess.run([sys.executable, str(kit / 'prepare-team.py'), '--role', 'consumer',
            '--registry', 'https://registry.example.invalid', '--output', str(output or self.work / 'task'),
            '--single-use', *extra], capture_output=True, text=True, timeout=20,
            env={k: v for k, v in os.environ.items() if not k.upper().startswith(('CJREPO', 'CJPM', 'CANGJIE'))})

    def test_team_kit_records_exact_approved_file_set(self):
        kit = self.team_kit()
        manifest = json.loads((kit / 'manifest.json').read_text())
        self.assertEqual(manifest['capabilities'], {'teamPreparation': 'single-use-cold-v1'})
        self.assertEqual(set(manifest['files']), FILES | TEAM)
        self.assertEqual({p.relative_to(kit).as_posix() for p in kit.rglob('*') if p.is_file()},
                         FILES | TEAM | {'manifest.json'})

    def test_team_kit_prepares_after_relocation_without_sdk_or_bytecode_writes(self):
        kit = self.team_kit()
        moved = self.work / 'moved-kit'
        kit.rename(moved)
        before = {p.relative_to(moved).as_posix(): p.read_bytes() for p in moved.rglob('*') if p.is_file()}
        result = self.prepare_kit(moved)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        task = self.work / 'task'
        self.assertTrue((task / 'job.py').is_file())
        self.assertTrue((task / 'run.sh').is_file())
        self.assertEqual(json.loads((task / 'workspace.json').read_text())['execution']['mode'], 'single-use-cold-v1')
        self.assertEqual(before, {p.relative_to(moved).as_posix(): p.read_bytes() for p in moved.rglob('*') if p.is_file()})
        self.assertFalse((task / 'cjpm-provenance.json').exists())
        self.assertFalse(any(moved.rglob('__pycache__')))

    def test_team_entry_verifies_preparer_before_loading_it(self):
        kit = self.team_kit()
        (kit / 'team/prepare.py').write_text('raise RuntimeError("untrusted-code-must-not-run")\n')
        result = self.prepare_kit(kit)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('untrusted-code-must-not-run', result.stdout + result.stderr)
        self.assertFalse((self.work / 'task').exists())

    def test_read_only_templates_produce_editable_task_sources(self):
        kit = self.team_kit()
        source = kit / 'team/consumer/src'
        (source / 'main.cj').chmod(0o444)
        source.chmod(0o555)
        result = self.prepare_kit(kit)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        task_source = self.work / 'task/src'
        # A new task is editable even when the delivery is mounted read-only.
        (task_source / 'main.cj').write_text('owned custom task code\n')
        (task_source / 'new.cj').write_text('owned new module\n')
        self.assertEqual((task_source / 'main.cj').read_text(), 'owned custom task code\n')

    def test_team_entry_verifies_binary_and_guard_before_preparation(self):
        for name in ('cjpm', 'team/job.py'):
            with self.subTest(name=name):
                kit = self.team_kit()
                original = (kit / name).read_bytes()
                (kit / name).write_bytes(original + b'corruption')
                result = self.prepare_kit(kit)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.work / 'task').exists())
                shutil.rmtree(kit)

    def test_team_entry_refuses_tasks_inside_the_kit(self):
        kit = self.team_kit()
        result = self.prepare_kit(kit, kit / 'task')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((kit / 'task').exists())

    def test_team_entry_rejects_missing_template(self):
        kit = self.team_kit()
        (kit / 'team/publisher/src/teamhello.cj').unlink()
        result = self.prepare_kit(kit)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / 'task').exists())

    def test_team_entry_rejects_unlisted_private_file(self):
        kit = self.team_kit()
        (kit / 'team/.env').write_text('synthetic-private-do-not-echo')
        result = self.prepare_kit(kit)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('synthetic-private-do-not-echo', result.stdout + result.stderr)
        self.assertFalse((self.work / 'task').exists())

    def test_team_manifest_cannot_omit_capability_or_select_an_unknown_one(self):
        kit = self.team_kit()
        manifest = json.loads((kit / 'manifest.json').read_text())
        for marker in (None, {}, {'teamPreparation': 'future'}, {'untrusted': 'anything'}):
            with self.subTest(marker=marker):
                if marker is None:
                    manifest.pop('capabilities', None)
                else:
                    manifest['capabilities'] = marker
                (kit / 'manifest.json').write_text(json.dumps(manifest))
                result = self.prepare_kit(kit)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.work / 'task').exists())

    def test_team_nested_directory_link_is_rejected(self):
        kit = self.team_kit()
        original = kit / 'team/consumer/src'
        alternate = self.work / 'alternate-src'
        original.rename(alternate)
        try:
            original.symlink_to(alternate, target_is_directory=True)
        except OSError as error:
            self.skipTest('symlink unavailable: ' + type(error).__name__)
        result = self.prepare_kit(kit)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / 'task').exists())

    def test_maker_rejects_foreign_input_before_creating_output(self):
        (self.root / 'lib/libboundscheck.so').write_bytes(elf(183))
        output = self.work / 'invalid-output'
        result = self.package(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ELF', result.stdout + result.stderr)
        self.assertFalse(output.exists())

    def test_linked_verifier_cannot_validate_another_bundle(self):
        trusted = self.work / 'other-bundle'
        shutil.copytree(self.root, trusted)
        verifier = self.root / 'verify.py'
        verifier.unlink()
        try: verifier.symlink_to(trusted / 'verify.py')
        except OSError as error: self.skipTest('symlink unavailable: ' + type(error).__name__)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('integrity', result.stdout + result.stderr)

    def test_maker_refuses_existing_dangling_output_link(self):
        output, target = self.work / 'output-link', self.work / 'uncreated-target'
        try: output.symlink_to(target, target_is_directory=True)
        except OSError as error: self.skipTest('symlink unavailable: ' + type(error).__name__)
        result = self.package(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('new directory', result.stdout + result.stderr)
        self.assertFalse(target.exists())


if __name__ == '__main__': unittest.main()
