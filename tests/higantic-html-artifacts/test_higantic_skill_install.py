import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "higantic-html-artifacts" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import higantic_skill_install as INSTALLER

HTML_SPEC = importlib.util.spec_from_file_location("higantic_html_skill_install_tests", SCRIPTS / "higantic_html.py")
HTML = importlib.util.module_from_spec(HTML_SPEC)
assert HTML_SPEC and HTML_SPEC.loader
HTML_SPEC.loader.exec_module(HTML)


FIXTURE_CATALOG = (
    {
        "slug": "higantic-html-artifacts",
        "name": "HTML Artifacts",
        "description": "Create safe HTML artifacts.",
    },
    {
        "slug": "higantic-research",
        "name": "Research",
        "description": "Create source-grounded research.",
    },
)


class ParserTests(unittest.TestCase):
    def test_skills_install_and_login_offer_controls_are_available(self):
        parser = HTML.build_parser()
        command = parser.parse_args(["skills", "install", "--skill", "higantic-html-artifacts", "--yes", "--json"])
        self.assertEqual(command.group, "skills")
        self.assertEqual(command.skill, ["higantic-html-artifacts"])
        self.assertTrue(command.yes)
        self.assertTrue(command.json)
        login = parser.parse_args(["auth", "login", "--no-skill-offer"])
        self.assertTrue(login.no_skill_offer)


