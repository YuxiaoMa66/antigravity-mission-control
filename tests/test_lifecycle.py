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

    def test_scoped_background_lifecycle_and_cancellation(self):
        # Init git repo
        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.workspace, check=True)
        subprocess.run(["git", "config", "user.email", "test@invalid"], cwd=self.workspace, check=True)
        (self.workspace / "user.txt").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.workspace, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.workspace, check=True)

        checks_dir = self.workspace / ".agy-mc"
        checks_dir.mkdir(exist_ok=True)
        (checks_dir / "checks.json").write_text(json.dumps({
            "schema": "agy-mc-checks.v1",
            "checks": {
                "tcheck": {"argv": [sys.executable, "-c", "import sys; sys.exit(0)"], "timeout_seconds": 30}
            }
        }), encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.workspace, check=True)
        subprocess.run(["git", "commit", "-qm", "add checks"], cwd=self.workspace, check=True)

        # 1. Successful scoped background run
        app_ok = self.root / "app_ok.json"
        cr_ok = self.cli(
            "approve", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--confirmed", "--policy", "balanced", "--output", str(app_ok),
            "--allowed-path", "user.txt", "--required-check", "tcheck",
        )
        self.assertEqual(cr_ok.returncode, 0, cr_ok.stderr)

        action_ok = json.dumps({"write": [{"path": "user.txt", "content": "mod\n"}]})
        env_ok = self.env.copy()
        env_ok["FAKE_AGY_CUSTOM_ACTION"] = action_ok
        run_bg = self.cli(
            "run", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--approval-file", str(app_ok), "--timeout-seconds", "30", "--background",
            env=env_ok,
        )
        self.assertEqual(run_bg.returncode, 0, run_bg.stderr)
        job_id_ok = json.loads(run_bg.stdout)["job_id"]
        wait_ok = self.cli("wait", job_id_ok, "--timeout", "15s")
        self.assertEqual(wait_ok.returncode, 0, wait_ok.stderr)
        res_ok = json.loads(wait_ok.stdout)
        self.assertEqual(res_ok["status"], "done")
        self.assertEqual(res_ok["exit_code"], 0)
        self.assertEqual(res_ok["acceptance"], "not_evaluated")
        self.assertEqual(res_ok["enforcement"]["status"], "passed")
        self.assertEqual(len(res_ok["enforcement"]["checks"]), 1)

        # 2. Scope violation in background
        app_viol = self.root / "app_viol.json"
        cr_viol = self.cli(
            "approve", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--confirmed", "--policy", "balanced", "--output", str(app_viol),
            "--allowed-path", "user.txt",
        )
        self.assertEqual(cr_viol.returncode, 0, cr_viol.stderr)

        action_viol = json.dumps({"write": [{"path": "unallowed.txt", "content": "bad\n"}]})
        env_viol = self.env.copy()
        env_viol["FAKE_AGY_CUSTOM_ACTION"] = action_viol
        run_viol = self.cli(
            "run", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--approval-file", str(app_viol), "--timeout-seconds", "30", "--background",
            env=env_viol,
        )
        self.assertEqual(run_viol.returncode, 0, run_viol.stderr)
        job_id_viol = json.loads(run_viol.stdout)["job_id"]
        wait_viol = self.cli("wait", job_id_viol, "--timeout", "15s")
        self.assertEqual(wait_viol.returncode, 5, wait_viol.stderr)
        res_viol = json.loads(wait_viol.stdout)
        self.assertEqual(res_viol["status"], "error")
        self.assertEqual(res_viol["exit_code"], 5)
        self.assertEqual(res_viol["acceptance"], "not_evaluated")
        self.assertEqual(res_viol["enforcement"]["status"], "scope_violation")

        # Result command prints stored result and returns exact exit code 5
        res_cmd = self.cli("result", job_id_viol)
        self.assertEqual(res_cmd.returncode, 5, res_cmd.stderr)
        res_cmd_data = json.loads(res_cmd.stdout)
        self.assertEqual(res_cmd_data["exit_code"], 5)
        self.assertEqual(res_cmd_data["enforcement"]["status"], "scope_violation")
        self.assertEqual(res_cmd_data["acceptance"], "not_evaluated")

    def test_nested_provider_result_stream_shape(self):
        nested_output = json.dumps({
            "conversation_id": "nested-conv-456",
            "status": "SUCCESS",
            "response": "nested response completed",
        })
        env_nested = self.env.copy()
        env_nested["FAKE_AGY_NESTED_RESULT"] = nested_output

        app = self.root / "app_nested.json"
        cr = self.cli(
            "approve", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--confirmed", "--policy", "balanced", "--output", str(app),
        )
        self.assertEqual(cr.returncode, 0, cr.stderr)

        run = self.cli(
            "run", "--strategy", "A", "--role", "implementer",
            "--model", "gemini-3.7-flash-high", "--cwd", str(self.workspace),
            "--prompt-file", str(self.prompt), "--mode", "accept-edits",
            "--approval-file", str(app), "--timeout-seconds", "30", "--background",
            env=env_nested,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        job_id = json.loads(run.stdout)["job_id"]

        wait = self.cli("wait", job_id, "--timeout", "15s")
        self.assertEqual(wait.returncode, 0, wait.stderr)
        res = json.loads(wait.stdout)
        self.assertEqual(res["conversation_id"], "nested-conv-456")
        self.assertEqual(res["status"], "done")

        stat = self.cli("status", job_id)
        job_meta = json.loads(stat.stdout)
        self.assertEqual(job_meta["conversation_id"], "nested-conv-456")


if __name__ == "__main__":
    unittest.main()
