import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from antigravity_mission_control import cli


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"
FAKE = ROOT / "tests" / "fake_agy.py"


class DoctorColdStartTests(unittest.TestCase):
    def run_cli(self, *args, **overrides):
        with tempfile.TemporaryDirectory() as state_root:
            env = os.environ.copy()
            env.update({"AGY_MC_BIN": str(FAKE), "AGY_MC_STATE_ROOT": state_root})
            env.update(overrides)
            return subprocess.run(
                [sys.executable, str(CLI), *args], cwd=ROOT, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )

    def test_default_lists_server_without_probing(self):
        proc = self.run_cli("doctor")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        checks = json.loads(proc.stdout)["checks"]
        mcp = next(check for check in checks if check["name"] == "agy-mcp")
        self.assertEqual(mcp["servers"], ["fake-mcp"])
        self.assertIn("warning", mcp)
        self.assertNotIn("agy-cold-start", [check["name"] for check in checks])

    def test_no_enabled_servers_has_no_warning(self):
        proc = self.run_cli("doctor", FAKE_AGY_MCP_NONE="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mcp = next(check for check in json.loads(proc.stdout)["checks"] if check["name"] == "agy-mcp")
        self.assertEqual(mcp["servers"], [])
        self.assertNotIn("warning", mcp)

    def test_probe_reports_numeric_latency(self):
        proc = self.run_cli("doctor", "--probe-latency")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        probe = next(check for check in json.loads(proc.stdout)["checks"] if check["name"] == "agy-cold-start")
        self.assertTrue(probe["ok"])
        self.assertIsInstance(probe["seconds"], (int, float))
        self.assertNotIn("warning", probe)

    def test_slow_probe_warns_with_enabled_server_name(self):
        success = subprocess.CompletedProcess([], 0, "", "")
        help_result = subprocess.CompletedProcess([], 0, "--add-dir --input-format --output-format --model", "")
        models = subprocess.CompletedProcess([], 0, json.dumps({"command": {"data": {"models": [{"id": "gemini-3.7-flash-high"}]}}}), "")
        mcp = subprocess.CompletedProcess([], 0, "NAME TYPE STATUS COMMAND/URL\nfake-mcp stdio enabled /bin/fake-mcp\n", "")
        with tempfile.TemporaryDirectory() as state:
            with patch.object(cli, "run_capture", side_effect=[success, help_result, models, mcp, success, success]):
                with patch.object(cli, "STATE_ROOT", Path(state)), patch.object(cli.os, "chmod"), patch.object(cli.time, "monotonic", side_effect=[0, 45]), patch("sys.stdout", new_callable=__import__("io").StringIO) as output:
                    self.assertEqual(cli.cmd_doctor(argparse.Namespace(probe_latency=True)), 0)
            probe = next(check for check in json.loads(output.getvalue())["checks"] if check["name"] == "agy-cold-start")
        self.assertEqual(probe["seconds"], 45.0)
        self.assertIn("fake-mcp", probe["warning"])

    def test_mcp_list_failure_does_not_fail_doctor(self):
        success = subprocess.CompletedProcess([], 0, "", "")
        help_result = subprocess.CompletedProcess([], 0, "--add-dir --input-format --output-format --model", "")
        models = subprocess.CompletedProcess([], 0, json.dumps({"command": {"data": {"models": [{"id": "gemini-3.7-flash-high"}]}}}), "")
        for failure in (subprocess.CompletedProcess([], 1, "", "failed"), subprocess.TimeoutExpired("agy mcp list", 30)):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as state:
                    with patch.object(cli, "run_capture", side_effect=[success, help_result, models, failure]):
                        with patch.object(cli, "STATE_ROOT", Path(state)), patch.object(cli.os, "chmod"), patch("sys.stdout", new_callable=__import__("io").StringIO) as output:
                            self.assertEqual(cli.cmd_doctor(argparse.Namespace()), 0)
                    mcp = next(check for check in json.loads(output.getvalue())["checks"] if check["name"] == "agy-mcp")
                    self.assertEqual(mcp["servers"], [])
                    self.assertNotIn("warning", mcp)

    def test_probe_keeps_bare_command_name_even_if_cwd_has_a_same_named_file(self):
        success = subprocess.CompletedProcess([], 0, "", "")
        help_result = subprocess.CompletedProcess([], 0, "--add-dir --input-format --output-format --model", "")
        models = subprocess.CompletedProcess([], 0, json.dumps({"command": {"data": {"models": [{"id": "gemini-3.7-flash-high"}]}}}), "")
        mcp = subprocess.CompletedProcess([], 0, "NAME TYPE STATUS COMMAND/URL\n", "")
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as cwd:
            (Path(cwd) / "agy").write_text("#!/bin/sh\n")
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                with patch.object(cli, "AGY_BIN", "agy"), patch.object(cli, "run_capture", side_effect=[success, help_result, models, mcp, success, success]) as run:
                    with patch.object(cli, "STATE_ROOT", Path(state)), patch.object(cli.os, "chmod"), patch("sys.stdout", new_callable=__import__("io").StringIO):
                        cli.cmd_doctor(argparse.Namespace(probe_latency=True))
            finally:
                os.chdir(previous)
        self.assertEqual(run.call_args_list[-1].args[0][0], "agy")

if __name__ == "__main__":
    unittest.main()
