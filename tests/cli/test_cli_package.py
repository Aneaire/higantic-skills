import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI_ROOT = ROOT / "cli"
if str(CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_ROOT))

import higantic_cli
from higantic_cli import higantic_html


class PackageTests(unittest.TestCase):
    def test_package_version_matches_cli_version(self):
        self.assertEqual(higantic_cli.__version__, "1.8.2")
        parser = higantic_html.build_parser()
        self.assertEqual(parser.prog, "higantic")

    def test_module_entrypoint_prints_version(self):
        completed = subprocess.run(
            [sys.executable, "-m", "higantic_cli", "--version"],
            cwd=CLI_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "HiGantic CLI 1.8.2")

    def test_packaged_modules_match_the_compatibility_launcher(self):
        compatibility_scripts = ROOT / "skills" / "higantic-html-artifacts" / "scripts"
        for name in (
            "higantic_auth.py",
            "higantic_diagnostics.py",
            "higantic_html.py",
            "higantic_secure_store.py",
            "higantic_skill_install.py",
        ):
            packaged = (CLI_ROOT / "higantic_cli" / name).read_text(encoding="utf-8")
            normalized = packaged.replace("from .higantic", "from higantic")
            compatibility = (compatibility_scripts / name).read_text(encoding="utf-8")
            self.assertEqual(normalized, compatibility, name)


if __name__ == "__main__":
    unittest.main()
