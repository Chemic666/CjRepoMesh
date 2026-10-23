"""Optional upgrade clients must fail safely before Docker side effects."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'integration-tests/recovery/upgrade.py'


class UpgradeClientTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='upgrade-client-', dir=parent)
        self.work = Path(self.temp.name)
        self.sdk = self.work / 'sdk'
        self.sdk.mkdir()
        (self.sdk / 'envsetup.sh').write_text('# synthetic, never executed\n')
        self.native = self.work / 'native'
        (self.native / 'bin').mkdir(parents=True)
        for name in ('ar', 'ld'):
            (self.native / 'bin' / name).write_text('synthetic, never executed\n')

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *extra):
        result = subprocess.run([sys.executable, str(SCRIPT), '--previous-image', 'not-contacted-old',
            '--candidate-image', 'not-contacted-new', '--seed-package', str(self.work / 'missing-seed'),
            '--new-package', str(self.work / 'missing-addition'), '--evidence-dir', str(self.work / 'evidence'),
            *map(str, extra)], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / 'evidence').exists())
        return result.stderr

    def test_sdk_requires_client_bundle_before_fixture_or_docker(self):
        self.assertIn('client-sdk/client-native require client-bundle', self.invoke('--client-sdk', self.sdk))

    def test_native_tools_require_bundle_before_fixture_or_docker(self):
        self.assertIn('client-sdk/client-native require client-bundle', self.invoke('--client-native', self.native))

    def test_bundle_requires_existing_sdk(self):
        self.assertIn('client-bundle requires an existing client-sdk', self.invoke('--client-bundle', self.work / 'bundle'))

    def test_bundle_requires_native_link_tools(self):
        self.assertIn('client-bundle requires existing client-native ar/ld', self.invoke('--client-bundle', self.work / 'bundle', '--client-sdk', self.sdk))

    def test_full_bundle_verified_before_evidence_or_docker(self):
        self.assertIn('invalid client bundle', self.invoke('--client-bundle', self.work / 'bundle',
                      '--client-sdk', self.sdk, '--client-native', self.native))

    def test_started_consumer_is_already_registered_when_start_fails(self):
        spec = importlib.util.spec_from_file_location('upgrade_client', SCRIPT.with_name('upgrade_client.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registered = []
        commands = []
        seed = dict(name='meshdep', organization='', version='1.0.0', sha256='a' * 64)
        def docker(*args, **kwargs):
            commands.append(args)
            if args[0] == 'create':
                return b'owned-consumer\n'
            self.assertEqual(registered, ['owned-consumer'])
            raise RuntimeError('controlled start failure')
        with self.assertRaisesRegex(RuntimeError, 'controlled start failure'):
            module.consume(name='probe', server='owned-server', image='fixed-image',
                packages=[seed], args=SimpleNamespace(client_bundle=self.work / 'bundle',
                    client_sdk=self.sdk, client_native=self.native, expected_output='high-1.0.0'),
                manifest={'files': {'cjpm': {'sha256': 'b' * 64}}}, report=self.work,
                docker=docker, inspect=lambda _: {}, register=registered.append,
                label_key='owned-label', scope='owned-scope', secret_values=['synthetic-secret'])
        self.assertEqual(registered, ['owned-consumer'])
        self.assertNotIn('synthetic-secret', str(commands))
        self.assertIn('container:owned-server', commands[0])
        self.assertIn('CJREPO_READ_TOKEN', commands[0])
        self.assertNotIn('CJREPO_PUBLISH_TOKEN', commands[0])
        self.assertNotIn('synthetic-secret', (self.work / 'consumer-probe/job/cangjie-repo.toml').read_text())

    def test_real_subprocess_keeps_binary_stdout_separate_unless_requested(self):
        spec = importlib.util.spec_from_file_location('upgrade_drill', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(SCRIPT.parent))
        command = [sys.executable, '-c', 'import os; os.write(1,b"archive\\x00bytes"); os.write(2,b"integrity-marker")']
        self.assertEqual(module.docker_output(command, environment=dict(os.environ)), b'archive\x00bytes')
        combined = module.docker_output(command, environment=dict(os.environ), include_stderr=True)
        self.assertIn(b'archive\x00bytes', combined)
        self.assertIn(b'integrity-marker', combined)


if __name__ == '__main__':
    unittest.main()
