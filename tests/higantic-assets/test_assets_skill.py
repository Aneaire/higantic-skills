import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "higantic-assets"
FETCHER_PATH = SKILL / "scripts" / "fetch_live_reference.py"
SPEC = importlib.util.spec_from_file_location("higantic_assets_fetcher_tests", FETCHER_PATH)
FETCHER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(FETCHER)


class AssetsSkillTests(unittest.TestCase):
    def test_source_and_fallback_are_identical_and_render_locally(self):
        source = (ROOT / "site" / "v1" / "references" / "higantic-assets.json").read_bytes()
        fallback = (SKILL / "references" / "live-reference-fallback.json").read_bytes()
        self.assertEqual(source, fallback)
        parsed = FETCHER.validate_reference_data(source, "higantic-assets")
        rendered = FETCHER.render_reference(parsed)
        self.assertIn("HiGantic Managed Assets product-state reference", rendered)
        self.assertNotIn(json.dumps(parsed), rendered)

    def test_reference_uses_canonical_asset_scopes(self):
        source = (ROOT / "site" / "v1" / "references" / "higantic-assets.json").read_bytes()
        parsed = FETCHER.validate_reference_data(source, "higantic-assets")
        self.assertEqual(parsed["scopes"], ["assets:read", "assets:write", "assets:share"])
        rendered = FETCHER.render_reference(parsed)
        self.assertIn("assets:read", rendered)
        self.assertIn("assets:share", rendered)
        self.assertNotIn("html_assets:read", rendered)

    def test_skill_owns_lifecycle_and_excludes_existing_reference_only_work(self):
        frontmatter = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        self.assertIn("upload", frontmatter.lower())
        self.assertIn("publish", frontmatter.lower())
        self.assertIn("delete", frontmatter.lower())
        self.assertIn("Do not trigger merely", frontmatter)
        html_frontmatter = (ROOT / "skills" / "higantic-html-artifacts" / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        self.assertIn("use higantic-assets for asset lifecycle work", html_frontmatter)

    def test_sharing_and_deletion_are_independent_confirmation_gates(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("assets make-public --asset-id ASSET_ID --confirm-public-sharing", text)
        self.assertIn("assets delete --asset-id ASSET_ID --confirm-delete", text)
        self.assertIn("Public visibility does not authorize deletion", text)
        self.assertIn("pinned HTML artifact snapshot may retain referenced bytes", text)


if __name__ == "__main__":
    unittest.main()