class CatalogAndConsentTests(unittest.TestCase):
    def test_yes_no_prompt_defaults_to_yes_on_enter(self):
        with mock.patch.object(INSTALLER.sys, "stdin", io.StringIO("\n")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertTrue(INSTALLER._ask_yes_no("Install? [Y/n]"))

        with mock.patch.object(INSTALLER.sys, "stdin", io.StringIO("n\n")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(INSTALLER._ask_yes_no("Install? [Y/n]"))

    def test_installed_skills_are_skipped_without_invoking_npx(self):
        with mock.patch.object(INSTALLER, "SKILL_CATALOG", FIXTURE_CATALOG):
            with mock.patch.object(INSTALLER, "_skill_is_installed", return_value=True):
                with mock.patch.object(INSTALLER, "_install") as install:
                    result = INSTALLER.install_skills()
        self.assertEqual(result["alreadyInstalled"], ["higantic-html-artifacts", "higantic-research"])
        self.assertEqual(result["installed"], [])
        install.assert_not_called()

    def test_noninteractive_install_requires_explicit_yes(self):
        with mock.patch.object(INSTALLER, "SKILL_CATALOG", FIXTURE_CATALOG):
            with mock.patch.object(INSTALLER, "_skill_is_installed", return_value=False):
                with mock.patch.object(INSTALLER, "_interactive_terminal", return_value=False):
                    with self.assertRaises(INSTALLER.SkillInstallError) as raised:
                        INSTALLER.install_skills()
        self.assertEqual(raised.exception.code, "interactive_required")

    def test_interactive_install_asks_for_each_missing_skill(self):
        with mock.patch.object(INSTALLER, "SKILL_CATALOG", FIXTURE_CATALOG):
            with mock.patch.object(INSTALLER, "_skill_is_installed", return_value=False):
                with mock.patch.object(INSTALLER, "_interactive_terminal", return_value=True):
                    with mock.patch.object(INSTALLER, "_ask_yes_no", side_effect=[True, False]) as ask:
                        with mock.patch.object(INSTALLER, "_install") as install:
                            with contextlib.redirect_stderr(io.StringIO()):
                                result = INSTALLER.install_skills()
        self.assertEqual(ask.call_count, 2)
        install.assert_called_once_with(FIXTURE_CATALOG[0])
        self.assertEqual(result["installed"], ["higantic-html-artifacts"])
        self.assertEqual(result["declined"], ["higantic-research"])

    def test_post_login_offer_is_silent_without_missing_skills_and_reviews_each_missing_skill(self):
        with mock.patch.object(INSTALLER, "_interactive_terminal", return_value=True):
            with mock.patch.object(INSTALLER, "missing_skills", return_value=[]):
                with mock.patch.object(INSTALLER, "install_skills") as install:
                    self.assertIsNone(INSTALLER.offer_skills_after_login())
                    install.assert_not_called()

        with mock.patch.object(INSTALLER, "_interactive_terminal", return_value=True):
            with mock.patch.object(INSTALLER, "missing_skills", return_value=[FIXTURE_CATALOG[1]]):
                with mock.patch.object(INSTALLER, "install_skills", return_value={"installed": []}) as install:
                    result = INSTALLER.offer_skills_after_login()
        self.assertEqual(result, {"installed": []})
        install.assert_called_once_with()


class ProcessSafetyTests(unittest.TestCase):
    def test_windows_resolves_the_cmd_launcher_without_a_shell(self):
        def resolve(candidate):
            return r"C:\\Program Files\\nodejs\\npx.cmd" if candidate == "npx.cmd" else None

        with mock.patch.object(INSTALLER.os, "name", "nt"):
            with mock.patch.object(INSTALLER.shutil, "which", side_effect=resolve) as which:
                self.assertEqual(INSTALLER._npx_executable(), r"C:\\Program Files\\nodejs\\npx.cmd")
        self.assertEqual(which.call_args_list, [mock.call("npx.cmd")])

    def test_installer_uses_fixed_argv_and_removes_higantic_credentials(self):
        entry = FIXTURE_CATALOG[1]
        completed = subprocess.CompletedProcess([], 0, "", "")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HIGANTIC_API_KEY": "never-forward-this-key",
            "HIGANTIC_AGENT_ID": "agent-a",
            "HIGANTIC_API_BASE_URL": "https://agent.higantic.com",
            "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL": "1",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(INSTALLER.shutil, "which", return_value="/usr/bin/npx"):
                with mock.patch.object(INSTALLER.subprocess, "run", return_value=completed) as run:
                    INSTALLER._install(entry)
        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertEqual(command, [
            "/usr/bin/npx", "--yes", "skills", "add", "Aneaire/higantic-skills",
            "--skill", "higantic-research", "--global", "--agent", "*", "--yes",
        ])
        self.assertNotIn("HIGANTIC_API_KEY", options["env"])
        self.assertNotIn("HIGANTIC_AGENT_ID", options["env"])
        self.assertNotIn("HIGANTIC_API_BASE_URL", options["env"])
        self.assertFalse(options.get("shell", False))

    def test_installer_failure_surfaces_only_a_bounded_control_free_reason(self):
        completed = subprocess.CompletedProcess([], 1, "", "\x1b[31mfirst line\x1b[0m\npackage failed\x07\u202e\n")
        with mock.patch.object(INSTALLER.shutil, "which", return_value="/usr/bin/npx"):
            with mock.patch.object(INSTALLER.subprocess, "run", return_value=completed):
                with self.assertRaises(INSTALLER.SkillInstallError) as raised:
                    INSTALLER._install(FIXTURE_CATALOG[1])
        message = str(raised.exception)
        self.assertIn("package failed", message)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("\x07", message)
        self.assertNotIn("\u202e", message)


class MainFlowTests(unittest.TestCase):
    def test_setup_confirms_cli_and_reviews_every_public_skill(self):
        result = {
            "scope": "global",
            "installed": ["higantic-html-artifacts", "higantic-excalidraw"],
            "alreadyInstalled": [],
            "declined": [],
            "failed": [],
        }
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "setup"]):
            with mock.patch.object(HTML, "install_skills", return_value=result) as install:
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(HTML.main(), 0)
        output = stdout.getvalue()
        self.assertIn("installed successfully", output)
        self.assertIn("Public skills  2", output)
        self.assertIn("HTML Artifacts, Excalidraw Canvas", output)
        install.assert_called_once_with(assume_yes=False)

    def test_setup_yes_is_noninteractive(self):
        result = {
            "scope": "global",
            "installed": [],
            "alreadyInstalled": ["higantic-html-artifacts", "higantic-excalidraw"],
            "declined": [],
            "failed": [],
        }
        with mock.patch.object(sys, "argv", ["higantic", "setup", "--yes"]):
            with mock.patch.object(HTML, "install_skills", return_value=result) as install:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(HTML.main(), 0)
        install.assert_called_once_with(assume_yes=True)

    def test_existing_profile_error_explains_safe_next_steps(self):
        stderr = io.StringIO()
        error = HTML.AuthError(
            0,
            "profile_exists",
            "Profile 'default' is already configured.",
            {"profile": "default"},
        )
        with mock.patch.object(sys, "argv", ["higantic", "auth", "login"]):
            with mock.patch.object(HTML, "execute_auth", side_effect=error):
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(HTML.main(), 2)
        output = stderr.getvalue()
        self.assertIn("Profile 'default' is already configured", output)
        self.assertIn("higantic auth status --profile default", output)
        self.assertIn("higantic auth logout --profile default", output)
        self.assertIn("higantic auth login --profile default", output)
        self.assertIn("higantic auth login --profile another-name", output)
        self.assertNotIn("HiGantic error [profile_exists]", output)

    def test_generic_auth_error_has_a_safe_contextual_hint(self):
        stderr = io.StringIO()
        error = HTML.AuthError(0, "connection_error", "Could not\x1b[31m connect.\u202e")
        with mock.patch.object(sys, "argv", ["higantic", "auth", "status"]):
            with mock.patch.object(HTML, "execute_auth", side_effect=error):
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(HTML.main(), 2)
        output = stderr.getvalue()
        self.assertIn("Next step", output)
        self.assertIn("higantic doctor", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\u202e", output)

    def test_explicit_skills_command_uses_english_by_default(self):
        result = {
            "scope": "global",
            "installed": [],
            "alreadyInstalled": ["higantic-html-artifacts"],
            "declined": [],
            "failed": [],
        }
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "skills", "install"]):
            with mock.patch.object(HTML, "install_skills", return_value=result):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(HTML.main(), 0)
        self.assertEqual(stdout.getvalue(), "HTML Artifacts is already installed globally.\n")

    def test_explicit_skills_command_supports_json_for_scripts(self):
        result = {
            "scope": "global",
            "installed": [],
            "alreadyInstalled": ["higantic-html-artifacts"],
            "declined": [],
            "failed": [],
        }
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "skills", "install", "--json"]):
            with mock.patch.object(HTML, "install_skills", return_value=result):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(HTML.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), result)

    def test_successful_login_stays_successful_when_optional_install_fails(self):
        auth_result = {
            "profile": "default",
            "agentId": "agent-a",
            "agentName": "Agent A",
            "apiBaseUrl": "https://agent.higantic.com",
            "scopes": ["html_artifacts:read"],
            "authenticated": True,
        }
        optional_result = {"failed": [{"slug": "higantic-research", "code": "skill_install_failed"}]}
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "auth", "login"]):
            with mock.patch.object(HTML, "execute_auth", return_value=auth_result):
                with mock.patch.object(HTML, "offer_skills_after_login", return_value=optional_result):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = HTML.main()
        self.assertEqual(code, 0)
        self.assertIn("◆ Signed in", stdout.getvalue())
        self.assertIn("Agent    Agent A (agent-a)", stdout.getvalue())
        self.assertIn("Profile  default", stdout.getvalue())
        self.assertIn("Authentication succeeded", stderr.getvalue())

        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "auth", "login"]):
            with mock.patch.object(HTML, "execute_auth", return_value=auth_result):
                with mock.patch.object(
                    HTML,
                    "offer_skills_after_login",
                    side_effect=HTML.SkillInstallError("invalid_skill_catalog", "catalog unavailable"),
                ):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                        code = HTML.main()
        self.assertEqual(code, 0)
        self.assertIn("Authentication succeeded", stderr.getvalue())

    def test_auth_json_is_explicit_and_suppresses_optional_skill_offer(self):
        auth_result = {
            "profile": "default",
            "agentId": "agent-a",
            "agentName": "Agent A",
            "apiBaseUrl": "https://agent.higantic.com",
            "scopes": ["html_artifacts:read"],
            "authenticated": True,
        }
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "auth", "login", "--json"]):
            with mock.patch.object(HTML, "execute_auth", return_value=auth_result):
                with mock.patch.object(HTML, "offer_skills_after_login", return_value=None) as offer:
                    with contextlib.redirect_stdout(stdout):
                        self.assertEqual(HTML.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), auth_result)
        offer.assert_called_once_with(True)

    def test_human_auth_results_cover_profiles_use_and_logout(self):
        profiles = HTML.format_auth_result("profiles", {
            "environmentOverrideActive": False,
            "profiles": [{"name": "work", "current": True, "agentName": "Agent A", "agentId": "agent-a"}],
        })
        self.assertIn("◆ work", profiles)
        self.assertIn("Agent A (agent-a)  active", profiles)
        self.assertEqual(HTML.format_auth_result("use", {"currentProfile": "work"}), "◆ Active profile changed\n  Profile  work")
        logout = HTML.format_auth_result("logout", {"profile": "work", "revoked": True})
        self.assertIn("◆ Signed out", logout)
        self.assertIn("API key  Revoked", logout)

    def test_doctor_human_output_and_failure_exit_status(self):
        result = {
            "version": "1.5.2",
            "status": "error",
            "healthy": False,
            "checks": [{"name": "HiGantic API", "status": "error", "message": "Could not connect."}],
        }
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["higantic", "doctor"]):
            with mock.patch.object(HTML, "run_doctor", return_value=result):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(HTML.main(), 2)
        self.assertIn("FAIL  HiGantic API", stdout.getvalue())
        self.assertIn("Could not connect.", stdout.getvalue())
        self.assertIn("Result  Problems found", stdout.getvalue())

    def test_explicit_skills_command_returns_failure_status_for_failed_installs(self):
        result = {
            "scope": "global",
            "installed": [],
            "alreadyInstalled": [],
            "declined": [],
            "failed": [{"slug": "higantic-html-artifacts", "code": "skill_install_failed"}],
        }
        with mock.patch.object(sys, "argv", ["higantic", "skills", "install", "--yes"]):
            with mock.patch.object(HTML, "install_skills", return_value=result):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(HTML.main(), 2)


if __name__ == "__main__":
    unittest.main()
