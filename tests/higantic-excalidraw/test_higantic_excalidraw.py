import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "higantic-excalidraw" / "scripts" / "higantic_excalidraw.py"
SPEC = importlib.util.spec_from_file_location("higantic_excalidraw_tests", SCRIPT)
EXCALIDRAW = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(EXCALIDRAW)

KEY = "hgk_test_secret_that_must_never_be_printed"
ENVIRONMENT = {
    "HIGANTIC_API_BASE_URL": "https://agent.higantic.com",
    "HIGANTIC_AGENT_ID": "agent-a",
    "HIGANTIC_API_KEY": KEY,
}


class FakeResponse:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"data": {"ok": True}}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ParserAndConfigurationTests(unittest.TestCase):
    def test_commands_are_available_without_a_key_argument(self):
        parser = EXCALIDRAW.build_parser()
        created = parser.parse_args([
            "scenes", "create", "--page-id", "page-a", "--flowchart-file", "flow.json",
        ])
        self.assertEqual(created.group, "scenes")
        self.assertEqual(created.action, "create")
        replaced = parser.parse_args([
            "scenes", "replace", "--page-id", "page-a", "--scene-id", "scene-a",
            "--expected-version", "7", "--scene-file", "scene.json",
        ])
        self.assertEqual(replaced.expected_version, 7)
        for action in parser._actions:
            self.assertNotIn("api-key", " ".join(action.option_strings))

    def test_environment_triple_must_be_complete(self):
        with mock.patch.dict(os.environ, {"HIGANTIC_API_KEY": KEY}, clear=True):
            with self.assertRaises(EXCALIDRAW.ApiError) as raised:
                EXCALIDRAW._configuration()
        self.assertEqual(raised.exception.code, "incomplete_configuration")

    def test_custom_origins_require_explicit_opt_in(self):
        environment = dict(ENVIRONMENT, HIGANTIC_API_BASE_URL="https://example.test")
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(EXCALIDRAW.ApiError) as raised:
                EXCALIDRAW._configuration()
        self.assertEqual(raised.exception.code, "invalid_api_base_url")


class RequestTests(unittest.TestCase):
    def run_command(self, argv, opener):
        with mock.patch.dict(os.environ, ENVIRONMENT, clear=True):
            with mock.patch.object(EXCALIDRAW.urllib.request, "build_opener", return_value=opener):
                return EXCALIDRAW.execute(EXCALIDRAW.build_parser().parse_args(argv))

    def test_page_list_uses_agent_path_and_bearer_header(self):
        opener = FakeOpener()
        result = self.run_command(["pages", "list"], opener)
        request, timeout = opener.requests[0]
        self.assertEqual(result, {"data": {"ok": True}})
        self.assertEqual(request.full_url, "https://agent.higantic.com/v1/agents/agent-a/excalidraw-pages")
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(timeout, 30)

    def test_create_sends_semantic_flowchart_json(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as directory:
            flowchart = Path(directory) / "flow.json"
            flowchart.write_text(json.dumps({
                "direction": "left-to-right",
                "nodes": [{"id": "start", "label": "Start", "stage": "Intake"}],
                "edges": [],
            }), encoding="utf-8")
            self.run_command([
                "scenes", "create", "--page-id", "page-a", "--title", "Workflow",
                "--flowchart-file", str(flowchart),
            ], opener)
        request, _timeout = opener.requests[0]
        self.assertEqual(request.method, "POST")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["title"], "Workflow")
        self.assertEqual(body["flowchart"]["nodes"][0]["id"], "start")
        self.assertNotIn("scene", body)

    def test_replace_carries_expected_version(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as directory:
            scene = Path(directory) / "scene.json"
            scene.write_text(json.dumps({"type": "excalidraw", "version": 2, "elements": []}), encoding="utf-8")
            self.run_command([
                "scenes", "replace", "--page-id", "page-a", "--scene-id", "scene-a",
                "--expected-version", "4", "--scene-file", str(scene),
            ], opener)
        request, _timeout = opener.requests[0]
        self.assertEqual(request.method, "PUT")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["expectedVersion"], 4)

    def test_delete_requires_confirmation_and_sends_preconditions(self):
        with mock.patch.dict(os.environ, ENVIRONMENT, clear=True):
            args = EXCALIDRAW.build_parser().parse_args([
                "scenes", "delete", "--page-id", "page-a", "--scene-id", "scene-a",
                "--expected-version", "9",
            ])
            with self.assertRaises(EXCALIDRAW.ApiError) as raised:
                EXCALIDRAW.execute(args)
        self.assertEqual(raised.exception.code, "confirmation_required")

        opener = FakeOpener()
        self.run_command([
            "scenes", "delete", "--page-id", "page-a", "--scene-id", "scene-a",
            "--expected-version", "9", "--confirm-delete",
        ], opener)
        request, _timeout = opener.requests[0]
        self.assertEqual(request.method, "DELETE")
        self.assertEqual(request.get_header("If-match"), "9")
        self.assertEqual(request.get_header("X-confirm-delete"), "true")

    def test_version_conflict_returns_exit_three_and_redacts_key(self):
        payload = json.dumps({
            "error": {"code": "scene_version_conflict", "message": "Conflict for " + KEY},
        }).encode("utf-8")
        conflict = urllib.error.HTTPError(
            "https://agent.higantic.com/v1/test", 409, "Conflict", {}, io.BytesIO(payload),
        )
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, ENVIRONMENT, clear=True):
            with mock.patch.object(EXCALIDRAW.urllib.request, "build_opener", return_value=FakeOpener(conflict)):
                with contextlib.redirect_stderr(stderr):
                    code = EXCALIDRAW.main(["pages", "list"])
        self.assertEqual(code, 3)
        self.assertIn("scene_version_conflict", stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())
        self.assertNotIn(KEY, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
