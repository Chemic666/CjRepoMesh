"""Fresh CI workspaces are explicitly claimed once and never silently reset."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / 'examples/team/prepare.py'
GUARD = ROOT / 'examples/team/job.py'


class SingleUseTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='single-use-', dir=parent)
        self.root = Path(self.temp.name) / 'task'
        self.private = 'synthetic-private-do-not-echo'

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, role='consumer', single=True):
        return subprocess.run([sys.executable, str(PREPARE), '--role', role, '--registry',
            'http://127.0.0.1:18080', '--output', str(self.root), *(['--single-use'] if single else [])],
            capture_output=True, text=True, timeout=15)

    def owned_root(self):
        self.root.mkdir()
        (self.root / '.home').mkdir()
        (self.root / 'cangjie-repo.toml').write_text('[repository.cache]\npath = "cache"\n')
        return hashlib.sha256((self.root / 'cangjie-repo.toml').read_bytes()).hexdigest()

    def claim(self, digest, env=None):
        with patch.dict(os.environ, {'CJREPOMESH_SOURCE_BASELINE': '/protected/approved.json'} if env is None else env, clear=True):
            runpy.run_path(str(GUARD))['claim'](self.root, digest)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_cli_prepares_pinned_consumer_without_credentials(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        meta = json.loads((self.root / 'workspace.json').read_text())
        expected = hashlib.sha256((self.root / 'cangjie-repo.toml').read_bytes()).hexdigest()
        self.assertEqual(meta['execution'], {'mode': 'single-use-cold-v1', 'configurationSha256': expected})
        self.assertTrue((self.root / 'job.py').is_file())
        script = (self.root / 'run.sh').read_text()
        self.assertIn(expected, script)
        self.assertLess(script.index('job.py'), script.index('"$CJREPOMESH_CJPM" build'))
        self.assertNotIn(self.private, self.snapshot().__repr__())
        self.assertFalse((self.root / '.cjrepomesh-job-started').exists())

    def test_default_consumer_has_no_guard_or_claim(self):
        result = self.prepare(single=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('execution', json.loads((self.root / 'workspace.json').read_text()))
        self.assertFalse((self.root / 'job.py').exists())

    def test_publisher_refused_before_output(self):
        result = self.prepare(role='publisher')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('consumer', result.stdout + result.stderr)
        self.assertFalse(self.root.exists())

    def test_helper_copy_failure_does_not_expose_run_entry(self):
        api = runpy.run_path(str(PREPARE))['prepare']
        import shutil
        original = shutil.copyfile
        def fail(source, target, *args, **kwargs):
            if Path(target).name == 'job.py':
                Path(target).write_bytes(b'partial helper')
                raise OSError('owned synthetic copy failure')
            return original(source, target, *args, **kwargs)
        with patch.object(shutil, 'copyfile', side_effect=fail):
            with self.assertRaises(OSError):
                api('consumer', 'http://127.0.0.1:18080', self.root, single_use=True)
        self.assertEqual((self.root / 'job.py').read_bytes(), b'partial helper')
        self.assertFalse((self.root / 'run.sh').exists())

    def test_claim_preserves_inputs_and_is_not_reusable(self):
        digest = self.owned_root()
        before = self.snapshot()
        self.claim(digest)
        self.assertTrue((self.root / '.cjrepomesh-job-started').is_dir())
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError):
            self.claim(digest)
        self.assertEqual(self.snapshot(), before)

    def test_missing_or_empty_main_baseline_refused_before_claim(self):
        digest = self.owned_root()
        for env in ({}, {'CJREPOMESH_SOURCE_BASELINE': ''}):
            with self.subTest(env=bool(env)), self.assertRaises(ValueError):
                self.claim(digest, env)
            self.assertFalse((self.root / '.cjrepomesh-job-started').exists())

    def test_modified_configuration_refused_without_changes(self):
        digest = self.owned_root()
        (self.root / 'cangjie-repo.toml').write_text(self.private)
        before = self.snapshot()
        with self.assertRaises(ValueError) as failure:
            self.claim(digest)
        self.assertNotIn(self.private, str(failure.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / '.cjrepomesh-job-started').exists())

    def test_each_preexisting_output_refused_and_preserved(self):
        digest = self.owned_root()
        for name in ('cache', 'target', 'build', 'build-script-cache', 'cjpm.lock',
                     'cjpm-provenance.json', 'cjpm-provenance.json.tmp', 'build.cj.bak'):
            with self.subTest(name=name):
                item = self.root / name
                item.write_text(self.private)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.claim(digest)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / '.cjrepomesh-job-started').exists())
                item.unlink()

    def test_nonempty_home_refused_and_preserved(self):
        digest = self.owned_root()
        (self.root / '.home/keep').write_text(self.private)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.claim(digest)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == 'nt', 'symlink creation needs separate Windows privilege')
    def test_configuration_link_refused_without_reading_target(self):
        digest = self.owned_root()
        config = self.root / 'cangjie-repo.toml'
        config.rename(self.root / 'original-config')
        config.symlink_to('original-config')
        with self.assertRaises(ValueError):
            self.claim(digest)
        self.assertTrue(config.is_symlink())
        self.assertFalse((self.root / '.cjrepomesh-job-started').exists())

    @unittest.skipIf(os.name == 'nt', 'symlink creation needs separate Windows privilege')
    def test_home_link_refused_without_changes(self):
        digest = self.owned_root()
        (self.root / '.home').rename(self.root / 'original-home')
        (self.root / '.home').symlink_to('original-home', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.claim(digest)
        self.assertTrue((self.root / '.home').is_symlink())
        self.assertFalse((self.root / '.cjrepomesh-job-started').exists())

    @unittest.skipIf(os.name == 'nt', 'symlink creation needs separate Windows privilege')
    def test_dangling_cache_link_refused_without_creating_target(self):
        digest = self.owned_root()
        (self.root / 'cache').symlink_to(self.root / 'missing', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.claim(digest)
        self.assertTrue((self.root / 'cache').is_symlink())
        self.assertFalse((self.root / 'missing').exists())

    def test_concurrent_real_process_claims_have_one_winner(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = hashlib.sha256((self.root / 'cangjie-repo.toml').read_bytes()).hexdigest()
        env = dict(os.environ, CJREPOMESH_SOURCE_BASELINE='/protected/approved.json')
        command = [sys.executable, str(self.root / 'job.py'), '--configuration-sha256', digest]
        def invoke(_):
            return subprocess.run(command, env=env, capture_output=True, text=True, timeout=15).returncode
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sorted(pool.map(invoke, range(4))), [0, 2, 2, 2])

    @unittest.skipUnless(os.name == 'posix', 'actual Bash execution is Linux-only')
    def test_failed_build_keeps_claim_and_repeat_never_builds(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        fake = Path(self.temp.name) / 'fake-client'
        fake.write_text('#!/bin/sh\nif [ "$1" = repo ] && [ "$2" = supports ]; then echo "$3"; exit 0; fi\necho build >> "$PWD/build-calls"\nexit 7\n')
        fake.chmod(0o700)
        env = dict(os.environ, CJREPOMESH_CJPM=str(fake), CJREPO_READ_TOKEN=self.private,
                   CJREPOMESH_SOURCE_BASELINE='/protected/approved.json')
        first = subprocess.run(['bash', 'run.sh'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 7, first.stdout + first.stderr)
        self.assertTrue((self.root / '.cjrepomesh-job-started').is_dir())
        second = subprocess.run(['bash', 'run.sh'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        self.assertEqual((self.root / 'build-calls').read_text(), 'build\n')
        self.assertNotIn(self.private, first.stdout + first.stderr + second.stdout + second.stderr)

    @unittest.skipUnless(os.name == 'posix', 'actual Bash execution is Linux-only')
    def test_application_failure_preserves_seven_and_claim(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        fake = Path(self.temp.name) / 'fake-client'
        fake.write_text('#!/bin/sh\nif [ "$1" = repo ] && [ "$2" = supports ]; then echo "$3"; exit 0; fi\n'
            'echo "$1" >> "$PWD/client-calls"\nmkdir -p target/release/bin\n'
            'printf "#!/bin/sh\\nexit 7\\n" > target/release/bin/main\nchmod +x target/release/bin/main\n')
        fake.chmod(0o700)
        env = dict(os.environ, CJREPOMESH_CJPM=str(fake), CJREPO_READ_TOKEN=self.private,
                   CJREPOMESH_SOURCE_BASELINE='/protected/approved.json')
        result = subprocess.run(['bash', 'run.sh'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual((self.root / 'client-calls').read_text(), 'build\n')
        self.assertTrue((self.root / '.cjrepomesh-job-started').is_dir())

    @unittest.skipUnless(os.name == 'posix', 'Linux-only acceptance runner')
    def test_losing_evidence_creator_cannot_overwrite_winner_summary(self):
        evidence = Path(self.temp.name) / 'competing-evidence'
        work = Path(self.temp.name) / 'acceptance-work'
        expected = b'{"owner":"winning invocation","passed":9}\n'
        # Simulate another creator winning between this runner's lstat and mkdir.
        script = textwrap.dedent('''
            from pathlib import Path
            import runpy,sys
            from unittest.mock import patch
            runner,evidence,work=sys.argv[1:]
            evidence=Path(evidence)
            original=Path.mkdir
            def race(path,*args,**kwargs):
                if path==evidence:
                    original(path,*args,**kwargs)
                    (path/'summary.json').write_bytes(b'{"owner":"winning invocation","passed":9}\\n')
                    raise FileExistsError('owned synthetic evidence race')
                return original(path,*args,**kwargs)
            sys.argv=[runner,'--client-bundle','unused-client','--server','unused-server',
                      '--evidence-dir',str(evidence),'--work-dir',work]
            with patch.object(Path,'mkdir',race):
                runpy.run_path(runner,run_name='__main__')
        ''')
        result = subprocess.run([sys.executable, '-c', script,
            str(ROOT / 'integration-tests/compatibility/team_single_use.py'), str(evidence), str(work)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((evidence / 'summary.json').read_bytes(), expected)
        self.assertFalse(work.exists())


if __name__ == '__main__':
    unittest.main()
