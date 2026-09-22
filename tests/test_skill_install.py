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
        self.claude_home = Path(self.temp.name) / "claude"
        self.env["CODEX_HOME"] = str(self.codex_home)
        self.env["CLAUDE_CONFIG_DIR"] = str(self.claude_home)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, host="codex"):
        host_args = ["--host", host] if host else []
        return subprocess.run(
            [sys.executable, str(CLI), "skill", *args, *host_args, "--format", "json"],
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
        self.assertEqual(json.loads(status.stdout)["version"], "0.5.0")

        updated = self.cli("update")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        update_payload = json.loads(updated.stdout)
        self.assertTrue(Path(update_payload["backup"]).is_dir())

        removed = self.cli("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        remove_payload = json.loads(removed.stdout)
        self.assertFalse(target.exists())
        self.assertTrue(Path(remove_payload["backup"]).is_dir())

    def test_uninstall_refuses_an_unmanaged_target_without_force(self):
        target = self.codex_home / "skills" / "antigravity-mission-control"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("someone else's skill", encoding="utf-8")
        refused = self.cli("uninstall")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not managed by agy-mc", refused.stderr)
        self.assertTrue((target / "SKILL.md").is_file())
        forced = self.cli("uninstall", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertFalse(target.exists())

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

    def test_claude_install_skips_codex_only_metadata_and_uses_claude_paths(self):
        target = self.claude_home / "skills" / "antigravity-mission-control"
        installed = self.cli("install", host="claude")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)["host"], "claude")
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / "references" / "host-notes.md").is_file())
        self.assertFalse((target / "agents").exists())
        marker = json.loads((target / ".agy-mc-install.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["host"], "claude")
        self.assertFalse((self.codex_home / "skills").exists())
        removed = self.cli("uninstall", host="claude")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertTrue(Path(json.loads(removed.stdout)["backup"]).is_relative_to(self.claude_home / "skill-backups"))

    def test_codex_install_keeps_interface_metadata(self):
        self.assertEqual(self.cli("install").returncode, 0)
        target = self.codex_home / "skills" / "antigravity-mission-control"
        self.assertTrue((target / "agents" / "openai.yaml").is_file())

    def test_all_installs_both_hosts(self):
        result = self.cli("install", host="all")
        self.assertEqual(result.returncode, 0, result.stderr)
        hosts = [item["host"] for item in json.loads(result.stdout)["results"]]
        self.assertEqual(hosts, ["codex", "claude"])

    def test_auto_installs_only_detected_hosts_and_errors_when_none(self):
        none = self.cli("install", host="auto")
        self.assertNotEqual(none.returncode, 0)
        self.assertIn("--host", none.stderr)
        self.claude_home.mkdir()
        result = self.cli("install", host="auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["host"], "claude")
        self.assertFalse((self.codex_home / "skills").exists())

    def test_auto_uninstall_touches_only_managed_hosts_and_status_lists_both(self):
        self.assertEqual(self.cli("install", host="claude").returncode, 0)
        unmanaged = self.codex_home / "skills" / "antigravity-mission-control"
        unmanaged.mkdir(parents=True)
        status = self.cli("status", host="auto")
        self.assertEqual(status.returncode, 0, status.stderr)
        by_host = {item["host"]: item["status"] for item in json.loads(status.stdout)["results"]}
        self.assertEqual(by_host, {"codex": "present", "claude": "present"})
        removed = self.cli("uninstall", host="auto")
        self.assertEqual(json.loads(removed.stdout)["host"], "claude")
        self.assertTrue(unmanaged.is_dir())

    def test_target_requires_a_single_host(self):
        result = self.cli("install", "--target", str(Path(self.temp.name) / "t"), host="all")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("single --host", result.stderr)

    def test_doctor_warns_when_installed_skill_is_stale(self):
        target = self.claude_home / "skills" / "antigravity-mission-control"
        target.mkdir(parents=True)
        (target / ".agy-mc-install.json").write_text(json.dumps({"version": "0.3.1"}), encoding="utf-8")
        env = {**self.env, "AGY_MC_BIN": str(ROOT / "tests" / "fake_agy.py"), "AGY_MC_STATE_ROOT": str(Path(self.temp.name) / "state")}
        proc = subprocess.run([sys.executable, str(CLI), "doctor"], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        checks = {c["name"]: c for c in json.loads(proc.stdout)["checks"]}
        self.assertIn("agy-mc skill update --host claude", checks["skill-claude"]["warning"])


if __name__ == "__main__":
    unittest.main()
