import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import argparse

from antigravity_mission_control import cli


class PermissionTests(unittest.TestCase):
    def test_atomic_json_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "evidence.json"
            cli.atomic_write_json(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})

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


if __name__ == "__main__":
    unittest.main()
