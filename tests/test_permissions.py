import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import argparse
import os

from antigravity_mission_control import cli


class PermissionTests(unittest.TestCase):
    def test_atomic_json_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "evidence.json"
            path.parent.mkdir(mode=0o755)
            cli.atomic_write_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o755)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})

    def test_signed_approval_detects_tampering_and_expiration(self):
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "approval.key"
            manifest = root / "approval.json"
            with mock.patch.object(cli, "APPROVAL_KEY_PATH", key_path):
                key = cli.approval_key(create=True)
                payload = {
                    "schema": "agy-mc-approval.v1",
                    "approval_id": "test",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "role": "planner",
                }
                payload["signature"] = cli.approval_signature(payload, key)
                cli.atomic_write_json(manifest, payload)
                tampered = dict(payload, role="implementer")
                cli.atomic_write_json(manifest, tampered)
                with self.assertRaisesRegex(RuntimeError, "signature"):
                    cli.load_approval(manifest)

                expired = dict(payload, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
                expired["signature"] = cli.approval_signature(expired, key)
                cli.atomic_write_json(manifest, expired)
                with self.assertRaisesRegex(RuntimeError, "expired"):
                    cli.load_approval(manifest)

    def test_signed_approval_detects_tampering_of_scoped_fields(self):
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "approval.key"
            manifest = root / "approval.json"
            with mock.patch.object(cli, "APPROVAL_KEY_PATH", key_path):
                key = cli.approval_key(create=True)
                payload = {
                    "schema": "agy-mc-approval.v1",
                    "approval_id": "test-scoped",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                    "role": "implementer",
                    "strategy": "A",
                    "model": "gemini-3.7-flash-high",
                    "cwd": str(root),
                    "mode": "accept-edits",
                    "base_commit": "a" * 40,
                    "preflight_sha256": "b" * 64,
                    "allowed_paths": ["src/"],
                    "forbidden_paths": [".agy-mc/checks.json"],
                    "required_checks": [{"id": "test", "argv": ["true"], "timeout_seconds": 300}],
                }
                payload["signature"] = cli.approval_signature(payload, key)
                cli.atomic_write_json(manifest, payload)
                self.assertEqual(cli.load_approval(manifest)["base_commit"], "a" * 40)

                for field, tampered_val in [
                    ("allowed_paths", ["docs/"]),
                    ("forbidden_paths", []),
                    ("base_commit", "c" * 40),
                    ("preflight_sha256", "d" * 64),
                    ("required_checks", [{"id": "test", "argv": ["false"], "timeout_seconds": 300}]),
                ]:
                    tampered = dict(payload, **{field: tampered_val})
                    cli.atomic_write_json(manifest, tampered)
                    with self.assertRaisesRegex(RuntimeError, "signature"):
                        cli.load_approval(manifest)

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
            with mock.patch.object(cli, "SETTINGS_PATH", settings):
                with self.assertRaisesRegex(RuntimeError, "Workspace is not trusted"):
                    cli.prepare_run(args)
            self.assertFalse(settings.exists())

    def test_cancel_refuses_pid_that_is_not_the_recorded_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(cli, "JOB_ROOT", Path(directory)):
                job = {
                    "job_id": "planner-test-job",
                    "status": "running",
                    "pid": os.getpid(),
                    "role": "planner",
                    "model": "fake",
                    "cwd": directory,
                }
                cli.write_job(job)
                args = argparse.Namespace(job_id=job["job_id"], grace_seconds=0.1)
                with self.assertRaisesRegex(RuntimeError, "Refusing to signal PID"):
                    cli.cmd_cancel(args)


if __name__ == "__main__":
    unittest.main()
