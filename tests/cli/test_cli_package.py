import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLI_ROOT = ROOT / "cli"
if str(CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_ROOT))

import higantic_cli
from higantic_cli import higantic_html


class PackageTests(unittest.TestCase):
    def test_package_version_matches_cli_version(self):
        self.assertEqual(higantic_cli.__version__, "1.8.3")
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
        self.assertEqual(completed.stdout.strip(), "HiGantic CLI 1.8.3")

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

    def test_keyboard_interrupt_exits_cleanly_without_a_traceback(self):
        args = SimpleNamespace(group="auth")
        stderr = io.StringIO()
        with mock.patch.object(higantic_html, "build_parser") as build_parser:
            build_parser.return_value.parse_args.return_value = args
            with mock.patch.object(higantic_html, "execute_auth", side_effect=KeyboardInterrupt):
                with contextlib.redirect_stderr(stderr):
                    exit_code = higantic_html.main()

        self.assertEqual(exit_code, 130)
        self.assertIn("Cancelled", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
