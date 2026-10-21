"""Contracts for preparing standalone publisher and CI workspaces."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "team" / "prepare.py"


class TeamExampleTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "integration-tests" / ".tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="team-unit-", dir=parent)
        self.output = Path(self.temporary.name) / "workspace"

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, role="consumer", registry="http://127.0.0.1:18080"):
        return subprocess.run((sys.executable, str(SCRIPT), "--role", role, "--registry", registry,
                               "--output", str(self.output)), capture_output=True, text=True, timeout=15)

    def test_consumer_prepared_without_credentials(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = (self.output / "cangjie-repo.toml").read_text()
        self.assertIn('token-env = "CJREPO_READ_TOKEN"', config)
        self.assertIn('exclusive = true', config)
        self.assertNotIn('PUBLISH_TOKEN', config)
        self.assertEqual(json.loads((self.output / "workspace.json").read_text())["role"], "consumer")
        self.assertFalse((self.output / ".env").exists())

    def test_publisher_uses_publish_credential_reference(self):
        result = self.invoke(role="publisher")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = (self.output / "cangjie-repo.toml").read_text()
        self.assertIn('[repository.home]', config)
        self.assertIn('token-env = "CJREPO_PUBLISH_TOKEN"', config)
        self.assertNotIn('READ_TOKEN', config)

    def test_existing_workspace_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse((self.output / "cangjie-repo.toml").exists())

    def test_unsafe_registry_rejected_before_creating_workspace(self):
        result = self.invoke(registry="http://user:synthetic-secret@localhost:18080")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn("synthetic-secret", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
