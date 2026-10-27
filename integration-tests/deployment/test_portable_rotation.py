"""Offline rotation preparation never applies credentials or changes a live root."""
from pathlib import Path
import hashlib
import importlib.util
import json
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]/'deployment/portable'
PROJECT = 'cjrepomesh-'+'a'*16
CONFIG = (f'COMPOSE_PROJECT_NAME={PROJECT}\nCJREPO_HOST_PORT=18080\n'
          'CJREPO_READ_TOKEN=synthetic-old-read\nCJREPO_PUBLISH_TOKEN=synthetic-old-publish\n'
          'CJREPO_CA_SHA256=\nCJREPO_STORAGE_QUOTA_BYTES=65536\n').encode()


class PortableRotationTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SOURCE)); self.addCleanup(sys.path.remove, str(SOURCE))
        spec = importlib.util.spec_from_file_location('rotation_maintenance', SOURCE/'maintenance.py')
        self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        parent = SOURCE.parents[1]/'integration-tests/.tmp'; parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='rotation-unit-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'deployment'; self.root.mkdir()
        (self.root/'.env').write_bytes(CONFIG); (self.root/'trust').mkdir()
        self.output = Path(self.temp.name)/'prepared'
        self.manifest = dict(image=dict(id='sha256:'+'b'*64),
                             maintenance='cold-backup-v1', caConfiguration='pem-directory-v1')
        self.checked = patch.object(self.module, 'verify_bundle', return_value=self.manifest).start()
        self.addCleanup(patch.stopall)
        self.docker = patch.object(self.module, 'docker', side_effect=AssertionError('offline means no Docker')).start()
        patch.object(self.module, 'protect_windows_file', return_value=None).start()

    def prepare(self, **options):
        self.assertTrue(hasattr(self.module, 'prepare_rotation'), 'rotation preparation is missing')
        return self.module.prepare_rotation(self.root, self.output, **options)

    def test_tokens_replaced_but_identity_port_other_settings_and_source_retained(self):
        value = self.prepare(rotate_tokens=True)
        prepared = self.module.read_configuration((self.output/'.env').read_bytes())
        for key in ('COMPOSE_PROJECT_NAME','CJREPO_HOST_PORT','CJREPO_STORAGE_QUOTA_BYTES'):
            self.assertEqual(prepared[key], self.module.read_configuration(CONFIG)[key])
        for key in ('CJREPO_READ_TOKEN','CJREPO_PUBLISH_TOKEN'):
            self.assertRegex(prepared[key], r'^[a-f0-9]{64}$')
        self.assertNotEqual(prepared['CJREPO_READ_TOKEN'], prepared['CJREPO_PUBLISH_TOKEN'])
        self.assertEqual((self.root/'.env').read_bytes(), CONFIG)
        self.assertFalse(value['runtimeApplied']); self.assertFalse(value['deploymentModified'])
        self.assertNotIn('synthetic-old', json.dumps(value))
        self.assertEqual(self.module.verify_rotation(self.output), value)
        self.docker.assert_not_called()

    def test_ca_only_keeps_tokens_and_validates_pinned_public_pem(self):
        ca = runpy.run_path(str(Path(__file__).with_name('test_portable_ca.py')))['CA']
        if isinstance(ca, str): ca = ca.encode()
        path = Path(self.temp.name)/'next-ca.pem'; path.write_bytes(ca)
        value = self.prepare(ca_file=path)
        prepared = self.module.read_configuration((self.output/'.env').read_bytes())
        self.assertEqual(prepared['CJREPO_READ_TOKEN'], 'synthetic-old-read')
        self.assertEqual(prepared['CJREPO_PUBLISH_TOKEN'], 'synthetic-old-publish')
        self.assertEqual(prepared['CJREPO_CA_SHA256'], hashlib.sha256(ca).hexdigest())
        self.assertEqual((self.output/'trust/ca.pem').read_bytes(), ca)
        self.assertFalse(value['tokensReplaced'])

    def test_all_accepted_configuration_line_endings_actually_replace_tokens(self):
        for ordinal, separator in enumerate((b'\r', '\u0085'.encode('utf-8'))):
            with self.subTest(separator=separator):
                (self.root/'.env').write_bytes(CONFIG.replace(b'\n', separator))
                self.output = Path(self.temp.name)/('prepared-lines-'+str(ordinal))
                value = self.prepare(rotate_tokens=True)
                prepared = self.module.read_configuration((self.output/'.env').read_bytes())
                self.assertTrue(value['tokensReplaced'])
                self.assertNotEqual(prepared['CJREPO_READ_TOKEN'], 'synthetic-old-read')
                self.assertNotEqual(prepared['CJREPO_PUBLISH_TOKEN'], 'synthetic-old-publish')

    def test_no_change_request_refused_before_output_creation(self):
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved(self):
        self.output.mkdir(); (self.output/'marker').write_text('keep')
        with self.assertRaises(ValueError): self.prepare(rotate_tokens=True)
        self.assertEqual((self.output/'marker').read_text(), 'keep')

    def test_output_inside_live_deployment_is_refused(self):
        self.output = self.root/'trust/prepared'
        with self.assertRaises(ValueError): self.prepare(rotate_tokens=True)
        self.assertFalse(self.output.exists())

    def test_invalid_ca_is_rejected_before_output_and_not_echoed(self):
        path = Path(self.temp.name)/'bad.pem'; path.write_text('synthetic-private-key-content')
        with self.assertRaises(ValueError) as caught: self.prepare(ca_file=path)
        self.assertNotIn('synthetic-private', str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_configuration_drift_retains_incomplete_output_but_has_no_valid_receipt(self):
        original = self.module.read_configuration_bytes
        count = 0
        def drift(path):
            nonlocal count
            if path == self.root/'.env':
                count += 1
                if count > 1: return CONFIG.replace(b'18080', b'18081')
            return original(path)
        with patch.object(self.module, 'read_configuration_bytes', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'inputs changed'): self.prepare(rotate_tokens=True)
        self.assertEqual((self.root/'.env').read_bytes(), CONFIG)
        self.assertFalse((self.output/'rotation.json').exists())

    def test_verifier_rejects_changed_configuration_and_extra_file(self):
        self.prepare(rotate_tokens=True)
        before = (self.output/'.env').read_bytes()
        (self.output/'.env').write_bytes(before.replace(b'18080', b'18081'))
        with self.assertRaises(ValueError): self.module.verify_rotation(self.output)
        (self.output/'.env').write_bytes(before)
        (self.output/'unexpected').write_text('extra')
        with self.assertRaises(ValueError): self.module.verify_rotation(self.output)


if __name__ == '__main__': unittest.main()
