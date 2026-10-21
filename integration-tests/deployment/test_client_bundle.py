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
