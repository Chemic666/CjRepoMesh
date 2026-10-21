"""Receiver-side delivery contracts using only synthetic bundle files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "deployment" / "portable"
NAMES = ("image.tar", "compose.yaml", "configure.py", "verify.py", "README.md", "LICENSE")


class PortableBundleTests(unittest.TestCase):
    def setUp(self):
        temporary_parent = SOURCE.parents[1] / "integration-tests" / ".tmp"
        temporary_parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="portable-unit-", dir=temporary_parent)
        self.root = Path(self.temporary.name)
        for name in NAMES:
            source = SOURCE / name
            if source.is_file():
                shutil.copyfile(source, self.root / name)
            else:
                (self.root / name).write_bytes(b"raise SystemExit('Receiver script is not implemented')\n"
                                              if name.endswith('.py') else b"synthetic bundle fixture\n")
        self.manifest = dict(formatVersion=1, image=dict(
            id="sha256:" + "a" * 64, tag="cjrepomesh-portable:sha256-" + "a" * 64,
            os="linux", architecture="amd64", serverSha256="b" * 64), files={})
        self.write_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        self.manifest["files"] = {name: dict(bytes=(self.root/name).stat().st_size,
            sha256=hashlib.sha256((self.root/name).read_bytes()).hexdigest()) for name in NAMES}
        (self.root/"manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def run_script(self, name, *arguments):
        return subprocess.run((sys.executable, str(self.root/name), *arguments), cwd=self.root,
                              capture_output=True, text=True, timeout=30)

    def test_receiver_setup_creates_private_config(self):
        result = self.run_script("configure.py", "--port", "18743")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        env = dict(line.split("=", 1) for line in (self.root/".env").read_text().splitlines())
        self.assertEqual(env["CJREPO_HOST_PORT"], "18743")
        self.assertRegex(env["COMPOSE_PROJECT_NAME"], r"^cjrepomesh-[a-f0-9]{16}$")
        for field in ("CJREPO_PUBLISH_TOKEN", "CJREPO_READ_TOKEN"):
            self.assertRegex(env[field], r"^[a-f0-9]{64}$")
            self.assertNotIn(env[field], result.stdout + result.stderr)
        self.assertNotEqual(env["CJREPO_PUBLISH_TOKEN"], env["CJREPO_READ_TOKEN"])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.root/".env").stat().st_mode), 0o600)

    def test_reconfigure_preserves_credentials(self):
        first = self.run_script("configure.py")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (self.root/".env").read_bytes()
        second = self.run_script("configure.py", "--port", "18744")
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((self.root/".env").read_bytes(), before)

    def test_corrupt_image_rejected_before_configuration(self):
        (self.root/"image.tar").write_bytes(b"damaged archive")
        result = self.run_script("configure.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/".env").exists())
        self.assertIn("integrity", result.stdout + result.stderr)

    def test_valid_bundle_verifies_without_docker(self):
        result = self.run_script("verify.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_unexpected_manifest_path_rejected(self):
        self.manifest["files"]["../outside"] = dict(bytes=0, sha256="0" * 64)
        (self.root/"manifest.json").write_text(json.dumps(self.manifest))
        result = self.run_script("verify.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("file list", result.stdout + result.stderr)

    def test_unknown_manifest_version_rejected(self):
        self.manifest["formatVersion"] = 2
        self.write_manifest()
        result = self.run_script("verify.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("version", result.stdout + result.stderr)

    def test_malformed_manifest_root_rejected(self):
        (self.root/"manifest.json").write_text("[]")
        result = self.run_script("verify.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_file_descriptor_rejected(self):
        self.manifest["files"]["image.tar"] = "invalid"
        (self.root/"manifest.json").write_text(json.dumps(self.manifest))
        result = self.run_script("verify.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_port_leaves_no_credentials(self):
        result = self.run_script("configure.py", "--port", "65536")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/".env").exists())


if __name__ == "__main__":
    unittest.main()
