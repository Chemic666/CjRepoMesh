"""Optional CA import must preserve deployments and diagnose the actual mounted bytes."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_portable_bundle as bundle_tests
import portable_ca

# Public synthetic certificate only. Its generating private key was deleted.
CA = b"""-----BEGIN CERTIFICATE-----
MIIDLzCCAhegAwIBAgIUH52NgorTWU+MUDQOcyuVS0LA5m4wDQYJKoZIhvcNAQEL
BQAwJzElMCMGA1UEAwwcQ2pSZXBvTWVzaCBzeW50aGV0aWMgdW5pdCBDQTAeFw0y
NjEwMjIwMzE4MzVaFw0zNjEwMTkwMzE4MzVaMCcxJTAjBgNVBAMMHENqUmVwb01l
c2ggc3ludGhldGljIHVuaXQgQ0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEK
AoIBAQC5hysPYcjvmtzO1xJYT2mKTMKnj52vW6NRrXpZoE0uA9Wogt8M20ozo1EX
IZjM+TUHoDskWsKvOig440xvlDaBdoT87m4R4gnYj5F13jQWr3Exh3xeeZeM9t8O
YOmu0xba9O63LiVdg4J/vz+Wd+kWEnu9KloV+VgkFpDYAu4w19nQY5nuXOeGUzEc
Ax/6DdR3OZQ8SlaC0kwbSgjJhwS1J8uN0ppWRem05BX0jE33/KPn5P1ky18YXmfT
zRQ7rYq2Oep2XijEQLs+7qjL9WE6N45+7fsleUIFG41PbdVem1/k6RTTwoUtw2wL
FY3f6pMO4YkAuOBys7I1gB36uPZtAgMBAAGjUzBRMB0GA1UdDgQWBBRYLGYcHRcw
W0fjOmKRB3AM5YHQ7jAfBgNVHSMEGDAWgBRYLGYcHRcwW0fjOmKRB3AM5YHQ7jAP
BgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQCrxTaPZQcoHM5mjtbz
CK0OJDFwd89tiVFmhBn6ML/TTTddYqIMY70TVrYyGtrbLjU+KYCo7DeshWhAqeHj
YES1QbVMBDnyFhV5iaewykrOTn53L7chSblh+D4sLUB0A+S2TUBVjhiNGmPFj55E
KUFccIN2z6laVnimgbedUy81ZpbkUCz9j0w+KFX0Vj+otf9D8dmUgrwzq/Dipumq
QtI3Y4Xlz769zTs9YT0dhgTFp7EdVpLkakqJXTDZerN43mu85XSbObR3Jo2T52XE
bIzJ0sSnRdWe21FO7TyGgYgoZ4t7H9SULokYwbUtiPCouVI4cbnVjKbzk5KPQzyC
vFhT
-----END CERTIFICATE-----
"""


class PortableCATests(unittest.TestCase):
    setUp = bundle_tests.PortableBundleTests.setUp
    tearDown = bundle_tests.PortableBundleTests.tearDown
    write_manifest = bundle_tests.PortableBundleTests.write_manifest
    run_script = bundle_tests.PortableBundleTests.run_script

    def input_ca(self):
        path = self.root/'input-ca.pem'; path.write_bytes(CA)
        return path

    def test_import_copies_only_public_ca_and_records_its_digest(self):
        source = self.input_ca()
        result = self.run_script('configure.py', '--ca-file', str(source))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(source.read_bytes(), CA)
        self.assertEqual((self.root/'trust/ca.pem').read_bytes(), CA)
        values = dict(line.split('=',1) for line in (self.root/'.env').read_text().splitlines())
        self.assertEqual(values['CJREPO_CA_SHA256'], hashlib.sha256(CA).hexdigest())
        self.assertNotIn('BEGIN CERTIFICATE', result.stdout+result.stderr)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE((self.root/'trust').stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((self.root/'trust/ca.pem').stat().st_mode), 0o444)

    def test_default_hosted_setup_has_an_empty_trust_directory(self):
        result = self.run_script('configure.py')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue((self.root/'trust').is_dir())
        self.assertEqual(list((self.root/'trust').iterdir()), [])
        self.assertIn('CJREPO_CA_SHA256=\n', (self.root/'.env').read_text())

    def test_bad_ca_inputs_are_rejected_before_creating_runtime_state(self):
        bad = self.root/'invalid.pem'
        for payload in (b'', b'synthetic-private-value', CA+b'-----BEGIN PRIVATE KEY-----\nsynthetic-private-value\n', b'x'*(1024*1024+1)):
            with self.subTest(length=len(payload)):
                bad.write_bytes(payload)
                result = self.run_script('configure.py', '--ca-file', str(bad))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root/'.env').exists())
                self.assertFalse((self.root/'trust').exists())
                self.assertNotIn('synthetic-private-value', result.stdout+result.stderr)

    def test_missing_ca_is_rejected_without_runtime_state(self):
        result = self.run_script('configure.py', '--ca-file', str(self.root/'missing.pem'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'.env').exists())
        self.assertFalse((self.root/'trust').exists())

    def test_existing_trust_directory_is_never_overwritten(self):
        trust = self.root/'trust'; trust.mkdir(); (trust/'keep').write_bytes(b'owned-by-another-setup')
        result = self.run_script('configure.py', '--ca-file', str(self.input_ca()))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'.env').exists())
        self.assertEqual({p.name:p.read_bytes() for p in trust.iterdir()}, {'keep':b'owned-by-another-setup'})

    def test_reconfigure_preserves_existing_ca_and_credentials(self):
        result = self.run_script('configure.py', '--ca-file', str(self.input_ca()))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        before = (self.root/'.env').read_bytes()
        result = self.run_script('configure.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root/'.env').read_bytes(), before)
        self.assertEqual((self.root/'trust/ca.pem').read_bytes(), CA)

    def test_selected_ca_link_is_rejected(self):
        target = self.input_ca(); link = self.root/'ca-link'
        try: link.symlink_to(target)
        except OSError: self.skipTest('symlinks unavailable')
        result = self.run_script('configure.py', '--ca-file', str(link))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'.env').exists())
        self.assertEqual(target.read_bytes(), CA)

    def runtime(self):
        (self.root/'trust').mkdir(); (self.root/'trust/ca.pem').write_bytes(CA)
        digest = hashlib.sha256(CA).hexdigest()
        (self.root/'.env').write_text('CJREPO_CA_SHA256='+digest+'\n')
        item = dict(Config=dict(Env=['SSL_CERT_FILE=/run/cjrepo-trust/ca.pem', 'CJREPO_CA_SHA256='+digest]),
                    Mounts=[dict(Type='bind', Destination='/run/cjrepo-trust', RW=False)])
        functions = runpy.run_path(str(self.root/'verify.py'))
        self.assertIn('check_running_trust', functions, 'CA runtime verification is not implemented')
        return functions['check_running_trust'], item, digest

    def check_runtime(self, function, item, digest):
        def docker(*args):
            if args == ('exec', 'fixture-id', '/bin/ls', '-A', '/run/cjrepo-trust'): return 'ca.pem\n'
            if args == ('exec', 'fixture-id', 'sha256sum', '/run/cjrepo-trust/ca.pem'): return digest+'  /run/cjrepo-trust/ca.pem\n'
            raise AssertionError('CA diagnostics must only read the intended directory and digest')
        with patch.dict(function.__globals__, docker=docker): function(self.root, item, 'fixture-id')

    def test_correct_ca_runtime_is_accepted(self):
        function,item,digest = self.runtime(); self.check_runtime(function,item,digest)

    def test_changed_host_ca_is_rejected(self):
        function,item,digest = self.runtime(); (self.root/'trust/ca.pem').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.check_runtime(function,item,digest)

    def test_missing_writable_or_wrong_kind_mount_is_rejected(self):
        function,item,digest = self.runtime()
        for mounts in ([], [dict(Type='bind',Destination='/run/cjrepo-trust',RW=True)],
                       [dict(Type='volume',Destination='/run/cjrepo-trust',RW=False)]):
            with self.subTest(mounts=mounts):
                changed=deepcopy(item); changed['Mounts']=mounts
                with self.assertRaises(ValueError): self.check_runtime(function,changed,digest)

    def test_changed_container_ca_is_rejected(self):
        function,item,digest = self.runtime()
        with self.assertRaises(ValueError): self.check_runtime(function,item,'f'*64)

    def test_duplicate_or_missing_ca_metadata_is_rejected(self):
        function,item,digest = self.runtime()
        for text in ('', 'CJREPO_CA_SHA256='+digest+'\nCJREPO_CA_SHA256='+digest+'\n', 'CJREPO_CA_SHA256=synthetic-private-value\n'):
            with self.subTest(text=text):
                (self.root/'.env').write_text(text)
                with self.assertRaises(ValueError) as caught: self.check_runtime(function,item,digest)
                self.assertNotIn('synthetic-private-value', str(caught.exception))

    def test_new_bundle_cannot_use_legacy_exemption_when_both_markers_are_missing(self):
        function,item,digest = self.runtime(); item['Config']['Env'] = []
        (self.root/'.env').write_text('')
        with self.assertRaises(ValueError): function(self.root,item,'fixture-id',required=True)

    def configuration_functions(self):
        sys.path.insert(0,str(self.root))
        try: return runpy.run_path(str(self.root/'configure.py'))
        finally: sys.path.pop(0)

    def test_initialization_failure_removes_only_this_attempts_files(self):
        source = self.input_ca(); functions = self.configuration_functions(); original = Path.chmod
        def fail_ca(path, *args, **kwargs):
            if path == self.root/'trust/ca.pem': raise OSError('synthetic chmod failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'chmod',fail_ca):
            with self.assertRaises((OSError,RuntimeError)): functions['configure'](self.root,18080,source)
        self.assertFalse((self.root/'.env').exists())
        self.assertFalse((self.root/'trust').exists())
        self.assertEqual(source.read_bytes(),CA)

    def test_failure_cleanup_retains_an_unrelated_new_file(self):
        source = self.input_ca(); functions = self.configuration_functions(); original = Path.chmod
        def fail_ca(path, *args, **kwargs):
            if path == self.root/'trust/ca.pem':
                (self.root/'trust/keep').write_bytes(b'unrelated')
                raise OSError('synthetic chmod failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'chmod',fail_ca):
            with self.assertRaises((OSError,RuntimeError)): functions['configure'](self.root,18080,source)
        self.assertFalse((self.root/'.env').exists())
        self.assertEqual((self.root/'trust/keep').read_bytes(),b'unrelated')

    def test_fixture_timeout_error_hides_tokens_in_the_command(self):
        error = subprocess.TimeoutExpired(['docker','create','--env','FIXTURE_TOKEN=synthetic-private-value'], 10)
        text = portable_ca.safe_error(error, ['synthetic-private-value'])
        self.assertNotIn('synthetic-private-value', text)
        self.assertIn('TimeoutExpired', text)
        self.assertIn('create', text)


if __name__ == '__main__': unittest.main()
