import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VALIDATOR)


class PublisherValidationTests(unittest.TestCase):
    def test_oversize_manifest_and_reference_fail_validator_size_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, maximum in (
                ("manifest.json", VALIDATOR.MAX_MANIFEST_BYTES),
                ("reference.json", VALIDATOR.MAX_REFERENCE_BYTES),
            ):
                path = root / name
                path.write_bytes(b" " * (maximum + 1))
                errors = []
                VALIDATOR.validate_bounded_file(path, maximum, errors, name)
                self.assertEqual(errors, [f"{name}: exceeds {maximum} bytes"])

    def test_config_comparison_uses_per_skill_version_and_rejects_url_mismatch(self):
        slug = "future-skill"
        source = {
            "slug": slug,
            "path": f"references/{slug}.json",
            "minimumInstalledVersion": "2.3.0",
        }
        valid = {
            "schemaVersion": 1,
            "slug": slug,
            "installedVersion": "2.4.7",
            "manifestUrl": VALIDATOR.MANIFEST_URL,
            "referenceUrl": f"{VALIDATOR.PUBLIC_ORIGIN}/v1/references/{slug}.json",
        }
        errors = []
        VALIDATOR.compare_installed_config(errors, slug, source, valid, "config")
        self.assertEqual(errors, [])

        mismatched = {**valid, "referenceUrl": f"{VALIDATOR.PUBLIC_ORIGIN}/v1/references/other.json"}
        errors = []
        VALIDATOR.compare_installed_config(errors, slug, source, mismatched, "config")
        self.assertEqual(len(errors), 1)
        self.assertIn("referenceUrl", errors[0])


if __name__ == "__main__":
    unittest.main()
