"""Bound manifest allocation in both standalone distribution verifiers."""
from pathlib import Path
import hashlib,io,json,runpy,sys,unittest
from unittest import mock
sys.dont_write_bytecode=True
import test_client_bundle as client
import test_portable_bundle as server
LIMIT=1024*1024

class ManifestCases:
    def fixture(self):
        case=self.fixture_class();case.setUp();self.addCleanup(case.tearDown)
        root=case.root
        verify=runpy.run_path(str(root/'verify.py'))['verify_bundle']
        return root,verify

    def snapshot(self,root):
        return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

    def test_exact_byte_boundary_still_verifies(self):
        root,verify=self.fixture();path=root/'manifest.json';raw=path.read_bytes()
        path.write_bytes(raw+b' '*(LIMIT-len(raw)));before=self.snapshot(root)
        self.assertEqual(path.stat().st_size,LIMIT);self.assertEqual(verify(root)['formatVersion'],1)
        self.assertEqual(self.snapshot(root),before)

    def test_oversize_refused_before_hash_or_docker(self):
        root,verify=self.fixture();path=root/'manifest.json';raw=path.read_bytes()
        path.write_bytes(raw+b' '*(LIMIT+1-len(raw)));before=self.snapshot(root)
        def later(*args,**kwargs):self.fail('oversized manifest reached file hashing or Docker')
        with mock.patch.dict(verify.__globals__,digest=later,docker=later):
            with self.assertRaisesRegex(ValueError,'manifest exceeds byte limit'):verify(root)
        self.assertEqual(self.snapshot(root),before)

    def test_actual_read_is_bounded_even_when_stat_is_small(self):
        root,verify=self.fixture();path=root/'manifest.json';raw=path.read_bytes();requests=[]
        payload=raw+b' '*(LIMIT+1-len(raw));before=self.snapshot(root)
        class Guarded(io.BytesIO):
            def read(stream,size=-1):
                requests.append(size)
                if not 0<=size<=LIMIT+1:raise AssertionError('unbounded manifest read')
                return super().read(size)
        original=Path.open
        def opened(current,*args,**kwargs):
            return Guarded(payload) if current==path else original(current,*args,**kwargs)
        self.assertLess(path.stat().st_size,LIMIT)
        with mock.patch.object(Path,'open',opened):
            with self.assertRaisesRegex(ValueError,'manifest exceeds byte limit'):verify(root)
        self.assertEqual(requests,[LIMIT+1]);self.assertEqual(self.snapshot(root),before)

    def test_limit_counts_utf8_bytes_not_characters(self):
        root,verify=self.fixture();path=root/'manifest.json';data=json.loads(path.read_text(encoding='utf-8'))
        data['note']='界'*(LIMIT//3+1);raw=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.assertLess(len(raw.decode('utf-8')),LIMIT);self.assertGreater(len(raw),LIMIT);path.write_bytes(raw)
        before=self.snapshot(root)
        with self.assertRaisesRegex(ValueError,'manifest exceeds byte limit'):verify(root)
        self.assertEqual(self.snapshot(root),before)

    def test_oversize_cli_is_fixed_and_preserves_inputs(self):
        root,_=self.fixture();path=root/'manifest.json';raw=path.read_bytes();path.write_bytes(raw+b' '*(LIMIT+1-len(raw)))
        before=self.snapshot(root)
        import subprocess
        result=subprocess.run([sys.executable,str(root/'verify.py')],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0);self.assertIn('manifest exceeds byte limit',result.stdout)
        self.assertNotIn('Traceback',result.stderr);self.assertNotIn(str(root),result.stdout+result.stderr)
        self.assertEqual(self.snapshot(root),before)

    def test_small_malformed_input_still_rejected(self):
        root,verify=self.fixture();path=root/'manifest.json'
        for raw in (b'\xff',b'{"synthetic-private-manifest-value":'):
            with self.subTest(raw=raw):
                path.write_bytes(raw);before=self.snapshot(root)
                with self.assertRaises(ValueError):verify(root)
                self.assertEqual(self.snapshot(root),before)

class ClientManifestLimits(ManifestCases,unittest.TestCase):
    fixture_class=client.ClientBundleTests

class ServerManifestLimits(ManifestCases,unittest.TestCase):
    fixture_class=server.PortableBundleTests

if __name__=='__main__':unittest.main()
