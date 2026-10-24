"""Optional upgrade clients must fail safely before Docker side effects."""
import importlib.util
import hashlib
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

    def test_single_use_requires_bundle_before_fixture_or_docker(self):
        self.assertIn('single-use-clients requires client-bundle', self.invoke('--single-use-clients'))

    def single_use_consumer(self, *, replay_exit=2, mutate=False, replay_output=None):
        spec = importlib.util.spec_from_file_location('upgrade_client', SCRIPT.with_name('upgrade_client.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        registered, commands, starts = [], [], []
        job = self.work / 'consumer-probe/job'
        approval = self.work / 'consumer-probe/approved-source.json'
        seed = dict(name='meshdep', organization='', version='1.0.0', sha256='a' * 64)
        def docker(*args, **kwargs):
            commands.append(args)
            if args[0] == 'create':
                self.assertTrue((job / 'job.py').is_file())
                digest = hashlib.sha256((job / 'cangjie-repo.toml').read_bytes()).hexdigest()
                self.assertIn('python3 /job/job.py --configuration-sha256 ' + digest, args[-1])
                self.assertLess(args[-1].index('/job/job.py'), args[-1].index('/client/run.sh build'))
                self.assertIn('unset CJREPO_READ_TOKEN CJREPO_PUBLISH_TOKEN', args[-1])
                self.assertIn('getVariable("CJREPO_READ_TOKEN")', (job / 'src/main.cj').read_text())
                return b'owned-consumer\n'
            self.assertEqual(registered, ['owned-consumer'])
            starts.append(args)
            if len(starts) == 1:
                (job / '.cjrepomesh-job-started').mkdir()
                (job / 'target').mkdir()
                (job / 'target/keep').write_bytes(b'build-output')
                (job / 'cjpm-provenance.json').write_bytes(approval.read_bytes())
                return ('PASS: client bundle integrity; cjpm SHA-256 ' + 'b' * 64 +
                        '\nsource-baseline-v1\nhigh-1.0.0\n').encode()
            if mutate:
                (job / 'target/keep').write_bytes(b'changed')
            return (replay_output if replay_output is not None else
                    'FAIL: single-use task contains previous cache or build state; prepare a new task\n').encode()
        def inspect(_):
            return {'State': {'Running': False, 'ExitCode': 0 if len(starts) == 1 else replay_exit}}
        facts = module.consume(name='probe', server='owned-server', image='fixed-image',
            packages=[seed], args=SimpleNamespace(client_bundle=self.work / 'bundle',
                client_sdk=self.sdk, client_native=self.native, expected_output='high-1.0.0', single_use_clients=True),
            manifest={'files': {'cjpm': {'sha256': 'b' * 64}}}, report=self.work,
            docker=docker, inspect=inspect, register=registered.append,
            label_key='owned-label', scope='owned-scope', secret_values=['synthetic-secret'])
        self.assertEqual(len(starts), 2)
        self.assertEqual(registered, ['owned-consumer'])
        self.assertNotIn('synthetic-secret', str(commands))
        self.assertEqual(facts['singleUseReplay']['exitCode'], 2)
        self.assertTrue(facts['singleUseReplay']['taskStateUnchanged'])
        self.assertTrue(facts['applicationCredentialsAbsent'])
        return facts

    def test_single_use_reuses_guard_and_preserves_completed_task(self):
        self.single_use_consumer()

    def test_repeat_success_is_not_guard_refusal(self):
        with self.assertRaisesRegex(ValueError, 'repeat did not refuse'):
            self.single_use_consumer(replay_exit=0)

    def test_repeat_unrelated_failure_is_not_guard_refusal(self):
        with self.assertRaisesRegex(ValueError, 'repeat did not refuse'):
            self.single_use_consumer(replay_output='some unrelated error')

    def test_repeat_must_preserve_all_task_bytes(self):
        with self.assertRaisesRegex(ValueError, 'repeat changed'):
            self.single_use_consumer(mutate=True)

    def test_repeat_must_not_run_application(self):
        with self.assertRaisesRegex(ValueError, 'repeat did not refuse'):
            self.single_use_consumer(replay_output='FAIL: single-use task refused\nhigh-1.0.0\n')

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

    def test_only_explicit_replay_exit_is_permitted_by_subprocess_adapter(self):
        sys.path.insert(0, str(SCRIPT.parent))
        try:
            spec = importlib.util.spec_from_file_location('upgrade_drill', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(SCRIPT.parent))
        command = [sys.executable, '-c', 'print("controlled guard refusal"); raise SystemExit(2)']
        self.assertIn(b'controlled guard refusal', module.docker_output(command,
            environment=dict(os.environ), allowed_exit_codes=(0, 2)))
        with self.assertRaises(module.TestFailure):
            module.docker_output(command, environment=dict(os.environ))


if __name__ == '__main__':
    unittest.main()
