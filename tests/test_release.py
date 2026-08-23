import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from antigravity_mission_control import __version__
from antigravity_mission_control import cli


ROOT = Path(__file__).resolve().parents[1]


class ReleaseIntegrityTests(unittest.TestCase):
    def test_versions_are_synchronized(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        npm_cli = (ROOT / "npm" / "cli.mjs").read_text(encoding="utf-8")
        self.assertEqual(cli.VERSION, "0.1.0a1")
        self.assertEqual(__version__, cli.VERSION)
        self.assertIn('version = "0.1.0a1"', pyproject)
        self.assertEqual(package["version"], "0.1.0-alpha.1")
        self.assertIn("const VERSION = '0.1.0-alpha.1'", npm_cli)
        self.assertIn("const PYTHON_VERSION = '0.1.0a1'", npm_cli)
        self.assertIn("assets/", package["files"])
        self.assertIn('skill_bundle/**/__pycache__/*', pyproject)

    def test_bilingual_document_pairs_exist(self):
        pairs = (
            ("README.md", "README.zh-CN.md"),
            ("docs/INSTALL.md", "docs/INSTALL.zh-CN.md"),
            ("docs/REFERENCE.md", "docs/REFERENCE.zh-CN.md"),
            ("docs/RELEASING.md", "docs/RELEASING.zh-CN.md"),
            ("docs/releases/v0.1.0a1.md", "docs/releases/v0.1.0a1.zh-CN.md"),
        )
        for english, chinese in pairs:
            with self.subTest(english=english):
                self.assertTrue((ROOT / english).is_file())
                self.assertTrue((ROOT / chinese).is_file())

    def test_embedded_skill_matches_canonical_sources(self):
        bundle = ROOT / "antigravity_mission_control" / "skill_bundle"
        paths = [ROOT / "SKILL.md", ROOT / "scripts" / "agy_delegate.py"]
        for directory in ("agents", "policies", "references"):
            paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
        for source in paths:
            relative = source.relative_to(ROOT)
            target = bundle / relative
            with self.subTest(path=str(relative)):
                self.assertTrue(target.is_file())
                self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_local_markdown_links_resolve(self):
        markdown_files = [path for path in ROOT.rglob("*.md") if ".git" not in path.parts]
        for document in markdown_files:
            text = document.read_text(encoding="utf-8")
            for raw_target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                target = raw_target.strip().strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (document.parent / target).resolve()
                with self.subTest(document=str(document.relative_to(ROOT)), target=target):
                    self.assertTrue(resolved.exists(), f"Broken local link: {document} -> {target}")

    def test_svg_assets_are_well_formed(self):
        for asset in (ROOT / "assets").rglob("*.svg"):
            with self.subTest(asset=str(asset.relative_to(ROOT))):
                root = ET.parse(asset).getroot()
                self.assertTrue(root.tag.endswith("svg"))


if __name__ == "__main__":
    unittest.main()
