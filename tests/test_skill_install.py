import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.temp.name) / "codex"
        self.env = os.environ.copy()
        self.env["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), "skill", *args, "--format", "json"],
            cwd=ROOT,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_install_update_status_and_recoverable_uninstall(self):
        target = self.codex_home / "skills" / "antigravity-mission-control"
        installed = self.cli("install")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)["status"], "installed")
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / ".agy-mc-install.json").is_file())

        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["version"], "0.1.0a4")

        updated = self.cli("update")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        update_payload = json.loads(updated.stdout)
        self.assertTrue(Path(update_payload["backup"]).is_dir())

        removed = self.cli("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        remove_payload = json.loads(removed.stdout)
        self.assertFalse(target.exists())
        self.assertTrue(Path(remove_payload["backup"]).is_dir())

    def test_dry_run_does_not_write(self):
        target = self.codex_home / "skills" / "antigravity-mission-control"
        dry = self.cli("install", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(json.loads(dry.stdout)["status"], "dry-run")
        self.assertFalse(target.exists())

    def test_symlink_target_is_refused_without_touching_destination(self):
        victim = Path(self.temp.name) / "victim"
        victim.mkdir()
        marker = victim / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        target = self.codex_home / "skills" / "antigravity-mission-control"
        target.parent.mkdir(parents=True)
        target.symlink_to(victim, target_is_directory=True)
        result = self.cli("uninstall", "--target", str(target))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink Skill target", result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
