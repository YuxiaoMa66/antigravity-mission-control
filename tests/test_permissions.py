import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import argparse
import contextlib
import io
import subprocess

from antigravity_mission_control import approvals, common, jobs, jobstore, workspace


class PermissionTests(unittest.TestCase):
    def test_atomic_json_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "evidence.json"
            path.parent.mkdir(mode=0o755)
            common.atomic_write_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o755)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})

    def test_signed_approval_detects_tampering_and_expiration(self):
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "approval.key"
            manifest = root / "approval.json"
            with mock.patch.object(approvals, "APPROVAL_KEY_PATH", key_path):
                key = approvals.approval_key(create=True)
                payload = {
                    "schema": "agy-mc-approval.v1",
                    "approval_id": "test",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "role": "planner",
                }
                payload["signature"] = approvals.approval_signature(payload, key)
                common.atomic_write_json(manifest, payload)
                tampered = dict(payload, role="implementer")
                common.atomic_write_json(manifest, tampered)
                with self.assertRaisesRegex(RuntimeError, "signature"):
                    approvals.load_approval(manifest)

                expired = dict(payload, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
                expired["signature"] = approvals.approval_signature(expired, key)
                common.atomic_write_json(manifest, expired)
                with self.assertRaisesRegex(RuntimeError, "expired"):
                    approvals.load_approval(manifest)

    def test_run_never_auto_grants_workspace_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text("bounded task")
            settings = root / "settings.json"
            args = argparse.Namespace(
                roster_approved=True,
                model="gemini-3.7-flash-high",
                unrestricted=False,
                unrestricted_approved=False,
                cwd=str(root),
                prompt_file=str(prompt),
                mode="plan",
                strategy="A",
                role="planner",
                allow_non_high_gemini=False,
                json_schema=None,
            )
            with mock.patch.object(workspace, "SETTINGS_PATH", settings):
                with self.assertRaisesRegex(RuntimeError, "Workspace is not trusted"):
                    jobs.prepare_run(args)
            self.assertFalse(settings.exists())

    def test_cancel_refuses_pid_that_is_not_the_recorded_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(jobstore, "JOB_ROOT", Path(directory)):
                job = {
                    "job_id": "planner-test-job",
                    "status": "running",
                    "pid": os.getpid(),
                    "role": "planner",
                    "model": "fake",
                    "cwd": directory,
                }
                jobstore.write_job(job)
                args = argparse.Namespace(job_id=job["job_id"], grace_seconds=0.1)
                with self.assertRaisesRegex(RuntimeError, "Refusing to signal PID"):
                    jobs.cmd_cancel(args)

    def test_job_left_starting_by_a_dead_launcher_is_marked_crashed(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(jobstore, "JOB_ROOT", Path(directory)):
                job = {"job_id": "planner-stuck-job", "status": "starting", "pid": None,
                       "launcher_pid": dead.pid, "role": "planner", "model": "fake", "cwd": directory}
                jobstore.write_job(job)
                self.assertEqual(jobstore.refresh_job(jobstore.read_job(job["job_id"]))["status"], "crashed")
                self.assertEqual(jobstore.job_result(job["job_id"])["status"], "crashed")

    def test_cancel_during_launch_is_not_overwritten_and_kills_the_worker(self):
        real_popen = subprocess.Popen
        spawned = []

        def cancel_then_spawn(*_args, **_kwargs):
            job_file = next(jobstore.JOB_ROOT.glob("*/job.json"))
            job = json.loads(job_file.read_text())
            jobstore.write_job(dict(job, status="canceled"))
            spawned.append(real_popen(["sleep", "30"], start_new_session=True))
            return spawned[0]

        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(role="planner", strategy="A", mode="plan", conversation=None,
                                      allow_non_high_gemini=False, unrestricted=False, timeout_seconds=30)
            prepared = {"cwd": Path(directory), "model": "fake", "prompt_text": "hi", "schema_path": None}
            with mock.patch.object(jobstore, "JOB_ROOT", Path(directory) / "jobs"), \
                    mock.patch.object(jobstore.subprocess, "Popen", side_effect=cancel_then_spawn), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = jobstore.launch_background_job(args, prepared, "planner-race-job", None, None)
                status = jobstore.read_job("planner-race-job")["status"]
        self.assertEqual(code, jobstore.JOB_EXIT_CODES["canceled"])
        self.assertEqual(status, "canceled")
        self.assertIsNotNone(spawned[0].poll())


if __name__ == "__main__":
    unittest.main()
