import argparse
import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path, PosixPath
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "higantic-html-artifacts" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import higantic_auth as AUTH
import higantic_secure_store as STORE

HTML_SPEC = importlib.util.spec_from_file_location("higantic_html_auth_tests", SCRIPTS / "higantic_html.py")
HTML = importlib.util.module_from_spec(HTML_SPEC)
assert HTML_SPEC and HTML_SPEC.loader
HTML_SPEC.loader.exec_module(HTML)

KEY = "hgk_" + "0123456789ab_0123456789abcdef0123456789abcdef0123456789abcdef"


class FakeStore:
    kind = "native"

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.preflight_count = 0
        self.puts = []
        self.deletes = []

    def preflight(self):
        self.preflight_count += 1

    def get(self, profile):
        return self.values.get(profile)

    def put(self, profile, secret):
        self.values[profile] = secret
        self.puts.append((profile, secret))

    def delete(self, profile):
        self.values.pop(profile, None)
        self.deletes.append(profile)


class ConfigPathTests(unittest.TestCase):
    def test_platform_config_paths(self):
        with mock.patch.object(Path, "home", return_value=Path("/" + "home/tester")):
            with mock.patch.object(STORE.sys, "platform", "linux"):
                with mock.patch.object(STORE.os, "name", "posix"):
                    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True):
                        self.assertEqual(STORE.config_path(), Path("/tmp/xdg/higantic/config.json"))
                    with mock.patch.dict(os.environ, {}, clear=True):
                        self.assertEqual(STORE.config_path(), Path("/" + "home/tester/.config/higantic/config.json"))
            with mock.patch.object(STORE.sys, "platform", "darwin"):
                self.assertEqual(STORE.config_path(), Path("/" + "home/tester/Library/Application Support/HiGantic/cli/config.json"))
            with mock.patch.object(STORE.sys, "platform", "win32"):
                with mock.patch.object(STORE.os, "name", "nt"):
                    with mock.patch.object(STORE, "Path", side_effect=lambda value: PosixPath(value)):
                        with mock.patch.dict(os.environ, {"APPDATA": "C:/" + "Users/tester/AppData/Roaming"}, clear=True):
                            self.assertEqual(str(STORE.config_path()), "C:/" + "Users/tester/AppData/Roaming/HiGantic/cli/config.json")

    def test_native_store_selects_only_the_platform_store(self):
        with mock.patch.object(STORE.sys, "platform", "darwin"):
            with mock.patch.object(STORE, "MacOSKeychainStore", return_value="mac"):
                self.assertEqual(STORE.native_store(), "mac")
        with mock.patch.object(STORE.sys, "platform", "linux"):
            with mock.patch.object(STORE.os, "name", "posix"):
                with mock.patch.object(STORE, "LinuxSecretServiceStore", return_value="linux"):
                    self.assertEqual(STORE.native_store(), "linux")
        with mock.patch.object(STORE.sys, "platform", "win32"):
            with mock.patch.object(STORE.os, "name", "nt"):
                with mock.patch.object(STORE, "WindowsCredentialStore", return_value="windows"):
                    self.assertEqual(STORE.native_store(), "windows")


