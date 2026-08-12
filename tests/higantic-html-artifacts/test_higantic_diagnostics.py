import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "higantic-html-artifacts" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("higantic_diagnostics_tests", SCRIPTS / "higantic_diagnostics.py")
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(DIAGNOSTICS)

KEY = "hgk_" + "0123456789ab_0123456789abcdef0123456789abcdef0123456789abcdef"


class DoctorTests(unittest.TestCase):
    def test_first_run_reports_actionable_warnings_without_mutating_storage(self):
        config = {"version": 1, "currentProfile": None, "profiles": {}}
        with mock.patch.object(DIAGNOSTICS, "environment_state", return_value=(False, {})):
            with mock.patch.object(DIAGNOSTICS, "load_config", return_value=config):
                with mock.patch.object(
                    DIAGNOSTICS,
                    "resolve_credentials",
                    side_effect=DIAGNOSTICS.AuthError(0, "profile_not_selected", "Choose a profile."),
                ):
                    with mock.patch.object(DIAGNOSTICS, "open_store", return_value=object()) as open_store:
                        with mock.patch.object(DIAGNOSTICS, "installer_available", return_value={"available": False, "message": "Install npx."}):
                            result = DIAGNOSTICS.run_doctor(offline=True)
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["healthy"])
        self.assertIn("higantic auth login", json.dumps(result))
        self.assertIn("Install npx", json.dumps(result))
        open_store.assert_called_once_with("native", False)

    def test_authenticated_api_check_never_returns_the_key(self):
        credentials = {
            "source": "profile",
            "profile": "work",
            "apiBaseUrl": "https://agent.higantic.com",
            "agentId": "agent-a",
            "apiKey": KEY,
            "record": {},
        }

        class Client:
            def __init__(self, base_url):
                self.base_url = base_url

            def request(self, method, path, body=None, key=None):
                self.key = key
                if path.endswith("/html-asset-targets"):
                    return {"targets": [{"target": "higantic", "available": True}]}
                return {"agentId": "agent-a"}

        config = {"version": 1, "currentProfile": "work", "profiles": {"work": {}}}
        with mock.patch.object(DIAGNOSTICS, "environment_state", return_value=(False, {})):
            with mock.patch.object(DIAGNOSTICS, "load_config", return_value=config):
                with mock.patch.object(DIAGNOSTICS, "resolve_credentials", return_value=credentials):
                    with mock.patch.object(DIAGNOSTICS, "AuthHttpClient", Client):
                        with mock.patch.object(DIAGNOSTICS, "installer_available", return_value={"available": True, "message": "npx ready"}):
                            result = DIAGNOSTICS.run_doctor()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["healthy"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_api_failure_marks_doctor_unhealthy(self):
        credentials = {
            "source": "environment",
            "profile": None,
            "apiBaseUrl": "https://agent.higantic.com",
            "agentId": "agent-a",
            "apiKey": KEY,
            "record": {},
        }

        class Client:
            def __init__(self, _base_url):
                pass

            def request(self, *_args, **_kwargs):
                raise DIAGNOSTICS.AuthError(0, "connection_error", "Could not connect.")

        config = {"version": 1, "currentProfile": None, "profiles": {}}
        with mock.patch.object(DIAGNOSTICS, "environment_state", return_value=(True, {})):
            with mock.patch.object(DIAGNOSTICS, "load_config", return_value=config):
                with mock.patch.object(DIAGNOSTICS, "resolve_credentials", return_value=credentials):
                    with mock.patch.object(DIAGNOSTICS, "AuthHttpClient", Client):
                        with mock.patch.object(DIAGNOSTICS, "installer_available", return_value={"available": True, "message": "npx ready"}):
                            result = DIAGNOSTICS.run_doctor()
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["healthy"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_missing_configured_credential_is_an_error_but_offline_skip_is_not(self):
        config = {"version": 1, "currentProfile": "work", "profiles": {"work": {}}}
        with mock.patch.object(DIAGNOSTICS, "environment_state", return_value=(False, {})):
            with mock.patch.object(DIAGNOSTICS, "load_config", return_value=config):
                with mock.patch.object(
                    DIAGNOSTICS,
                    "resolve_credentials",
                    side_effect=DIAGNOSTICS.AuthError(0, "credential_not_found", "Credential missing."),
                ):
                    with mock.patch.object(DIAGNOSTICS, "installer_available", return_value={"available": True, "message": "npx ready"}):
                        missing = DIAGNOSTICS.run_doctor(offline=True)
        self.assertEqual(missing["status"], "error")
        self.assertFalse(missing["healthy"])

        credentials = {
            "source": "profile",
            "profile": "work",
            "apiBaseUrl": "https://agent.higantic.com",
            "agentId": "agent-a",
            "apiKey": KEY,
            "record": {},
        }
        with mock.patch.object(DIAGNOSTICS, "environment_state", return_value=(False, {})):
            with mock.patch.object(DIAGNOSTICS, "load_config", return_value=config):
                with mock.patch.object(DIAGNOSTICS, "resolve_credentials", return_value=credentials):
                    with mock.patch.object(DIAGNOSTICS, "installer_available", return_value={"available": True, "message": "npx ready"}):
                        healthy = DIAGNOSTICS.run_doctor(offline=True)
        self.assertEqual(healthy["status"], "ok")
        self.assertTrue(healthy["healthy"])


if __name__ == "__main__":
    unittest.main()
