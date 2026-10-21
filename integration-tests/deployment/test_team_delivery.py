"""Delivered client preflight must finish before Docker or evidence writes."""
from pathlib import Path
import hashlib
import json
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'integration-tests/deployment/portable.py'


class TeamDeliveryTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='team-delivery-', dir=parent)
        self.work = Path(self.temporary.name)
        self.bundle = self.work / 'client bundle'
        (self.bundle / 'lib').mkdir(parents=True)
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HH', header, 16, 3, 62)
        names = runpy.run_path(str(ROOT / 'deployment/client/verify.py'))['FILES']
        for name in names:
            # The candidate's own verifier must never be imported or executed.
            payload = (bytes(header) if name == 'cjpm' or name.endswith('.so') else
                       b"raise RuntimeError('untrusted verifier executed')\n")
            (self.bundle / name).write_bytes(payload)
        files = {name: dict(bytes=(self.bundle / name).stat().st_size,
                 sha256=hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()) for name in names}
        (self.bundle / 'manifest.json').write_text(json.dumps(dict(formatVersion=1,
            platform=dict(os='linux', architecture='amd64'), files=files)))
        self.functions = runpy.run_path(str(SCRIPT))

    def tearDown(self):
        self.temporary.cleanup()

    def identity(self):
        self.assertTrue('client_bundle_identity' in self.functions,
                        'receiver lacks delivered client verification')
        return self.functions['client_bundle_identity'](self.bundle)

    def invoke(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), '--bundle', str(self.work / 'server'),
            '--package-dir', str(self.work / 'package'), '--evidence-dir', str(self.work / 'evidence'),
            *map(str, arguments)], capture_output=True, text=True, timeout=15)

    def test_verified_identity_does_not_execute_candidate_verifier(self):
        identity = self.identity()
        self.assertEqual(identity['mode'], 'client-bundle')
        self.assertEqual(identity['binarySha256'], hashlib.sha256((self.bundle / 'cjpm').read_bytes()).hexdigest())
        self.assertEqual(identity['manifestSha256'], hashlib.sha256((self.bundle / 'manifest.json').read_bytes()).hexdigest())

    def test_modified_runtime_rejected(self):
        (self.bundle / 'lib/libboundscheck.so').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.identity()

    def test_extra_credential_file_rejected(self):
        (self.bundle / '.env').write_text('SYNTHETIC=do-not-read')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.identity()

    def test_bundle_requires_sdk_before_side_effects(self):
        result = self.invoke('--team-client-bundle', self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be supplied together', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_raw_client_and_bundle_are_mutually_exclusive(self):
        result = self.invoke('--team-client-bundle', self.bundle, '--team-client', self.work / 'cjpm')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not allowed with argument', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())

    def test_corrupt_bundle_rejected_before_evidence_creation(self):
        sdk = self.work / 'sdk'
        sdk.mkdir()
        (sdk / 'envsetup.sh').write_text('# synthetic; never executed\n')
        (self.bundle / 'cjpm').write_bytes(b'corrupt')
        result = self.invoke('--team-sdk', sdk, '--team-client-bundle', self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('integrity', result.stderr)
        self.assertFalse((self.work / 'evidence').exists())


if __name__ == '__main__':
    unittest.main()