class EnvironmentResolutionTests(unittest.TestCase):
    def test_complete_environment_triple_wins_without_profiles(self):
        environment = {
            "HIGANTIC_API_BASE_URL": "https://agent.higantic.com",
            "HIGANTIC_AGENT_ID": "agent-env",
            "HIGANTIC_API_KEY": KEY,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(AUTH, "load_config", side_effect=AssertionError("profiles must not be loaded")):
                result = AUTH.resolve_credentials("ignored")
        self.assertEqual(result["source"], "environment")
        self.assertEqual(result["agentId"], "agent-env")
        self.assertEqual(result["apiKey"], KEY)

    def test_partial_environment_never_combines_with_profile(self):
        with mock.patch.dict(os.environ, {"HIGANTIC_API_BASE_URL": "https://agent.higantic.com"}, clear=True):
            with self.assertRaises(AUTH.AuthError) as raised:
                AUTH.resolve_credentials("default")
        self.assertEqual(raised.exception.code, "incomplete_environment")

    def test_destination_is_validated_before_secure_store_read(self):
        config = {
            "version": 1,
            "currentProfile": "default",
            "profiles": {"default": {"apiBaseUrl": "https://evil.example", "agentId": "agent-a", "storage": "native"}},
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(AUTH, "load_config", return_value=config):
                with mock.patch.object(AUTH, "open_store", side_effect=AssertionError("secret store was read before destination validation")):
                    with self.assertRaises(AUTH.AuthError) as raised:
                        AUTH.resolve_credentials(None)
        self.assertEqual(raised.exception.code, "custom_api_base_url_not_allowed")

    def test_verification_urls_are_pinned_and_never_allow_browser_protocol_injection(self):
        self.assertEqual(AUTH.OFFICIAL_VERIFICATION_URI, "https://higantic.com/auth/device")
        valid = AUTH.validate_verification_urls(
            AUTH.OFFICIAL_API_ORIGIN,
            AUTH.OFFICIAL_VERIFICATION_URI,
            AUTH.OFFICIAL_VERIFICATION_URI + "#code=ABCD-EFGH",
            "ABCD-EFGH",
        )
        self.assertEqual(valid[1], AUTH.OFFICIAL_VERIFICATION_URI + "#code=ABCD-EFGH")
        for complete in (
            "file:///tmp/device",
            "https://evil.example/auth/device#code=ABCD-EFGH",
            AUTH.OFFICIAL_VERIFICATION_URI + "?code=ABCD-EFGH",
            AUTH.OFFICIAL_VERIFICATION_URI + "#code=WXYZ-2345",
        ):
            with self.assertRaises(AUTH.AuthError):
                AUTH.validate_verification_urls(
                    AUTH.OFFICIAL_API_ORIGIN,
                    AUTH.OFFICIAL_VERIFICATION_URI,
                    complete,
                    "ABCD-EFGH",
                )


class ParserTests(unittest.TestCase):
    def test_default_login_scopes_cover_private_html_and_canvas_without_sharing(self):
        scopes = AUTH._requested_scopes(None)
        self.assertIn("html_artifacts:read", scopes)
        self.assertIn("excalidraw:read", scopes)
        self.assertIn("excalidraw:write", scopes)
        self.assertIn("excalidraw_pages:create", scopes)
        self.assertNotIn("html_artifacts:share", scopes)
        self.assertNotIn("excalidraw:share", scopes)

    def test_auth_commands_and_global_profile_are_available_without_key_argument(self):
        parser = HTML.build_parser()
        login = parser.parse_args(["--profile", "work", "auth", "login", "--no-browser", "--json"])
        self.assertEqual(login.profile, "work")
        self.assertTrue(login.no_browser)
        self.assertTrue(login.json)
        imported = parser.parse_args(["auth", "import", "--profile", "work", "--stdin"])
        self.assertEqual(imported.profile, "work")
        selected = parser.parse_args(["auth", "use", "work", "--allow-protected-file"])
        self.assertTrue(selected.allow_protected_file)
        profiles = parser.parse_args(["auth", "profiles", "--json"])
        self.assertEqual(profiles.command, "profiles")
        self.assertTrue(profiles.json)
        doctor = parser.parse_args(["doctor", "--profile", "work", "--offline", "--json"])
        self.assertEqual(doctor.group, "doctor")
        self.assertEqual(doctor.profile, "work")
        self.assertTrue(doctor.offline)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["auth", "login", "--replace"])
            with self.assertRaises(SystemExit):
                parser.parse_args(["auth", "import", "--stdin", "--api-key", KEY])

    def test_split_auth_command_gets_a_concise_correction(self):
        parser = HTML.build_parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                parser.parse_args(["auth", "log", "out"])
        self.assertEqual(raised.exception.code, 2)
        output = stderr.getvalue()
        self.assertIn("◆ Command not recognized", output)
        self.assertIn("higantic auth logout", output)
        self.assertNotIn("argument command", output)
        self.assertNotIn("higantic_html.py", output)

    def test_parser_error_does_not_echo_unknown_option_values(self):
        parser = HTML.build_parser()
        secret = "not-a-real-key-but-never-print-this"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                parser.parse_args(["auth", "status", "--api-key", secret])
        self.assertNotIn(secret, stderr.getvalue())
        self.assertIn("Some options aren’t valid", stderr.getvalue())


class ProfileCommandTests(unittest.TestCase):
    def setUp(self):
        AUTH._REGISTERED_SECRETS.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = Path(self.directory.name) / "config.json"
        self.store = FakeStore()
        self.environment = mock.patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.path_patch = mock.patch.object(AUTH, "config_path", return_value=self.config_path)
        self.path_patch.start()
        self.store_patch = mock.patch.object(AUTH, "open_store", return_value=self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.path_patch.stop()
        self.environment.stop()
        self.directory.cleanup()

    def args(self, **values):
        defaults = {
            "profile": "work",
            "api_base_url": None,
            "scope": None,
            "no_browser": True,
            "replace": False,
            "storage": None,
            "allow_protected_file": False,
            "stdin": True,
            "offline": False,
            "json": False,
            "yes": True,
            "local_only": False,
        }
        defaults.update(values)
        return argparse.Namespace(**defaults)

    def test_login_preflights_sleeps_before_poll_honors_slow_down_and_never_outputs_key(self):
        requests = []

        class FakeClient:
            def __init__(self, base_url):
                self.base_url = base_url

            def request(self, method, path, body=None, key=None):
                requests.append((method, path, body, key))
                if path.endswith("/code"):
                    return {
                        "device_code": "hgd_" + "A" * 43,
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://higantic.com/auth/device",
                        "verification_uri_complete": "https://higantic.com/auth/device#code=ABCD-EFGH",
                        "expires_in": 600,
                        "interval": 5,
                    }
                polls = sum(1 for item in requests if item[1].endswith("/token"))
                if polls == 1:
                    raise AUTH.AuthError(400, "slow_down", "wait", retry_after=12)
                return {"access_token": KEY, "agent_id": "agent-a", "agent_name": "Agent A", "scope": "html_artifacts:read"}

        sleeps = []
        stderr = io.StringIO()
        with mock.patch.object(AUTH, "AuthHttpClient", FakeClient):
            with mock.patch.object(AUTH.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)):
                with contextlib.redirect_stderr(stderr):
                    result = AUTH.auth_login(self.args())
        self.assertEqual(self.store.preflight_count, 1)
        self.assertEqual(sleeps, [5, 12])
        self.assertEqual(result["agentId"], "agent-a")
        self.assertEqual(self.store.values["work"], KEY)
        self.assertNotIn(KEY, stderr.getvalue())
        self.assertIn("ABCD-EFGH", stderr.getvalue())
        self.assertIn("Waiting for browser approval", stderr.getvalue())
        self.assertIn("Approval received", stderr.getvalue())
        config = json.loads(self.config_path.read_text())
        self.assertNotIn(KEY, json.dumps(config))
        self.assertEqual(config["currentProfile"], "work")

    def test_import_reads_one_line_validates_remotely_and_rejects_extra_input(self):
        class FakeClient:
            def __init__(self, base_url):
                self.base_url = base_url

            def request(self, method, path, body=None, key=None):
                self_key = key
                if self_key != KEY:
                    raise AssertionError("wrong key")
                return {"agentId": "agent-a", "agentName": "Agent A", "scopes": ["html_artifacts:read"]}

        with mock.patch.object(AUTH, "AuthHttpClient", FakeClient):
            with mock.patch.object(sys, "stdin", io.StringIO(KEY + "\n")):
                result = AUTH.auth_import(self.args())
        self.assertEqual(result["profile"], "work")
        self.assertEqual(self.store.values["work"], KEY)

        self.store.values.clear()
        self.config_path.unlink()
        with mock.patch.object(AUTH, "AuthHttpClient", FakeClient):
            with mock.patch.object(sys, "stdin", io.StringIO(KEY + "\n" + KEY + "\n")):
                with self.assertRaises(AUTH.AuthError) as raised:
                    AUTH.auth_import(self.args())
        self.assertEqual(raised.exception.code, "invalid_import")

        with mock.patch.object(AUTH, "AuthHttpClient", FakeClient):
            with mock.patch.object(sys, "stdin", io.StringIO("x" * (AUTH.MAX_IMPORT_BYTES + 1))):
                with self.assertRaises(AUTH.AuthError) as raised:
                    AUTH.auth_import(self.args())
        self.assertEqual(raised.exception.code, "invalid_import")

    def test_status_is_remote_by_default_offline_on_request_and_never_returns_secret(self):
        config = {
            "version": 1,
            "currentProfile": "work",
            "profiles": {
                "work": {
                    "apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN,
                    "agentId": "agent-a",
                    "agentName": "Stored Agent",
                    "storage": "native",
                    "scopes": ["html_artifacts:read"],
                }
            },
        }
        AUTH.save_config(config)
        self.store.values["work"] = KEY
        calls = []

        class FakeClient:
            def __init__(self, base_url):
                self.base_url = base_url

            def request(self, method, path, body=None, key=None):
                calls.append((method, path, key))
                return {"agentId": "agent-a", "agentName": "Remote Agent", "scopes": ["html_artifacts:read"]}

        with mock.patch.object(AUTH, "AuthHttpClient", FakeClient):
            remote = AUTH.auth_status(self.args())
            offline = AUTH.auth_status(self.args(offline=True))
        self.assertEqual(calls, [("GET", "/v1/auth/status", KEY)])
        self.assertEqual(remote["agentName"], "Remote Agent")
        self.assertTrue(offline["offline"])
        self.assertNotIn(KEY, json.dumps(remote))
        self.assertNotIn(KEY, json.dumps(offline))

    def test_profile_storage_failure_removes_the_uncommitted_secret_and_metadata(self):
        config = {
            "version": 1,
            "currentProfile": None,
            "profiles": {},
        }
        record = {
            "apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN,
            "agentId": "new-agent",
            "storage": "native",
            "scopes": ["html_artifacts:read"],
        }
        with mock.patch.object(AUTH, "save_config", side_effect=[OSError("disk full"), None]) as save:
            with self.assertRaises(AUTH.AuthError) as raised:
                AUTH._store_profile(
                    config,
                    "work",
                    None,
                    self.store,
                    "native",
                    KEY,
                    record,
                    None,
                    False,
                )
        self.assertEqual(raised.exception.code, "credential_store_failed")
        self.assertNotIn("work", self.store.values)
        self.assertNotIn("work", config["profiles"])
        self.assertIsNone(config["currentProfile"])
        self.assertEqual(save.call_count, 2)

    def test_existing_profile_must_be_revoked_before_reauthentication(self):
        config = {
            "version": 1,
            "currentProfile": "work",
            "profiles": {"work": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-a", "storage": "native"}},
        }
        with self.assertRaises(AUTH.AuthError) as raised:
            AUTH._prepare_profile(self.args(replace=True), config)
        self.assertEqual(raised.exception.code, "profile_exists")
        self.assertEqual(raised.exception.details, {"profile": "work"})
        self.assertEqual(self.store.preflight_count, 0)

    def test_profile_use_requires_a_retrievable_current_scoped_key(self):
        config = {
            "version": 1,
            "currentProfile": None,
            "profiles": {"work": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-a", "storage": "native"}},
        }
        AUTH.save_config(config)
        with self.assertRaises(AUTH.AuthError) as raised:
            AUTH.auth_use(self.args(name="work"))
        self.assertEqual(raised.exception.code, "credential_not_found")
        self.assertIsNone(AUTH.load_config()["currentProfile"])

        self.store.values["work"] = KEY
        result = AUTH.auth_use(self.args(name="work"))
        self.assertEqual(result["currentProfile"], "work")
        self.assertEqual(AUTH.load_config()["currentProfile"], "work")

    def test_profiles_lists_metadata_without_reading_secure_storage(self):
        config = {
            "version": 1,
            "currentProfile": "work",
            "profiles": {
                "other": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-b", "storage": "native"},
                "work": {
                    "apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN,
                    "agentId": "agent-a",
                    "agentName": "Agent A",
                    "storage": "native",
                    "scopes": ["html_artifacts:read"],
                },
            },
        }
        AUTH.save_config(config)
        with mock.patch.object(self.store, "get", side_effect=AssertionError("profile listing must not read secrets")):
            result = AUTH.auth_profiles(self.args())
        self.assertEqual([item["name"] for item in result["profiles"]], ["other", "work"])
        self.assertTrue(result["profiles"][1]["current"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_remote_logout_failure_retains_profile_and_secret(self):
        config = {
            "version": 1,
            "currentProfile": "work",
            "profiles": {"work": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-a", "storage": "native"}},
        }
        AUTH.save_config(config)
        self.store.values["work"] = KEY

        class FailingClient:
            def __init__(self, base_url):
                pass

            def request(self, method, path, body=None, key=None):
                raise AUTH.AuthError(503, "connection_error", "offline")

        with mock.patch.object(AUTH, "AuthHttpClient", FailingClient):
            with self.assertRaises(AUTH.AuthError):
                AUTH.auth_logout(self.args())
        self.assertEqual(self.store.values["work"], KEY)
        self.assertIn("work", AUTH.load_config()["profiles"])

    def test_local_only_logout_does_not_switch_to_another_profile(self):
        config = {
            "version": 1,
            "currentProfile": "work",
            "profiles": {
                "work": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-a", "storage": "native"},
                "other": {"apiBaseUrl": AUTH.OFFICIAL_API_ORIGIN, "agentId": "agent-b", "storage": "native"},
            },
        }
        AUTH.save_config(config)
        self.store.values["work"] = KEY
        result = AUTH.auth_logout(self.args(local_only=True))
        self.assertIsNone(result["currentProfile"])
        self.assertIsNone(AUTH.load_config()["currentProfile"])
        self.assertIn("other", AUTH.load_config()["profiles"])


@unittest.skipIf(os.name == "nt", "POSIX permission checks")
class ProtectedFileTests(unittest.TestCase):
    def test_protected_file_requires_opt_in_and_rejects_insecure_modes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "higantic"
            with mock.patch.object(STORE, "config_directory", return_value=root):
                with self.assertRaises(STORE.SecureStoreError):
                    STORE.ProtectedFileStore(False)
                store = STORE.ProtectedFileStore(True)
                store.put("work", KEY)
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
                self.assertEqual(store.get("work"), KEY)
                os.chmod(store.path, 0o644)
                with self.assertRaises(STORE.SecureStoreError):
                    store.get("work")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "higantic"
            root.mkdir(mode=0o700)
            target = Path(directory) / "target"
            target.write_text("{}")
            (root / "credentials.json").symlink_to(target)
            with mock.patch.object(STORE, "config_directory", return_value=root):
                with self.assertRaises(STORE.SecureStoreError):
                    STORE.ProtectedFileStore(True)

    def test_profile_config_rejects_insecure_modes_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "higantic"
            root.mkdir(mode=0o700)
            config = root / "config.json"
            config.write_text('{"version":1,"currentProfile":null,"profiles":{}}')
            os.chmod(config, 0o644)
            with mock.patch.object(AUTH, "config_path", return_value=config):
                with self.assertRaises(AUTH.AuthError) as raised:
                    AUTH.load_config()
            self.assertEqual(raised.exception.code, "invalid_config")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "higantic"
            root.mkdir(mode=0o700)
            target = Path(directory) / "config-target"
            target.write_text('{"version":1,"currentProfile":null,"profiles":{}}')
            (root / "config.json").symlink_to(target)
            with mock.patch.object(AUTH, "config_path", return_value=root / "config.json"):
                with self.assertRaises(AUTH.AuthError) as raised:
                    AUTH.load_config()
            self.assertEqual(raised.exception.code, "invalid_config")


if __name__ == "__main__":
    unittest.main()
