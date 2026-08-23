import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"
FAKE = ROOT / "tests" / "fake_agy.py"


class UsageTests(unittest.TestCase):
    def run_cli(self, *args):
        env = os.environ.copy()
        env["AGY_MC_BIN"] = str(FAKE)
        env["AGY_MC_STATE_ROOT"] = str(ROOT / ".test-state")
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_usage_json_is_normalized_and_account_free(self):
        proc = self.run_cli("usage", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema"], "agy-mc-usage.v1")
        self.assertEqual(payload["groups"][0]["buckets"][0]["remaining_percent"], 62.5)
        self.assertEqual(payload["groups"][0]["buckets"][1]["remaining_percent"], 7.12)
        self.assertTrue(payload["groups"][1]["buckets"][0]["disabled"])
        serialized = json.dumps(payload).lower()
        self.assertNotIn("oauth", serialized)
        self.assertNotIn("email", serialized)

    def test_watch_has_bounded_count_for_automation(self):
        proc = self.run_cli("usage", "--watch", "--count", "2", "--interval", "0.01", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.count('"schema": "agy-mc-usage.v1"'), 2)

    def test_table_does_not_turn_unknown_into_zero(self):
        proc = self.run_cli("usage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("62.50%", proc.stdout)
        self.assertIn("unknown", proc.stdout)
        self.assertIn("disabled", proc.stdout)

    def test_doctor_checks_capabilities(self):
        proc = self.run_cli("doctor")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "ok")

    def test_prompt_transport_is_stdin_stream_json(self):
        from antigravity_mission_control import cli
        import argparse
        import tempfile

        args = argparse.Namespace(mode="plan", timeout_seconds=30, conversation=None, unrestricted=False)
        prepared = {"cwd": ROOT, "model": "gemini-3.7-flash-high", "schema_path": None, "prompt_text": "secret prompt"}
        command = cli.build_agy_command(args, prepared, Path(tempfile.gettempdir()) / "agy.log")
        self.assertNotIn("secret prompt", command)
        self.assertIn("stream-json", command)
        event = json.loads(cli.prompt_event("secret prompt"))
        self.assertEqual(event["message"]["content"], "secret prompt")


if __name__ == "__main__":
    unittest.main()
