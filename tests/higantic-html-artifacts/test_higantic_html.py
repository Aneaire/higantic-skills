import contextlib
import io
import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "higantic-html-artifacts" / "scripts" / "higantic_html.py"
SECRET = "hgk_test_secret_never_echo"

SPEC = importlib.util.spec_from_file_location("higantic_html", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ApiBaseUrlTests(unittest.TestCase):
    def validate(self, value, **environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            return MODULE.validate_api_base_url(value)

    def test_accepts_official_origin_by_default(self):
        self.assertEqual(self.validate("https://agent.higantic.com"), "https://agent.higantic.com")
        self.assertEqual(self.validate("https://agent.higantic.com/"), "https://agent.higantic.com")

    def test_accepts_explicit_custom_https_origin_and_base_path(self):
        result = self.validate(
            "https://API.example.test/service/",
            HIGANTIC_ALLOW_CUSTOM_API_BASE_URL="1",
        )
        self.assertEqual(result, "https://api.example.test/service")

    def test_accepts_explicit_insecure_loopback_only_with_both_flags(self):
        environment = {
            "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL": "1",
            "HIGANTIC_ALLOW_INSECURE_LOCALHOST": "1",
        }
        self.assertEqual(self.validate("http://localhost:8080/api/", **environment), "http://localhost:8080/api")
        self.assertEqual(self.validate("http://[::1]:8080", **environment), "http://[::1]:8080")
        with self.assertRaises(MODULE.ApiError):
            self.validate("http://127.0.0.1:8080", HIGANTIC_ALLOW_CUSTOM_API_BASE_URL="1")

    def test_rejects_custom_origin_without_opt_in(self):
        with self.assertRaises(MODULE.ApiError) as raised:
            self.validate("https://api.example.test")
        self.assertEqual(raised.exception.code, "custom_api_base_url_not_allowed")

    def test_rejects_unsafe_destinations(self):
        environment = {
            "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL": "1",
            "HIGANTIC_ALLOW_INSECURE_LOCALHOST": "1",
        }
        unsafe = (
            "https://user:password@agent.higantic.com",
            "https://agent.higantic.com?target=other",
            "https://agent.higantic.com#fragment",
            "https:///missing-host",
            "ftp://agent.higantic.com",
            "http://api.example.test",
            "https://api.example.test/base/%2e%2e/private",
            "https://api.example.test/base/%252e%252e/private",
        )
        for value in unsafe:
            with self.subTest(value=value):
                with self.assertRaises(MODULE.ApiError):
                    self.validate(value, **environment)

    def test_redirect_handler_allows_same_origin_and_rejects_cross_origin(self):
        handler = MODULE.SameOriginRedirectHandler()
        request = MODULE.urllib.request.Request(
            "https://agent.higantic.com/start",
            headers={"Authorization": "Bearer fixture-value"},
        )
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://agent.higantic.com/next",
        )
        self.assertEqual(redirected.full_url, "https://agent.higantic.com/next")
        self.assertEqual(redirected.get_header("Authorization"), "Bearer fixture-value")
        with self.assertRaises(MODULE.ApiError) as raised:
            handler.redirect_request(request, None, 302, "Found", {}, "https://other.example/next")
        self.assertEqual(raised.exception.code, "unsafe_redirect")


class PathSegmentTests(unittest.TestCase):
    def test_validates_and_quotes_supported_identifiers(self):
        self.assertEqual(MODULE.segment("project:release-plan"), "project%3Arelease-plan")
        self.assertEqual(MODULE.segment("artifact with spaces"), "artifact%20with%20spaces")
        self.assertEqual(MODULE.segment("page-a_123"), "page-a_123")

    def test_rejects_dot_segments_separators_controls_and_recursive_encodings(self):
        excessive = "/"
        for _ in range(MODULE.MAX_SEGMENT_DECODE_ROUNDS + 2):
            excessive = MODULE.urllib.parse.quote(excessive, safe="")
        invalid = (
            "",
            ".",
            "..",
            "%2e",
            "%252e%252e",
            "/",
            "\\",
            "%2F",
            "%255c",
            "line\nbreak",
            "%00",
            excessive,
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(MODULE.ApiError) as raised:
                    MODULE.segment(value)
                self.assertEqual(raised.exception.code, "invalid_path_segment")
                self.assertNotIn(SECRET, str(raised.exception))


class Handler(BaseHTTPRequestHandler):
    queued_responses = []
    requests = []

    def _handle(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        content_type = self.headers.get("Content-Type")
        body = json.loads(raw) if raw and content_type and content_type.startswith("application/json") else None
        type(self).requests.append({
            "method": self.command,
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": content_type,
            "asset_name": self.headers.get("X-Asset-Name"),
            "idempotency_key": self.headers.get("Idempotency-Key"),
            "body": body,
            "raw": raw,
        })
        status, payload = type(self).queued_responses.pop(0)
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle

    def log_message(self, *_args):
        pass


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError as error:
            raise unittest.SkipTest(f"local sockets are blocked by this sandbox: {error}") from error
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)

    def setUp(self):
        Handler.queued_responses = []
        Handler.requests = []

    def run_cli(self, *args, input_text=None):
        env = {
            **os.environ,
            "HIGANTIC_API_BASE_URL": self.base_url,
            "HIGANTIC_AGENT_ID": "agent-a",
            "HIGANTIC_API_KEY": SECRET,
            "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL": "1",
            "HIGANTIC_ALLOW_INSECURE_LOCALHOST": "1",
        }
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=input_text, text=True, capture_output=True, env=env, check=False)

    def test_pages_list_uses_bearer_without_printing_key(self):
        Handler.queued_responses = [(200, {"data": {"pages": []}, "requestId": "r1"})]
        result = self.run_cli("pages", "list")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Handler.requests[0]["authorization"], f"Bearer {SECRET}")
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_create_commands_send_idempotency_and_external_keys(self):
        Handler.queued_responses = [
            (201, {"data": {"page": {"id": "page-a"}}}),
            (201, {"data": {"artifact": {"id": "artifact-a", "externalId": "campaign:42"}}}),
        ]
        page = self.run_cli("pages", "create", "--label", "Campaign", "--idempotency-key", "page-create-42")
        artifact = self.run_cli(
            "artifacts", "create",
            "--page-id", "page-a",
            "--title", "Campaign",
            "--external-id", "campaign:42",
            "--idempotency-key", "artifact-create-42",
        )
        self.assertEqual(page.returncode, 0)
        self.assertEqual(artifact.returncode, 0)
        self.assertEqual(Handler.requests[0]["idempotency_key"], "page-create-42")
        self.assertEqual(Handler.requests[1]["idempotency_key"], "artifact-create-42")
        self.assertEqual(Handler.requests[1]["body"]["externalId"], "campaign:42")

    def test_external_id_upsert_reads_then_sends_optimistic_precondition(self):
        Handler.queued_responses = [
            (200, {"data": {"artifact": {"id": "artifact-a", "currentRevision": 4, "version": 7, "externalId": "campaign:42"}}}),
            (200, {"data": {"artifact": {"id": "artifact-a", "currentRevision": 5}, "created": False}}),
        ]
        result = self.run_cli(
            "artifacts", "upsert",
            "--page-id", "page-a",
            "--external-id", "campaign:42",
            "--title", "Updated campaign",
            "--html-file", "-",
            input_text="<p>Updated</p>",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual([item["method"] for item in Handler.requests], ["GET", "PUT"])
        self.assertIn("/by-external-id/campaign%3A42", Handler.requests[1]["path"])
        self.assertEqual(Handler.requests[1]["body"]["expectedCurrentRevision"], 4)
        self.assertEqual(Handler.requests[1]["body"]["expectedArtifactVersion"], 7)

    def test_metadata_update_reads_then_sends_artifact_version(self):
        Handler.queued_responses = [
            (200, {"data": {"artifact": {"id": "artifact-a", "version": 8, "currentRevision": 4}}}),
            (200, {"data": {"artifact": {"id": "artifact-a", "title": "Renamed", "version": 9}}}),
        ]
        result = self.run_cli(
            "artifacts", "update",
            "--page-id", "page-a",
            "--artifact-id", "artifact-a",
            "--title", "Renamed",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual([item["method"] for item in Handler.requests], ["GET", "PATCH"])
        self.assertEqual(Handler.requests[1]["body"]["expectedArtifactVersion"], 8)

    def test_append_reads_current_revision_and_sends_precondition(self):
        Handler.queued_responses = [
            (200, {"data": {"artifact": {"currentRevision": 4}}}),
            (201, {"data": {"revision": {"revision": 5}, "url": "https://higantic.com/private"}}),
        ]
        result = self.run_cli("revisions", "append", "--page-id", "page-a", "--artifact-id", "artifact-a", "--html-file", "-", input_text="<!doctype html><html><body>Report</body></html>")
        self.assertEqual(result.returncode, 0)
        self.assertEqual([item["method"] for item in Handler.requests], ["GET", "POST"])
        self.assertEqual(Handler.requests[1]["body"]["expectedCurrentRevision"], 4)

    def test_conflict_stops_without_leaking_key(self):
        Handler.queued_responses = [
            (200, {"data": {"artifact": {"currentRevision": 4}}}),
            (409, {"error": {"code": "revision_conflict", "message": "Artifact changed"}, "requestId": "r2"}),
        ]
        result = self.run_cli("revisions", "restore", "--page-id", "page-a", "--artifact-id", "artifact-a", "--revision", "2")
        self.assertEqual(result.returncode, 3)
        self.assertIn("reconcile", result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_artifact_version_conflict_stops_without_leaking_key(self):
        Handler.queued_responses = [
            (200, {"data": {"artifact": {"version": 4}}}),
            (409, {"error": {"code": "artifact_version_conflict", "message": "Metadata changed"}, "requestId": "r3"}),
        ]
        result = self.run_cli(
            "artifacts", "update",
            "--page-id", "page-a",
            "--artifact-id", "artifact-a",
            "--title", "Renamed",
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("reconcile", result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_url_uses_private_page_url_returned_by_api(self):
        Handler.queued_responses = [(200, {"data": {"pages": [{"id": "page-a", "url": "https://app.example/agents/agent-a/tab/page-a"}]}})]
        result = self.run_cli("url", "--page-id", "page-a", "--artifact-id", "artifact-a", "--revision", "3")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "https://app.example/agents/agent-a/tab/page-a?artifact=artifact-a&revision=3")

    def test_assets_list_uses_scoped_asset_route_without_printing_key(self):
        Handler.queued_responses = [(200, {"data": {"assets": []}, "requestId": "r-assets"})]
        result = self.run_cli("assets", "list")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(Handler.requests[0]["method"], "GET")
        self.assertEqual(Handler.requests[0]["path"], "/v1/agents/agent-a/html-assets")
        self.assertEqual(Handler.requests[0]["authorization"], f"Bearer {SECRET}")
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_assets_upload_sends_validated_binary_request_without_printing_key(self):
        Handler.queued_responses = [(201, {"data": {"asset": {"id": "asset-a", "embedSource": "higantic-asset://asset-a"}}})]
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "hero.png"
            image.write_bytes(bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))
            result = self.run_cli("assets", "upload", "--file", str(image))
        self.assertEqual(result.returncode, 0)
        request = Handler.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/v1/agents/agent-a/html-assets")
        self.assertEqual(request["content_type"], "image/png")
        self.assertEqual(request["asset_name"], "hero.png")
        self.assertEqual(request["raw"], bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]))
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_delete_routes_require_confirmation_and_send_delete(self):
        unconfirmed_artifact = self.run_cli(
            "artifacts", "delete", "--page-id", "page-a", "--artifact-id", "artifact-a",
        )
        unconfirmed_asset = self.run_cli("assets", "delete", "--asset-id", "asset-a")
        self.assertEqual(unconfirmed_artifact.returncode, 2)
        self.assertEqual(unconfirmed_asset.returncode, 2)
        self.assertEqual(Handler.requests, [])

        Handler.queued_responses = [
            (200, {"data": {"artifactId": "artifact-a", "deleted": True}}),
            (200, {"data": {"assetId": "asset-a", "deleted": True}}),
        ]
        artifact = self.run_cli(
            "artifacts", "delete", "--page-id", "page-a", "--artifact-id", "artifact-a", "--confirm-delete",
        )
        asset = self.run_cli("assets", "delete", "--asset-id", "asset-a", "--confirm-delete")
        self.assertEqual(artifact.returncode, 0)
        self.assertEqual(asset.returncode, 0)
        self.assertEqual(Handler.requests[0]["method"], "DELETE")
        self.assertEqual(Handler.requests[0]["path"], "/v1/agents/agent-a/html-pages/page-a/artifacts/artifact-a")
        self.assertEqual(Handler.requests[1]["method"], "DELETE")
        self.assertEqual(Handler.requests[1]["path"], "/v1/agents/agent-a/html-assets/asset-a")

    def test_invalid_destructive_identifiers_fail_before_any_request(self):
        commands = (
            ("artifacts", "delete", "--page-id", "page-a", "--artifact-id", "..", "--confirm-delete"),
            ("assets", "delete", "--asset-id", "%2e%2e", "--confirm-delete"),
            (
                "shares", "revoke",
                "--page-id", "page-a",
                "--artifact-id", "artifact-a",
                "--share-id", "%252e%252e",
                "--confirm-revoke",
            ),
        )
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid_path_segment", result.stderr)
                self.assertEqual(Handler.requests, [])

    def test_share_lifecycle_is_explicit_and_only_create_rotate_show_capability(self):
        unconfirmed = self.run_cli(
            "shares", "create", "--page-id", "page-a", "--artifact-id", "artifact-a",
        )
        self.assertEqual(unconfirmed.returncode, 2)
        self.assertIn("confirm-public-sharing", unconfirmed.stderr)
        self.assertEqual(Handler.requests, [])

        Handler.queued_responses = [
            (201, {"data": {"share": {"id": "share-a", "revision": 2, "tokenPrefix": "abc"}, "capabilityUrl": "https://public.example/s/raw-create-token"}}),
            (200, {"data": {"shares": [{"id": "share-a", "revision": 2, "tokenPrefix": "abc"}]}}),
            (200, {"data": {"share": {"id": "share-a", "revokedAt": 123}}}),
            (201, {"data": {"share": {"id": "share-b", "revision": 2}, "capabilityUrl": "https://public.example/s/raw-rotate-token"}}),
        ]
        created = self.run_cli(
            "shares", "create",
            "--page-id", "page-a",
            "--artifact-id", "artifact-a",
            "--revision", "2",
            "--expires-at-ms", "4102444800000",
            "--confirm-public-sharing",
        )
        listed = self.run_cli("shares", "list", "--page-id", "page-a", "--artifact-id", "artifact-a")
        revoked = self.run_cli(
            "shares", "revoke",
            "--page-id", "page-a",
            "--artifact-id", "artifact-a",
            "--share-id", "share-a",
            "--confirm-revoke",
        )
        rotated = self.run_cli(
            "shares", "rotate",
            "--page-id", "page-a",
            "--artifact-id", "artifact-a",
            "--share-id", "share-a",
            "--confirm-public-sharing",
        )
        self.assertEqual([created.returncode, listed.returncode, revoked.returncode, rotated.returncode], [0, 0, 0, 0])
        self.assertIn("raw-create-token", created.stdout)
        self.assertIn("shown only once", created.stderr)
        self.assertNotIn("raw-create-token", listed.stdout + listed.stderr)
        self.assertNotIn("raw-create-token", revoked.stdout + revoked.stderr)
        self.assertIn("raw-rotate-token", rotated.stdout)
        self.assertEqual(Handler.requests[0]["body"], {"revision": 2, "expiresAt": 4102444800000})
        self.assertEqual(Handler.requests[0]["path"], "/v1/agents/agent-a/html-pages/page-a/artifacts/artifact-a/shares")
        self.assertEqual(Handler.requests[1]["method"], "GET")
        self.assertEqual(Handler.requests[2]["method"], "DELETE")
        self.assertEqual(Handler.requests[3]["path"], "/v1/agents/agent-a/html-pages/page-a/artifacts/artifact-a/shares/share-a/rotate")

    def test_share_list_defensively_redacts_raw_tokens_and_capability_urls(self):
        Handler.queued_responses = [(200, {"data": {"shares": [{
            "id": "share-a",
            "tokenPrefix": "safe-prefix",
            "token": "raw-list-token",
            "tokenHash": "raw-list-hash",
            "capabilityUrl": "https://public.example/s/raw-list-token",
        }]}})]
        result = self.run_cli("shares", "list", "--page-id", "page-a", "--artifact-id", "artifact-a")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("raw-list-token", result.stdout + result.stderr)
        self.assertNotIn("raw-list-hash", result.stdout + result.stderr)
        self.assertIn("safe-prefix", result.stdout)
        self.assertIn("[REDACTED]", result.stdout)

    def test_share_errors_redact_tokens_and_explain_disabled_feature(self):
        raw_share_token = "hgs_" + "A" * 43
        Handler.queued_responses = [(404, {"error": {
            "code": "not_found",
            "message": f"missing https://public.example/s/raw-error-token and {raw_share_token}",
            "details": {"token": "raw-detail-token", "authorization": f"Bearer {SECRET}"},
        }})]
        result = self.run_cli("shares", "list", "--page-id", "page-a", "--artifact-id", "artifact-a")
        self.assertEqual(result.returncode, 2)
        self.assertIn("HTML_ARTIFACT_PUBLIC_SHARING_ENABLED", result.stderr)
        self.assertNotIn("raw-error-token", result.stdout + result.stderr)
        self.assertNotIn("raw-detail-token", result.stdout + result.stderr)
        self.assertNotIn(raw_share_token, result.stdout + result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)


class OfflineCommandTests(unittest.TestCase):
    def test_http_error_echoing_api_key_is_redacted_without_a_socket(self):
        environment = {
            "HIGANTIC_API_BASE_URL": "https://proxy.example",
            "HIGANTIC_AGENT_ID": "agent-a",
            "HIGANTIC_API_KEY": SECRET,
            "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL": "1",
        }
        echoed = json.dumps({
            "error": {
                "code": f"proxy_{SECRET}",
                "message": f"upstream echoed {SECRET}",
                "details": {"authorization": f"Bearer {SECRET}"},
            }
        }).encode("utf-8")
        http_error = MODULE.urllib.error.HTTPError(
            "https://proxy.example/v1",
            502,
            "Bad Gateway",
            {},
            io.BytesIO(echoed),
        )

        stderr = io.StringIO()
        opener = mock.Mock()
        opener.open.side_effect = http_error
        try:
            with mock.patch.dict(os.environ, environment, clear=False):
                with mock.patch.object(sys, "argv", [str(SCRIPT), "pages", "list"]):
                    with mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener):
                        with contextlib.redirect_stderr(stderr):
                            result = MODULE.main()
        finally:
            http_error.close()

        self.assertEqual(result, 2)
        self.assertNotIn(SECRET, stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())

    def test_restore_reads_current_revision_before_writing(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def request(self, method, path="", body=None):
                self.calls.append((method, path, body))
                if method == "GET":
                    return {"artifact": {"currentRevision": 7}}
                return {"revision": {"revision": 8}}

        client = FakeClient()
        args = MODULE.build_parser().parse_args(["revisions", "restore", "--page-id", "page-a", "--artifact-id", "artifact-a", "--revision", "2"])
        MODULE.execute(client, args)
        self.assertEqual(client.calls[1][2]["expectedCurrentRevision"], 7)

    def test_url_comes_from_private_api_page_url(self):
        class FakeClient:
            def request(self, method, path="", body=None):
                return {"pages": [{"id": "page-a", "url": "https://private.example/agents/a/tab/page-a"}]}

        args = MODULE.build_parser().parse_args(["url", "--page-id", "page-a", "--artifact-id", "artifact-a"])
        self.assertEqual(MODULE.execute(FakeClient(), args), "https://private.example/agents/a/tab/page-a?artifact=artifact-a")


if __name__ == "__main__":
    unittest.main()
