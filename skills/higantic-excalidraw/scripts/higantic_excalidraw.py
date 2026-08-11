#!/usr/bin/env python3
"""Dependency-free CLI for HiGantic's direct Excalidraw API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


OFFICIAL_API_BASE_URL = "https://agent.higantic.com"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 800 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ApiError(code, "redirect_rejected", "Cross-request redirects are not allowed.")


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _configuration() -> Dict[str, str]:
    names = ("HIGANTIC_API_BASE_URL", "HIGANTIC_AGENT_ID", "HIGANTIC_API_KEY")
    values = {name: _env(name) for name in names}
    present = [name for name, value in values.items() if value]
    if present and len(present) != len(names):
        raise ApiError(0, "incomplete_configuration", "Set the complete HIGANTIC_API_BASE_URL, HIGANTIC_AGENT_ID, and HIGANTIC_API_KEY environment triple.")
    if not present:
        raise ApiError(0, "missing_configuration", "Generate a scoped key in Settings → Excalidraw, then set HIGANTIC_API_BASE_URL, HIGANTIC_AGENT_ID, and HIGANTIC_API_KEY.")

    parsed = urllib.parse.urlsplit(values["HIGANTIC_API_BASE_URL"])
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ApiError(0, "invalid_api_base_url", "The API base URL cannot contain credentials, a query, or a fragment.")
    normalized = urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))
    if normalized != OFFICIAL_API_BASE_URL:
        allow_custom = _env("HIGANTIC_ALLOW_CUSTOM_API_BASE_URL") == "1"
        allow_local = _env("HIGANTIC_ALLOW_INSECURE_LOCALHOST") == "1"
        host = (parsed.hostname or "").lower()
        local_http = parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
        if local_http:
            if not allow_local:
                raise ApiError(0, "invalid_api_base_url", "Loopback HTTP requires HIGANTIC_ALLOW_INSECURE_LOCALHOST=1.")
        elif parsed.scheme != "https" or not allow_custom:
            raise ApiError(0, "invalid_api_base_url", "A custom HTTPS origin requires HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1.")
    if not ID_PATTERN.fullmatch(values["HIGANTIC_AGENT_ID"]):
        raise ApiError(0, "invalid_agent_id", "HIGANTIC_AGENT_ID is invalid.")
    return {
        "base_url": normalized,
        "agent_id": values["HIGANTIC_AGENT_ID"],
        "api_key": values["HIGANTIC_API_KEY"],
    }


def _safe_id(value: str, label: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ApiError(0, "invalid_identifier", "%s is invalid." % label)
    return urllib.parse.quote(value, safe="")


def _read_json_file(path_value: str) -> Any:
    path = Path(path_value).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ApiError(0, "invalid_input_file", "Input must be a regular, non-symlink JSON file.")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ApiError(0, "input_too_large", "Input JSON exceeds 800 KiB.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ApiError(0, "invalid_input_file", "Input file is not valid UTF-8 JSON: %s" % error) from None


def _payload_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    if bool(args.flowchart_file) == bool(args.scene_file):
        raise ApiError(0, "invalid_input", "Provide exactly one of --flowchart-file or --scene-file.")
    payload: Dict[str, Any] = {}
    if args.title:
        payload["title"] = args.title
    if args.flowchart_file:
        payload["flowchart"] = _read_json_file(args.flowchart_file)
    else:
        payload["scene"] = _read_json_file(args.scene_file)
    return payload


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    config = _configuration()
    url = config["base_url"] + path
    request_headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + config["api_key"],
        "User-Agent": "higantic-excalidraw-skill/1.0",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ApiError(response.status, "response_too_large", "API response exceeded 2 MiB.")
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as error:
        raw = error.read(MAX_RESPONSE_BYTES + 1)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeError, json.JSONDecodeError):
            payload = {}
        api_error = payload.get("error", {}) if isinstance(payload, dict) else {}
        raise ApiError(
            error.code,
            str(api_error.get("code") or "http_error"),
            str(api_error.get("message") or "HiGantic API request failed."),
            api_error.get("details"),
        ) from None
    except urllib.error.URLError as error:
        raise ApiError(0, "connection_error", "Could not connect to the HiGantic API: %s" % error.reason) from None


def _base_path() -> str:
    config = _configuration()
    return "/v1/agents/%s/excalidraw-pages" % _safe_id(config["agent_id"], "agent ID")


def execute(args: argparse.Namespace) -> Any:
    base = _base_path()
    if args.group == "pages":
        if args.action == "list":
            return _request("GET", base)
        return _request("POST", base, {"label": args.label})

    if args.group == "visibility":
        visibility_path = base + "/" + _safe_id(args.page_id, "page ID") + "/scenes/" + _safe_id(args.scene_id, "scene ID") + "/visibility"
        if args.action == "get":
            return _request("GET", visibility_path)
        if args.visibility == "public" and not args.confirm_public_sharing:
            raise ApiError(0, "confirmation_required", "Publishing requires --confirm-public-sharing.")
        return _request("PUT", visibility_path, {
            "visibility": args.visibility,
            "expectedVersion": args.expected_version,
            "confirmPublicSharing": args.visibility == "public" and args.confirm_public_sharing,
        })

    page_path = base + "/" + _safe_id(args.page_id, "page ID") + "/scenes"
    if args.action == "list":
        return _request("GET", page_path)
    scene_path = page_path + "/" + _safe_id(args.scene_id, "scene ID") if getattr(args, "scene_id", None) else page_path
    if args.action == "get":
        return _request("GET", scene_path)
    if args.action == "create":
        return _request("POST", scene_path, _payload_from_args(args))
    if args.action == "replace":
        payload = _payload_from_args(args)
        payload["expectedVersion"] = args.expected_version
        payload["confirmPublicWrite"] = args.confirm_public_sharing
        return _request("PUT", scene_path, payload)
    if args.action == "delete":
        if not args.confirm_delete:
            raise ApiError(0, "confirmation_required", "Deletion requires --confirm-delete after confirming the exact scene.")
        return _request("DELETE", scene_path, headers={
            "If-Match": str(args.expected_version),
            "X-Confirm-Delete": "true",
        })
    raise ApiError(0, "invalid_command", "Unknown command.")


def _add_scene_source(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--flowchart-file")
    source.add_argument("--scene-file")
    parser.add_argument("--title")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage HiGantic Excalidraw Canvas pages and scenes.")
    groups = parser.add_subparsers(dest="group", required=True)

    pages = groups.add_parser("pages")
    page_actions = pages.add_subparsers(dest="action", required=True)
    page_actions.add_parser("list")
    page_create = page_actions.add_parser("create")
    page_create.add_argument("--label", required=True)

    scenes = groups.add_parser("scenes")
    scene_actions = scenes.add_subparsers(dest="action", required=True)
    scene_list = scene_actions.add_parser("list")
    scene_list.add_argument("--page-id", required=True)
    scene_get = scene_actions.add_parser("get")
    scene_get.add_argument("--page-id", required=True)
    scene_get.add_argument("--scene-id", required=True)
    scene_create = scene_actions.add_parser("create")
    scene_create.add_argument("--page-id", required=True)
    _add_scene_source(scene_create)
    scene_replace = scene_actions.add_parser("replace")
    scene_replace.add_argument("--page-id", required=True)
    scene_replace.add_argument("--scene-id", required=True)
    scene_replace.add_argument("--expected-version", required=True, type=int)
    scene_replace.add_argument("--confirm-public-sharing", action="store_true")
    _add_scene_source(scene_replace)
    scene_delete = scene_actions.add_parser("delete")
    scene_delete.add_argument("--page-id", required=True)
    scene_delete.add_argument("--scene-id", required=True)
    scene_delete.add_argument("--expected-version", required=True, type=int)
    scene_delete.add_argument("--confirm-delete", action="store_true")

    visibility = groups.add_parser("visibility")
    visibility_actions = visibility.add_subparsers(dest="action", required=True)
    visibility_get = visibility_actions.add_parser("get")
    visibility_get.add_argument("--page-id", required=True)
    visibility_get.add_argument("--scene-id", required=True)
    visibility_set = visibility_actions.add_parser("set")
    visibility_set.add_argument("--page-id", required=True)
    visibility_set.add_argument("--scene-id", required=True)
    visibility_set.add_argument("--expected-version", required=True, type=int)
    visibility_set.add_argument("--visibility", required=True, choices=("private", "public"))
    visibility_set.add_argument("--confirm-public-sharing", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = execute(build_parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ApiError as error:
        message = str(error)
        key = _env("HIGANTIC_API_KEY")
        if key:
            message = message.replace(key, "[REDACTED]")
        print("HiGantic Excalidraw error [%s]: %s" % (error.code, message), file=sys.stderr)
        return 3 if error.code == "scene_version_conflict" else 2


if __name__ == "__main__":
    raise SystemExit(main())
