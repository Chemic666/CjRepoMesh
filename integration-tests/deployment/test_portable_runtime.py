"""Running-deployment diagnostics must reject mismatched container metadata."""
from copy import deepcopy
from pathlib import Path
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import runpy
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.functions = runpy.run_path(str(ROOT / 'deployment/portable/verify.py'))
        self.project = 'cjrepomesh-' + 'a' * 16
        self.image = dict(id='sha256:' + 'b' * 64, tag='cjrepomesh-portable:sha256-' + 'b' * 64)
        self.container = dict(Image=self.image['id'], State=dict(Running=True, Health=dict(Status='healthy')),
            Config=dict(User='10001:10001', Labels={'com.docker.compose.project': self.project,
                'com.docker.compose.service': 'cjrepo', 'io.cjrepomesh.distribution': self.image['tag']},
                Env=['CJREPO_READ_TOKEN=synthetic-read', 'CJREPO_PUBLISH_TOKEN=synthetic-publish']),
            HostConfig=dict(ReadonlyRootfs=True, CapDrop=['ALL'], SecurityOpt=['no-new-privileges:true']),
            NetworkSettings=dict(Ports={'8080/tcp': [dict(HostIp='127.0.0.1', HostPort='18080')]}),
            Mounts=[dict(Type='volume', Destination='/var/lib/cjrepo', Name=self.project+'_cjrepo-data', RW=True)])

    def check(self, container):
        self.assertTrue('check_running_container' in self.functions, 'running diagnostics not implemented')
        self.functions['check_running_container'](container, self.image, self.project, 18080)

    def test_matching_container_is_accepted(self):
        self.check(self.container)

    def test_wrong_image_is_rejected(self):
        self.container['Image'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.check(self.container)

    def test_other_project_or_service_is_rejected(self):
        for key in ('com.docker.compose.project', 'com.docker.compose.service', 'io.cjrepomesh.distribution', None):
            with self.subTest(key=key):
                item = deepcopy(self.container)
                if key is None: item['Config']['Labels'] = None
                else: item['Config']['Labels'][key] = 'another'
                with self.assertRaisesRegex(ValueError, 'identity'):
                    self.check(item)

    def test_stopped_or_unhealthy_container_is_rejected(self):
        for state in (dict(Running=False), dict(Running=True, Health=dict(Status='unhealthy'))):
            with self.subTest(state=state):
                self.container['State'] = state
                with self.assertRaisesRegex(ValueError, 'healthy'):
                    self.check(self.container)

    def test_extra_or_public_port_binding_is_rejected(self):
        for binding in ({'8080/tcp': [dict(HostIp='0.0.0.0', HostPort='18080')]},
                        {**self.container['NetworkSettings']['Ports'], '9000/tcp': [dict(HostIp='127.0.0.1', HostPort='9000')]}):
            self.container['NetworkSettings']['Ports'] = binding
            with self.assertRaisesRegex(ValueError, 'binding'):
                self.check(self.container)

    def test_wrong_data_volume_is_rejected(self):
        self.container['Mounts'][0]['Name'] = 'another-project-data'
        with self.assertRaisesRegex(ValueError, 'volume'):
            self.check(self.container)

    def test_relaxed_runtime_constraints_are_rejected(self):
        for section, key, value in (('Config', 'User', 'root'), ('HostConfig', 'ReadonlyRootfs', False),
                                    ('HostConfig', 'CapDrop', []), ('HostConfig', 'SecurityOpt', []),
                                    ('HostConfig', 'CapDrop', None), ('HostConfig', 'SecurityOpt', None),
                                    ('HostConfig', 'CapAdd', ['SYS_ADMIN']), ('HostConfig', 'Privileged', True)):
            with self.subTest(key=key):
                item = deepcopy(self.container)
                item[section][key] = value
                with self.assertRaisesRegex(ValueError, 'constraints'):
                    self.check(item)

    def test_absent_read_or_publish_token_is_rejected_without_echo(self):
        for missing in ('CJREPO_READ_TOKEN', 'CJREPO_PUBLISH_TOKEN'):
            item = deepcopy(self.container)
            item['Config']['Env'] = [value for value in item['Config']['Env'] if not value.startswith(missing+'=')]
            with self.assertRaisesRegex(ValueError, 'credentials') as caught:
                self.check(item)
            self.assertNotIn('synthetic-', str(caught.exception))

    def test_duplicate_or_invalid_runtime_config_is_rejected(self):
        self.assertTrue('runtime_configuration' in self.functions, 'runtime configuration reader not implemented')
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='portable-runtime-', dir=parent) as temporary:
            folder = Path(temporary)
            for text in ('COMPOSE_PROJECT_NAME=other\nCJREPO_HOST_PORT=18080\n',
                         'COMPOSE_PROJECT_NAME='+self.project+'\nCJREPO_HOST_PORT=65536\n',
                         'COMPOSE_PROJECT_NAME='+self.project+'\nCJREPO_HOST_PORT=18080\nCJREPO_HOST_PORT=18081\n'):
                (folder/'.env').write_text(text+'CJREPO_READ_TOKEN=synthetic-secret\n')
                with self.assertRaisesRegex(ValueError, 'configuration') as caught:
                    self.functions['runtime_configuration'](folder)
                self.assertNotIn('synthetic-secret', str(caught.exception))

    def health_failure(self, redirect=False):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302 if redirect and self.path == '/health' else 200)
                if redirect and self.path == '/health':
                    self.send_header('Location', '/redirect-target')
                self.end_headers()
                self.wfile.write(b'{"status":"ok","service":"cjrepo"}' if redirect else b'synthetic-private-detail')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        port = server.server_port
        item = deepcopy(self.container)
        item['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort'] = str(port)
        manifest = dict(image={**self.image, 'serverSha256': 'd' * 64})
        def docker(*args):
            if args[0] == 'compose': return 'e' * 64
            if args[0] == 'inspect': return json.dumps([item])
            if args[:2] == ('volume', 'inspect'): return json.dumps([dict(Labels=item['Config']['Labels'])])
            if args[0] == 'exec' and args[2:] == ('sha256sum', '/usr/local/bin/cjrepo'): return 'd' * 64 + '  /usr/local/bin/cjrepo'
            raise AssertionError('diagnostics must not mutate Docker resources')
        parent = ROOT / 'integration-tests/.tmp'
        parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix='runtime-health-', dir=parent) as temporary:
                folder = Path(temporary)
                (folder/'.env').write_text('COMPOSE_PROJECT_NAME='+self.project+'\nCJREPO_HOST_PORT='+str(port)+'\n')
                function = self.functions['verify_running']
                with patch.dict(function.__globals__, docker=docker):
                    with self.assertRaisesRegex(ValueError, 'health check failed') as caught:
                        function(folder, manifest)
                self.assertNotIn('synthetic-private-detail', str(caught.exception))
        finally:
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()
        self.assertEqual(requests, ['/health'])

    def test_health_redirect_is_rejected_without_following(self):
        self.health_failure(redirect=True)

    def test_health_failure_does_not_echo_response_body(self):
        self.health_failure()


if __name__ == '__main__':
    unittest.main()
