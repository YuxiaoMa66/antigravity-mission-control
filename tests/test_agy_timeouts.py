import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_mission_control import cli, routing, usage


class AgyTimeoutTests(unittest.TestCase):
    def test_model_listing_uses_90_seconds_for_json_and_fallback(self):
        empty = subprocess.CompletedProcess([], 0, '{"command":{"data":{"models":[]}}}', "")
        fallback = subprocess.CompletedProcess([], 0, "model-id\tModel label\n", "")
        with patch.object(routing, "run_capture", side_effect=[empty, fallback]) as run:
            self.assertEqual(routing.available_models(), [{"id": "model-id", "label": "Model label"}])
        self.assertEqual([call.kwargs["timeout"] for call in run.call_args_list], [90, 90])

    def test_doctor_model_listing_uses_90_seconds(self):
        success = subprocess.CompletedProcess([], 0, "", "")
        help_result = subprocess.CompletedProcess([], 0, "--add-dir --input-format --output-format --model", "")
        models = subprocess.CompletedProcess(
            [], 0, json.dumps({"command": {"data": {"models": [{"id": "model-id"}]}}}), ""
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(cli, "run_capture", side_effect=[success, help_result, models, success]) as run:
                with patch.object(cli, "STATE_ROOT", Path(temp_dir) / "state"), patch.object(cli.os, "chmod"):
                    self.assertEqual(cli.cmd_doctor(argparse.Namespace()), 0)
        self.assertEqual(run.call_args_list[2].kwargs["timeout"], routing.MODELS_TIMEOUT_SECONDS)

    def test_usage_timeout_defaults_to_45_seconds(self):
        self.assertEqual(cli.build_parser().parse_args(["usage"]).timeout_seconds, 45)
        with patch.object(usage, "run_capture") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "")
            usage.fetch_usage()
        self.assertEqual(run.call_args.kwargs["timeout"], 45)


if __name__ == "__main__":
    unittest.main()
