"""Container client argument checks must precede Docker and evidence creation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'integration-tests/recovery/docker_backup.py'


class DockerClientTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='backup-client-', dir=parent)
        self.work = Path(self.temporary.name)
        self.sdk = self.work / 'sdk'
        self.sdk.mkdir()
        (self.sdk / 'envsetup.sh').write_text('# synthetic, never executed\n')

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        result = subprocess.run([sys.executable, str(SCRIPT), '--image', 'not-contacted',
            '--evidence-dir', str(self.work / 'evidence'), *map(str, arguments)],
            capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / 'evidence').exists())
        return result.stderr

    def test_native_client_and_bundle_are_mutually_exclusive(self):
        self.assertIn('not allowed with argument', self.invoke('--cjpm', self.work / 'cjpm',
                      '--client-bundle', self.work / 'bundle'))

    def test_bundle_requires_existing_sdk(self):
        self.assertIn('client-bundle requires an existing client-sdk',
                      self.invoke('--client-bundle', self.work / 'bundle'))

    def test_bundle_is_verified_before_side_effects(self):
        self.assertIn('invalid client bundle', self.invoke('--client-bundle', self.work / 'bundle',
                      '--client-sdk', self.sdk))

    def test_native_mode_rejects_container_only_tools(self):
        self.assertIn('client-sdk/client-native require client-bundle', self.invoke('--cjpm',
                      self.work / 'cjpm', '--client-sdk', self.sdk))

    def test_legacy_missing_client_still_rejected(self):
        self.assertIn('build the enhanced cjpm first', self.invoke('--cjpm', self.work / 'missing'))


if __name__ == '__main__':
    unittest.main()
