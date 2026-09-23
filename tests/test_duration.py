import argparse
import unittest

from antigravity_mission_control.common import parse_duration
from antigravity_mission_control.jobs import cmd_wait


class ParseDurationTests(unittest.TestCase):
    def test_valid_units(self):
        cases = [
            ("100ms", 0.1),
            ("1s", 1),
            ("1.5s", 1.5),
            ("2m", 120),
            ("0.5h", 1800),
            ("1d", 86400),
        ]
        for text, seconds in cases:
            with self.subTest(text=text):
                self.assertAlmostEqual(parse_duration(text), seconds)

    def test_rejects_malformed_values(self):
        for text in ["", "10", "10w", "-1s", " 1s", "1s ", "1 s"]:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "duration") as exc_info:
                    parse_duration(text)
                self.assertIn(repr(text), str(exc_info.exception))

    def test_wait_keeps_existing_invalid_timeout_message(self):
        args = argparse.Namespace(timeout_seconds_override=None, timeout="nonsense")
        with self.assertRaisesRegex(
            RuntimeError,
            "^Invalid --timeout; use values such as 100s, 5m, or 1h$",
        ):
            cmd_wait(args)

    def test_wait_rejects_zero_timeout_as_non_positive(self):
        args = argparse.Namespace(timeout_seconds_override=None, timeout="0s")
        with self.assertRaisesRegex(RuntimeError, "^--timeout must be positive$"):
            cmd_wait(args)


if __name__ == "__main__":
    unittest.main()
