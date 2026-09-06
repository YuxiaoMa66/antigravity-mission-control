import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import stat


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"
FAKE = ROOT / "tests" / "fake_agy.py"


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("make a bounded change", encoding="utf-8")
        self.settings = self.root / "settings.json"
        self.settings.write_text(json.dumps({"trustedWorkspaces": [str(self.workspace) + os.sep]}), encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update(
            {
                "AGY_MC_BIN": str(FAKE),
                "AGY_MC_STATE_ROOT": str(self.root / "state"),
                "AGY_MC_JOB_ROOT": str(self.root / "state" / "jobs"),
                "AGY_MC_SETTINGS_PATH": str(self.settings),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            env=env or self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_args(self):
        return (
            "run", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--roster-approved",
            "--cwd", str(self.workspace), "--prompt-file", str(self.prompt),
            "--mode", "accept-edits", "--timeout-seconds", "30", "--background",
        )

    def test_background_lifecycle_and_atomic_editor_lock(self):
        slow_env = self.env.copy()
        slow_env["FAKE_AGY_SLEEP"] = "30"
        first = self.cli(*self.run_args(), env=slow_env)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_job = json.loads(first.stdout)["job_id"]

        second = self.cli(*self.run_args())
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("active editing lock", second.stderr)

        canceled = self.cli("cancel", first_job, "--grace-seconds", "0.2")
        self.assertEqual(canceled.returncode, 4, canceled.stderr)
        self.assertEqual(json.loads(canceled.stdout)["status"], "canceled")
        result = self.cli("result", first_job)
        self.assertEqual(json.loads(result.stdout)["status"], "canceled")

        third = self.cli(*self.run_args())
        self.assertEqual(third.returncode, 0, third.stderr)
        third_job = json.loads(third.stdout)["job_id"]
        waited = self.cli("wait", third_job, "--timeout", "10s")
        self.assertEqual(waited.returncode, 0, waited.stderr)
        payload = json.loads(waited.stdout)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["conversation_id"], "fake-conversation")

    def test_signed_approval_binds_prompt_and_run(self):
        approval = self.root / "approval.json"
        created = self.cli(
            "approve", "--strategy", "A", "--role", "planner",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "plan",
            "--expires-minutes", "10", "--confirmed", "--three-rosters-presented", "--output", str(approval),
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(json.loads(created.stdout)["status"], "created")
        self.assertEqual(stat.S_IMODE(approval.stat().st_mode), 0o600)

        run = self.cli(
            "run", "--strategy", "A", "--role", "planner",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "plan",
            "--approval-file", str(approval), "--timeout-seconds", "30",
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"event": "result"', run.stdout)

        self.prompt.write_text("changed after approval", encoding="utf-8")
        mismatch = self.cli(
            "run", "--strategy", "A", "--role", "planner",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "plan",
            "--approval-file", str(approval), "--timeout-seconds", "30",
        )
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("prompt_sha256", mismatch.stderr)


if __name__ == "__main__":
    unittest.main()
