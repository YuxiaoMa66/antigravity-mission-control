import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from antigravity_mission_control import cli


MODELS = [
    {"id": "gemini-3.8-flash-low"},
    {"id": "gemini-3.8-flash-medium"},
    {"id": "gemini-3.8-flash-high"},
    {"id": "gemini-3.1-pro-high"},
    {"id": "claude-sonnet-4-6"},
    {"id": "claude-opus-4-6-thinking"},
    {"id": "gpt-oss-120b-medium"},
]


class RoutingTests(unittest.TestCase):
    def test_a_prefers_role_specific_flash_intensity(self):
        self.assertEqual(cli.select_model("scout", MODELS, strategy="A"), "gemini-3.8-flash-low")
        self.assertEqual(cli.select_model("implementer", MODELS, strategy="A"), "gemini-3.8-flash-medium")

    def test_b_is_quality_first_but_flash_first_for_implementer(self):
        self.assertEqual(cli.select_model("implementer", MODELS, strategy="B"), "gemini-3.8-flash-high")
        self.assertEqual(
            cli.select_model("reviewer", MODELS, avoid_family="gemini", strategy="B"),
            "claude-opus-4-6-thinking",
        )

    def test_c_routes_every_role_to_latest_flash_high(self):
        models = MODELS + [{"id": "gemini-3.9-flash-high"}, {"id": "gemini-3.10-flash-high"}]
        for role in cli.ROLES:
            with self.subTest(role=role):
                self.assertEqual(cli.select_model(role, models, strategy="C"), "gemini-3.10-flash-high")

    def test_implementer_fallback_order(self):
        for strategy, order in {
            "A": [1, 2, 0, 3, 4, 5, 6],
            "B": [2, 1, 0, 3, 5, 4, 6],
        }.items():
            candidates = list(reversed(MODELS))
            for index in order:
                with self.subTest(strategy=strategy, remaining=len(candidates)):
                    self.assertEqual(cli.select_model("implementer", candidates, strategy=strategy), MODELS[index]["id"])
                candidates.remove(MODELS[index])

    def test_other_non_high_gemini_are_not_proposed(self):
        excluded = [{"id": "gemini-3.1-pro-low"}, {"id": "gemini-3.1-pro-medium"}]
        for strategy in ("A", "B"):
            for role in cli.ROLES:
                with self.subTest(strategy=strategy, role=role):
                    with self.assertRaisesRegex(RuntimeError, "No AGY models"):
                        cli.select_model(role, excluded, strategy=strategy)
                    self.assertEqual(cli.select_model(role, excluded + [MODELS[-1]], strategy=strategy), MODELS[-1]["id"])

    def test_c_rejects_missing_high_and_family_exclusion(self):
        with self.assertRaisesRegex(RuntimeError, "no Gemini Flash High"):
            cli.select_model("reviewer", [MODELS[0]], strategy="C")
        with self.assertRaisesRegex(RuntimeError, "does not support --avoid-family"):
            cli.select_model("reviewer", MODELS, avoid_family="gemini", strategy="C")

    def test_non_high_execution_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "prompt.txt"
            prompt.write_text("bounded task")
            args = argparse.Namespace(
                roster_approved=True, model=MODELS[1]["id"], unrestricted=False,
                unrestricted_approved=False, cwd=directory, prompt_file=str(prompt),
                mode="plan", strategy="A", role="implementer",
                allow_non_high_gemini=False, json_schema=None,
            )
            with patch.object(cli, "workspace_status", return_value={"trusted": True}), patch.object(cli, "available_models", return_value=MODELS):
                with self.assertRaisesRegex(RuntimeError, "requires explicit user confirmation"):
                    cli.prepare_run(args)
                args.allow_non_high_gemini = True
                self.assertEqual(cli.prepare_run(args)["model"], args.model)


if __name__ == "__main__":
    unittest.main()
