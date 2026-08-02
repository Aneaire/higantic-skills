#!/usr/bin/env python3
"""Dependency-free CLI for HiGantic's direct HTML Artifacts API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from higantic_auth import (  # noqa: E402
    AuthError,
    CLI_VERSION,
    execute_auth,
    redact as redact_auth_secret,
    resolve_credentials,
)
from higantic_diagnostics import run_doctor  # noqa: E402
from higantic_skill_install import (  # noqa: E402
    SKILL_CATALOG,
    SkillInstallError,
    format_install_result,
    install_skills,
    offer_skills_after_login,
)


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SEGMENT_DECODE_ROUNDS = 10
OFFICIAL_API_ORIGIN = "https://agent.higantic.com"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SUPPORTED_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
SENSITIVE_RESPONSE_KEYS = {
    "authorization",
    "apikey",
    "api_key",
    "rawtoken",
    "raw_token",
    "token",
    "tokenhash",
    "token_hash",
}
CAPABILITY_URL_PATTERN = re.compile(r"(?P<prefix>https?://[^\s\"'<>]+/s/)[^\s\"'<>/?#]+")
SHARE_TOKEN_PATTERN = re.compile(r"\bhgs_[A-Za-z0-9_-]{20,}\b")


def redact(value: Any) -> str:
    text = redact_auth_secret(value)
    secret = os.environ.get("HIGANTIC_API_KEY", "").strip()
    if secret:
        text = text.replace(secret, "[REDACTED]")
        encoded_secret = urllib.parse.quote(secret, safe="")
        if encoded_secret != secret:
            text = text.replace(encoded_secret, "[REDACTED]")
    text = CAPABILITY_URL_PATTERN.sub(r"\g<prefix>[REDACTED]", text)
    return SHARE_TOKEN_PATTERN.sub("[REDACTED]", text)


def safe_output(value: Any, allow_capability_url: bool = False) -> Any:
    """Defensively remove credentials and raw share capabilities from API output."""
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "").replace(" ", "")
            if normalized in SENSITIVE_RESPONSE_KEYS:
                safe[key] = "[REDACTED]"
            elif normalized == "capabilityurl" and not allow_capability_url:
                safe[key] = "[REDACTED]"
            else:
                safe[key] = safe_output(item, allow_capability_url=allow_capability_url)
        return safe
    if isinstance(value, list):
        return [safe_output(item, allow_capability_url=allow_capability_url) for item in value]
    if isinstance(value, tuple):
        return [safe_output(item, allow_capability_url=allow_capability_url) for item in value]
    if isinstance(value, str):
        if allow_capability_url:
            return redact_auth_secret(value)
        return redact(value)
    return value


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        safe_code = redact(code)
        safe_message = redact(message)
        super().__init__(safe_message)
        self.status = status
        self.code = safe_code
        self.details = None if details is None else safe_output(details)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ApiError(0, "missing_environment", f"Set {name} in the process environment.")
    return value


def env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def parsed_origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ApiError(0, "invalid_api_base_url", f"Invalid API URL: {error}") from None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ApiError(0, "invalid_api_base_url", "API URLs must use HTTP or HTTPS and include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ApiError(0, "invalid_api_base_url", "API URLs must not include user information.")
    scheme = parsed.scheme.lower()
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def validate_api_base_url(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not contain whitespace or control characters.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ApiError(0, "invalid_api_base_url", f"Invalid HIGANTIC_API_BASE_URL: {error}") from None
    if not parsed.scheme or not parsed.hostname:
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must include a scheme and host.")
    if parsed.username is not None or parsed.password is not None:
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not include user information.")
    if parsed.query or parsed.fragment:
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not include a query or fragment.")
    if "%" in parsed.netloc:
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not percent-encode its host.")

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    path = parsed.path
    decoded_path = path
    for _ in range(10):
        next_path = urllib.parse.unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    else:
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL path is excessively encoded.")
    if "\\" in decoded_path or any(segment in (".", "..") for segment in decoded_path.split("/")):
        raise ApiError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL path must not contain dot traversal.")

    custom_allowed = env_enabled("HIGANTIC_ALLOW_CUSTOM_API_BASE_URL")
    normalized_path = path.rstrip("/")
    is_official = scheme == "https" and host == "agent.higantic.com" and port is None and not normalized_path
    if not is_official:
        if not custom_allowed:
            raise ApiError(
                0,
                "custom_api_base_url_not_allowed",
                f"Only {OFFICIAL_API_ORIGIN} is allowed unless HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1.",
            )
        if scheme == "http":
            if host not in LOOPBACK_HOSTS or not env_enabled("HIGANTIC_ALLOW_INSECURE_LOCALHOST"):
                raise ApiError(
                    0,
                    "insecure_api_base_url_not_allowed",
                    "HTTP is allowed only for loopback hosts with both custom-base and insecure-localhost flags set to 1.",
                )
        elif scheme != "https":
            raise ApiError(0, "invalid_api_base_url", "Custom API base URLs must use HTTPS.")

    display_host = f"[{host}]" if ":" in host else host
    normalized_port = f":{port}" if port is not None else ""
    return f"{scheme}://{display_host}{normalized_port}{normalized_path}"


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        if parsed_origin(request.full_url) != parsed_origin(target):
            raise ApiError(0, "unsafe_redirect", "Refused a cross-origin API redirect to protect the bearer credential.")
        return super().redirect_request(request, file_pointer, code, message, headers, target)


class Client:
    def __init__(self, profile: Optional[str] = None, allow_protected_file: bool = False) -> None:
        credentials = resolve_credentials(profile, allow_protected_file)
        self.base_url = credentials["apiBaseUrl"]
        self.agent_id = credentials["agentId"]
        self._key = credentials["apiKey"]
        self._opener = urllib.request.build_opener(SameOriginRedirectHandler())
        agent = segment(self.agent_id)
        self.agent_root = f"{self.base_url}/v1/agents/{agent}"
        self.root = f"{self.agent_root}/html-pages"

    def _request_url(
        self,
        method: str,
        url: str,
        body: Optional[Dict[str, Any]] = None,
        binary: Optional[bytes] = None,
        content_type: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if body is not None and binary is not None:
            raise ApiError(0, "invalid_arguments", "A request cannot contain both JSON and binary input.")
        encoded = binary if binary is not None else (None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8"))
        request_headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            **({"Content-Type": content_type} if binary is not None and content_type else {}),
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        }
        request = urllib.request.Request(url, data=encoded, method=method, headers=request_headers)
        try:
            with self._opener.open(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ApiError(error.code, "http_error", f"HTTP {error.code}") from None
            api_error = payload.get("error", {})
            raise ApiError(
                error.code,
                api_error.get("code", "http_error"),
                api_error.get("message", f"HTTP {error.code}"),
                api_error.get("details"),
            ) from None
        except urllib.error.URLError as error:
            raise ApiError(0, "connection_error", f"Could not reach HiGantic: {error.reason}") from None
        if "error" in payload:
            item = payload["error"]
            raise ApiError(0, item.get("code", "api_error"), item.get("message", "API request failed"), item.get("details"))
        return payload.get("data", payload)

    def request(
        self,
        method: str,
        path: str = "",
        body: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
        return self._request_url(method, self.root + path, body=body, headers=headers)

    def assets_request(
        self,
        method: str,
        asset_id: Optional[str] = None,
        binary: Optional[bytes] = None,
        content_type: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        suffix = f"/{segment(asset_id)}" if asset_id is not None else ""
        return self._request_url(
            method,
            f"{self.agent_root}/html-assets{suffix}",
            binary=binary,
            content_type=content_type,
            headers={"X-Asset-Name": name} if name is not None else None,
        )


def segment(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ApiError(0, "invalid_path_segment", "Resource identifiers must be non-empty path segments.")
    decoded = value
    for _ in range(MAX_SEGMENT_DECODE_ROUNDS + 1):
        if any(unicodedata.category(character) == "Cc" for character in decoded):
            raise ApiError(0, "invalid_path_segment", "Resource identifiers must not contain control characters.")
        if decoded in (".", "..") or "/" in decoded or "\\" in decoded:
            raise ApiError(0, "invalid_path_segment", "Resource identifiers must not contain dot segments or path separators.")
        next_value = urllib.parse.unquote(decoded)
        if next_value == decoded:
            return urllib.parse.quote(value, safe="")
        decoded = next_value
    raise ApiError(0, "invalid_path_segment", "Resource identifier encoding exceeds the safe decoding limit.")


def read_html(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as source:
        return source.read()


def read_image(path: str) -> tuple[bytes, str, str]:
    source = Path(path)
    mime_type = SUPPORTED_IMAGE_MIME_TYPES.get(source.suffix.lower())
    if not mime_type:
        guessed, _ = mimetypes.guess_type(source.name)
        raise ApiError(0, "unsupported_media_type", f"Unsupported image type: {guessed or source.suffix or 'unknown'}. Use PNG, JPEG, WebP, or GIF.")
    data = source.read_bytes()
    if not data:
        raise ApiError(0, "invalid_arguments", "The image file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(0, "payload_too_large", "The image exceeds the 10 MiB limit.")
    return data, mime_type, source.name


def artifact_path(args: argparse.Namespace) -> str:
    return f"/{segment(args.page_id)}/artifacts/{segment(args.artifact_id)}"


def current_revision(client: Client, args: argparse.Namespace) -> int:
    result = client.request("GET", artifact_path(args))
    return int(result["artifact"].get("currentRevision", 0))


def share_path(args: argparse.Namespace) -> str:
    root = artifact_path(args) + "/shares"
    if getattr(args, "share_id", None) is not None:
        root += f"/{segment(args.share_id)}"
    return root


def share_unavailable(error: ApiError) -> ApiError:
    if error.code != "not_found":
        return error
    return ApiError(
        error.status,
        "share_management_unavailable",
        "Public sharing is unavailable or the requested artifact/share was not found. Confirm sharing is enabled for the server and that the IDs are correct.",
    )


def require_confirmation(args: argparse.Namespace, attribute: str, message: str) -> None:
    if not getattr(args, attribute, False):
        raise ApiError(0, "confirmation_required", message)


def build_share_expiration(args: argparse.Namespace) -> Optional[int]:
    if args.expires_at_ms is not None:
        if args.expires_at_ms <= int(time.time() * 1000):
            raise ApiError(0, "invalid_arguments", "--expires-at-ms must be a future Unix timestamp in milliseconds.")
        return args.expires_at_ms
    if args.expires_in_hours is not None:
        if args.expires_in_hours <= 0:
            raise ApiError(0, "invalid_arguments", "--expires-in-hours must be greater than zero.")
        return int(time.time() * 1000 + args.expires_in_hours * 60 * 60 * 1000)
    return None


def add_artifact_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--artifact-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authenticate with HiGantic, install optional public skills, and manage private-by-default HTML artifacts without invoking an LLM.")
    parser.add_argument("--version", action="version", version=f"HiGantic CLI {CLI_VERSION}")
    parser.add_argument("--profile", help="Use a named HiGantic profile when no complete environment override is set.")
    parser.add_argument("--allow-protected-file", action="store_true", help="Allow an explicitly configured protected-file credential store.")
    groups = parser.add_subparsers(dest="group", required=True)

    auth = groups.add_parser("auth", description="Manage secure HiGantic CLI profiles.")
    auth_commands = auth.add_subparsers(dest="command", required=True)
    login = auth_commands.add_parser("login")
    login.add_argument("--profile", default=argparse.SUPPRESS)
    login.add_argument("--api-base-url", help="Trusted HiGantic API origin; defaults to the official service.")
    login.add_argument("--scope", action="append", help="Request one explicit scope; repeat for multiple scopes.")
    login.add_argument("--no-browser", action="store_true")
    login.add_argument("--storage", choices=("native", "file"))
    login.add_argument("--no-skill-offer", action="store_true", help="Do not offer optional HiGantic skills after successful interactive login.")
    login.add_argument("--json", action="store_true", help="Print the authentication result as JSON and suppress optional skill prompts.")
    login.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)
    status = auth_commands.add_parser("status")
    status.add_argument("--profile", default=argparse.SUPPRESS)
    status.add_argument("--offline", action="store_true")
    status.add_argument("--json", action="store_true")
    status.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)
    use = auth_commands.add_parser("use")
    use.add_argument("name")
    use.add_argument("--json", action="store_true")
    use.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)
    logout = auth_commands.add_parser("logout")
    logout.add_argument("--profile", default=argparse.SUPPRESS)
    logout.add_argument("--yes", action="store_true")
    logout.add_argument("--local-only", action="store_true")
    logout.add_argument("--json", action="store_true")
    logout.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)
    imported = auth_commands.add_parser("import")
    imported.add_argument("--profile", default=argparse.SUPPRESS)
    imported.add_argument("--stdin", action="store_true", required=True)
    imported.add_argument("--api-base-url", help="Trusted HiGantic API origin; defaults to the official service.")
    imported.add_argument("--storage", choices=("native", "file"))
    imported.add_argument("--json", action="store_true")
    imported.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)
    profiles = auth_commands.add_parser("profiles", description="List configured profile metadata without reading or printing API keys.")
    profiles.add_argument("--json", action="store_true")

    doctor = groups.add_parser("doctor", description="Run read-only CLI, credential, dependency, and API diagnostics.")
    doctor.add_argument("--profile", default=argparse.SUPPRESS)
    doctor.add_argument("--offline", action="store_true", help="Skip the authenticated API connectivity check.")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--allow-protected-file", action="store_true", default=argparse.SUPPRESS)

    skills = groups.add_parser("skills", description="Review and install optional public HiGantic skills.")
    skill_commands = skills.add_subparsers(dest="command", required=True)
    install_skills_command = skill_commands.add_parser("install")
    install_skills_command.add_argument(
        "--skill",
        action="append",
        choices=tuple(entry["slug"] for entry in SKILL_CATALOG),
        help="Review or install only this offered skill; repeat for more than one.",
    )
    install_skills_command.add_argument("--yes", action="store_true", help="Install every selected missing skill without prompting.")
    install_skills_command.add_argument("--json", action="store_true", help="Print the installation result as JSON for scripts.")

    pages = groups.add_parser("pages")
    pages_commands = pages.add_subparsers(dest="command", required=True)
    pages_commands.add_parser("list")
    create_page = pages_commands.add_parser("create")
    create_page.add_argument("--label", required=True)
    create_page.add_argument("--idempotency-key")

    artifacts = groups.add_parser("artifacts")
    artifact_commands = artifacts.add_subparsers(dest="command", required=True)
    list_artifacts = artifact_commands.add_parser("list")
    list_artifacts.add_argument("--page-id", required=True)
    create_artifact = artifact_commands.add_parser("create")
    create_artifact.add_argument("--page-id", required=True)
    create_artifact.add_argument("--title", required=True)
    create_artifact.add_argument("--summary")
    create_artifact.add_argument("--external-id")
    create_artifact.add_argument("--html-file")
    create_artifact.add_argument("--idempotency-key")
    lookup_artifact = artifact_commands.add_parser("lookup")
    lookup_artifact.add_argument("--page-id", required=True)
    lookup_artifact.add_argument("--external-id", required=True)
    upsert_artifact = artifact_commands.add_parser("upsert")
    upsert_artifact.add_argument("--page-id", required=True)
    upsert_artifact.add_argument("--external-id", required=True)
    upsert_artifact.add_argument("--title", required=True)
    upsert_artifact.add_argument("--summary")
    upsert_artifact.add_argument("--html-file")
    upsert_artifact.add_argument("--confirm-public-sharing", action="store_true", help="Confirm replacing the live content of an already-public artifact.")
    for command in ("get", "update", "delete"):
        item = artifact_commands.add_parser(command)
        add_artifact_identity_arguments(item)
        if command == "update":
            item.add_argument("--title")
            item.add_argument("--summary")
        if command == "delete":
            item.add_argument("--confirm-delete", action="store_true", help="Confirm deletion of the artifact and all revisions/shares.")

    revisions = groups.add_parser("revisions")
    revision_commands = revisions.add_subparsers(dest="command", required=True)
    for command in ("list", "get", "append", "restore"):
        item = revision_commands.add_parser(command)
        add_artifact_identity_arguments(item)
        if command in ("get", "restore"):
            item.add_argument("--revision", required=True, type=int)
        if command == "append":
            item.add_argument("--html-file", required=True)
        if command in ("append", "restore"):
            item.add_argument("--confirm-public-sharing", action="store_true", help="Confirm replacing the live content of an already-public artifact.")

    assets = groups.add_parser("assets")
    asset_commands = assets.add_subparsers(dest="command", required=True)
    asset_commands.add_parser("list")
    upload_asset = asset_commands.add_parser("upload")
    upload_asset.add_argument("--file", required=True)
    delete_asset = asset_commands.add_parser("delete")
    delete_asset.add_argument("--asset-id", required=True)
    delete_asset.add_argument("--confirm-delete", action="store_true", help="Confirm removal of the managed asset record.")

    visibility = groups.add_parser("visibility", description="Read or explicitly change stable artifact visibility.")
    visibility_commands = visibility.add_subparsers(dest="command", required=True)
    get_visibility = visibility_commands.add_parser("get")
    add_artifact_identity_arguments(get_visibility)
    set_visibility = visibility_commands.add_parser("set")
    add_artifact_identity_arguments(set_visibility)
    set_visibility.add_argument("--visibility", required=True, choices=("private", "public"))
    set_visibility.add_argument("--confirm-public-sharing", action="store_true", help="Acknowledge that anyone can access the stable current-revision URL while public.")

    shares = groups.add_parser("shares", description="Explicitly manage opt-in unlisted capability links.")
    share_commands = shares.add_subparsers(dest="command", required=True)
    list_shares = share_commands.add_parser("list")
    add_artifact_identity_arguments(list_shares)
    create_share = share_commands.add_parser("create")
    add_artifact_identity_arguments(create_share)
    create_share.add_argument("--revision", type=int, help="Pin a specific immutable revision; omit to pin the current revision.")
    expiration = create_share.add_mutually_exclusive_group()
    expiration.add_argument("--expires-at-ms", type=int, help="Future Unix timestamp in milliseconds; omit for no expiration.")
    expiration.add_argument("--expires-in-hours", type=float, help="Expire this many hours from now; omit for no expiration.")
    create_share.add_argument("--confirm-public-sharing", action="store_true", help="Acknowledge that anyone with the unlisted link can access it.")
    revoke_share = share_commands.add_parser("revoke")
    add_artifact_identity_arguments(revoke_share)
    revoke_share.add_argument("--share-id", required=True)
    revoke_share.add_argument("--confirm-revoke", action="store_true")
    rotate_share = share_commands.add_parser("rotate")
    add_artifact_identity_arguments(rotate_share)
    rotate_share.add_argument("--share-id", required=True)
    rotate_share.add_argument("--confirm-public-sharing", action="store_true", help="Acknowledge that the replacement link grants access to anyone who has it.")

    url = groups.add_parser("url")
    url.add_argument("--page-id", required=True)
    url.add_argument("--artifact-id")
    url.add_argument("--revision", type=int)
    return parser


def execute(client: Client, args: argparse.Namespace) -> Any:
    if args.group == "assets":
        if args.command == "list":
            return client.assets_request("GET")
        if args.command == "delete":
            require_confirmation(args, "confirm_delete", "Asset deletion requires --confirm-delete.")
            return client.assets_request("DELETE", asset_id=args.asset_id)
        data, mime_type, name = read_image(args.file)
        return client.assets_request("POST", binary=data, content_type=mime_type, name=name)
    if args.group == "pages":
        return client.request("GET") if args.command == "list" else client.request(
            "POST",
            body={"label": args.label},
            idempotency_key=args.idempotency_key,
        )
    if args.group == "artifacts":
        collection = f"/{segment(args.page_id)}/artifacts"
        if args.command == "list":
            return client.request("GET", collection)
        if args.command == "create":
            body: Dict[str, Any] = {"title": args.title}
            if args.summary is not None:
                body["summary"] = args.summary
            if args.external_id is not None:
                body["externalId"] = args.external_id
            if args.html_file is not None:
                body["html"] = read_html(args.html_file)
            return client.request("POST", collection, body, idempotency_key=args.idempotency_key)
        if args.command in ("lookup", "upsert"):
            external_path = f"{collection}/by-external-id/{segment(args.external_id)}"
            if args.command == "lookup":
                return client.request("GET", external_path)
            current_artifact: Dict[str, Any] = {}
            try:
                current_artifact = client.request("GET", external_path)["artifact"]
                current_revision_number = int(current_artifact.get("currentRevision", 0))
                current_version = int(current_artifact.get("version", 0))
            except ApiError as error:
                if error.code != "not_found":
                    raise
                current_revision_number = 0
                current_version = 0
            confirmed_public_write = args.html_file is not None and current_artifact.get("visibility") == "public"
            if confirmed_public_write:
                require_confirmation(
                    args,
                    "confirm_public_sharing",
                    "Updating a public artifact requires --confirm-public-sharing because the new revision becomes visible immediately.",
                )
            body = {
                "title": args.title,
                "expectedCurrentRevision": current_revision_number,
                "expectedArtifactVersion": current_version,
            }
            if confirmed_public_write:
                body["confirmPublicWrite"] = True
            if args.summary is not None:
                body["summary"] = args.summary
            if args.html_file is not None:
                body["html"] = read_html(args.html_file)
            return client.request("PUT", external_path, body)
        path = artifact_path(args)
        if args.command == "get":
            return client.request("GET", path)
        if args.command == "delete":
            require_confirmation(args, "confirm_delete", "Artifact deletion requires --confirm-delete because it removes all revisions and shares.")
            return client.request("DELETE", path)
        body = {key: value for key, value in {"title": args.title, "summary": args.summary}.items() if value is not None}
        if not body:
            raise ApiError(0, "invalid_arguments", "Pass --title or --summary.")
        current = client.request("GET", path)["artifact"]
        body["expectedArtifactVersion"] = int(current.get("version", 0))
        return client.request("PATCH", path, body)
    if args.group == "revisions":
        root = artifact_path(args) + "/revisions"
        if args.command == "list":
            return client.request("GET", root)
        if args.command == "get":
            return client.request("GET", f"{root}/{args.revision}")
        current_artifact = client.request("GET", artifact_path(args))["artifact"]
        expected = int(current_artifact.get("currentRevision", 0))
        expected_version = int(current_artifact.get("version", 0))
        confirmed_public_write = current_artifact.get("visibility") == "public"
        if confirmed_public_write:
            require_confirmation(
                args,
                "confirm_public_sharing",
                "Updating a public artifact requires --confirm-public-sharing because the new current revision becomes visible immediately.",
            )
        write_body: Dict[str, Any] = {
            "expectedCurrentRevision": expected,
            "expectedArtifactVersion": expected_version,
        }
        if confirmed_public_write:
            write_body["confirmPublicWrite"] = True
        if args.command == "append":
            write_body["html"] = read_html(args.html_file)
            return client.request("POST", root, write_body)
        return client.request("POST", f"{root}/{args.revision}/restore", write_body)
    if args.group == "visibility":
        path = artifact_path(args) + "/visibility"
        try:
            if args.command == "set" and args.visibility == "public":
                require_confirmation(
                    args,
                    "confirm_public_sharing",
                    "Publishing requires --confirm-public-sharing. Anyone can access the stable URL while the artifact is public, and it follows the current revision.",
                )
            current = client.request("GET", path)
            if args.command == "get":
                return current
            return client.request("PUT", path, {
                "visibility": args.visibility,
                "expectedArtifactVersion": int(current.get("version", 0)),
            })
        except ApiError as error:
            raise share_unavailable(error) from None
    if args.group == "shares":
        try:
            if args.command == "list":
                return client.request("GET", share_path(args))
            if args.command == "create":
                require_confirmation(
                    args,
                    "confirm_public_sharing",
                    "Share creation requires --confirm-public-sharing. Capability links are unlisted but accessible to anyone with the link.",
                )
                body: Dict[str, Any] = {}
                if args.revision is not None:
                    if args.revision < 1:
                        raise ApiError(0, "invalid_arguments", "--revision must be at least 1.")
                    body["revision"] = args.revision
                expires_at = build_share_expiration(args)
                if expires_at is not None:
                    body["expiresAt"] = expires_at
                return client.request("POST", share_path(args), body)
            if args.command == "revoke":
                require_confirmation(args, "confirm_revoke", "Share revocation requires --confirm-revoke.")
                return client.request("DELETE", share_path(args))
            require_confirmation(
                args,
                "confirm_public_sharing",
                "Share rotation requires --confirm-public-sharing. The replacement link is accessible to anyone who receives it.",
            )
            return client.request("POST", share_path(args) + "/rotate")
        except ApiError as error:
            raise share_unavailable(error) from None
    if args.artifact_id:
        path = f"/{segment(args.page_id)}/artifacts/{segment(args.artifact_id)}"
        if args.revision is not None:
            result = client.request("GET", f"{path}/revisions/{args.revision}")
            url = result.get("url")
        else:
            result = client.request("GET", path)
            url = result.get("artifact", {}).get("url")
        if not url:
            raise ApiError(0, "not_found", "HTML artifact URL was not found.")
        return str(url)
    if args.revision is not None:
        raise ApiError(0, "invalid_arguments", "--revision requires --artifact-id.")
    pages = client.request("GET").get("pages", [])
    page = next((item for item in pages if item.get("id") == args.page_id), None)
    if not page or not page.get("url"):
        raise ApiError(0, "not_found", "HTML page was not found.")
    return str(page["url"])


def terminal_line(value: Any) -> str:
    cleaned = "".join(character if not unicodedata.category(character).startswith("C") else " " for character in redact(value))
    return " ".join(cleaned.split())


def _agent_label(result: Dict[str, Any]) -> str:
    name = terminal_line(result.get("agentName") or "")
    agent_id = terminal_line(result.get("agentId") or "")
    if name and agent_id and name != agent_id:
        return f"{name} ({agent_id})"
    return name or agent_id or "Unknown agent"


def format_auth_result(command: str, result: Dict[str, Any]) -> str:
    if command in {"login", "import"}:
        profile = terminal_line(result.get("profile") or "default")
        action = "Signed in to" if command == "login" else "Imported credentials for"
        lines = [f"{action} {_agent_label(result)} using profile {profile!r}."]
        if result.get("apiBaseUrl"):
            lines.append(f"API: {terminal_line(result['apiBaseUrl'])}")
        if result.get("storage"):
            lines.append(f"Credential storage: {terminal_line(result['storage'])}")
        scopes = result.get("scopes") or []
        if scopes:
            lines.append(f"Scopes: {', '.join(terminal_line(scope) for scope in scopes)}")
        return "\n".join(lines)
    if command == "status":
        source = result.get("profile") or result.get("source") or "unknown"
        mode = "offline" if result.get("offline") else "remote"
        lines = [
            f"Authenticated ({mode}) using {terminal_line(source)}.",
            f"Agent: {_agent_label(result)}",
            f"API: {terminal_line(result.get('apiBaseUrl') or '')}",
        ]
        scopes = result.get("scopes") or []
        if scopes:
            lines.append(f"Scopes: {', '.join(terminal_line(scope) for scope in scopes)}")
        return "\n".join(lines)
    if command == "use":
        return f"Profile {terminal_line(result.get('currentProfile') or '')!r} is now active."
    if command == "logout":
        profile = terminal_line(result.get("profile") or "")
        if result.get("revoked"):
            return f"Revoked the API key and removed profile {profile!r} from this device."
        return f"Removed profile {profile!r} from this device without revoking its API key."
    if command == "profiles":
        profiles = result.get("profiles") or []
        lines = []
        if result.get("environmentOverrideActive"):
            lines.append("Environment credentials are active and currently override named profiles.")
        if not profiles:
            lines.extend(["No HiGantic profiles are configured.", "Run: higantic auth login"])
            return "\n".join(lines)
        lines.append("Configured HiGantic profiles:")
        for profile in profiles:
            marker = "*" if profile.get("current") else "-"
            name = terminal_line(profile.get("name") or "")
            agent = _agent_label(profile)
            current = " (active)" if profile.get("current") else ""
            lines.append(f"  {marker} {name}: {agent}{current}")
        return "\n".join(lines)
    return json.dumps(result, indent=2, sort_keys=True)


def format_doctor_result(result: Dict[str, Any]) -> str:
    labels = {"ok": "OK", "warning": "WARN", "error": "ERROR", "skipped": "SKIP"}
    lines = [f"HiGantic CLI {terminal_line(result.get('version') or '')} diagnostics"]
    for check in result.get("checks", []):
        status = labels.get(str(check.get("status")), "INFO")
        name = terminal_line(check.get("name") or "Check")
        message = terminal_line(check.get("message") or "")
        lines.append(f"[{status}] {name}: {message}")
    outcome = {"ok": "Ready", "warning": "Ready with warnings", "error": "Problems found"}.get(result.get("status"), "Complete")
    lines.append(f"Result: {outcome}.")
    return "\n".join(lines)


def error_hint(code: str) -> Optional[str]:
    hints = {
        "profile_not_selected": "Run `higantic auth profiles`, then select one with `higantic auth use PROFILE` or sign in with `higantic auth login`.",
        "profile_not_found": "Run `higantic auth profiles` to see configured profiles, or create one with `higantic auth login --profile NAME`.",
        "credential_not_found": "Run `higantic doctor` to check secure storage. If the profile is broken, remove that exact profile with `higantic auth logout --profile PROFILE --local-only` and sign in again.",
        "invalid_api_key": "Run `higantic doctor`. Sign in again if the stored or environment API key is no longer valid.",
        "incomplete_environment": "Set all three HIGANTIC_API_BASE_URL, HIGANTIC_AGENT_ID, and HIGANTIC_API_KEY variables, or unset all three.",
        "environment_override_active": "Unset HIGANTIC_API_BASE_URL, HIGANTIC_AGENT_ID, and HIGANTIC_API_KEY before managing named profiles.",
        "secure_storage_unavailable": "Run `higantic doctor` for the failing credential-store dependency and suggested setup.",
        "connection_error": "Check the network connection and run `higantic doctor` to test the configured API.",
        "expired_token": "Run `higantic auth login` again to start a new ten-minute approval session.",
        "authorization_denied": "Review the selected agent and permissions in the browser, then run `higantic auth login` again.",
        "access_denied": "Review the selected agent and permissions in the browser, then run `higantic auth login` again.",
        "interactive_required": "Run the command in a terminal, or pass `--yes` only when installing every selected missing skill is intentional.",
        "skills_installer_unavailable": "Install Node.js with npx, then run `higantic doctor` to verify it.",
    }
    return hints.get(code)


def main() -> int:
    try:
        args = build_parser().parse_args()
        if args.group == "doctor":
            result = run_doctor(args.profile, args.allow_protected_file, args.offline)
            printable = safe_output(result)
            print(json.dumps(printable, indent=2, sort_keys=True) if args.json else format_doctor_result(printable))
            return 2 if result["status"] == "error" else 0
        if args.group == "skills":
            result = install_skills(args.skill, args.yes)
            printable = safe_output(result)
            print(json.dumps(printable, indent=2, sort_keys=True) if args.json else format_install_result(printable))
            return 2 if result["failed"] else 0
        if args.group == "auth":
            result = execute_auth(args)
            printable = safe_output(result)
            print(json.dumps(printable, indent=2, sort_keys=True) if args.json else format_auth_result(args.command, printable))
            if args.command == "login":
                try:
                    optional_install = offer_skills_after_login(getattr(args, "no_skill_offer", False) or args.json)
                    if optional_install and optional_install.get("failed"):
                        print("Authentication succeeded, but one or more optional skills could not be installed.", file=sys.stderr)
                except SkillInstallError as error:
                    print(f"Authentication succeeded, but the optional skill catalog could not be opened: {error}", file=sys.stderr)
            return 0
        result = execute(Client(args.profile, args.allow_protected_file), args)
        allow_capability_url = args.group == "shares" and args.command in ("create", "rotate")
        printable = safe_output(result, allow_capability_url=allow_capability_url)
        print(printable if args.group == "url" else json.dumps(printable, indent=2, sort_keys=True))
        if allow_capability_url:
            print("Warning: this capability link is unlisted but accessible to anyone with the link. It is shown only once; store it securely.", file=sys.stderr)
        if args.group == "visibility" and args.command == "set" and args.visibility == "public":
            print("Warning: the stable public URL is accessible to anyone and follows the artifact's current revision until visibility is set to private.", file=sys.stderr)
        return 0
    except (ApiError, AuthError, SkillInstallError) as error:
        if isinstance(error, AuthError) and error.code == "profile_exists" and isinstance(error.details, dict):
            profile = str(error.details.get("profile", ""))
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", profile):
                print(
                    f"HiGantic profile {profile!r} is already configured.\n\n"
                    "Check the current sign-in:\n"
                    f"  higantic auth status --profile {profile}\n\n"
                    "To sign in again, revoke the old API key first:\n"
                    f"  higantic auth logout --profile {profile}\n"
                    f"  higantic auth login --profile {profile}\n\n"
                    "Or keep this profile and create another one:\n"
                    "  higantic auth login --profile another-name",
                    file=sys.stderr,
                )
                return 2
        conflict_codes = {"revision_conflict", "artifact_version_conflict"}
        suffix = " Refresh the artifact and reconcile before retrying." if error.code in conflict_codes else ""
        details = f" Details: {json.dumps(safe_output(error.details), sort_keys=True)}" if error.details is not None else ""
        print(f"HiGantic error [{terminal_line(error.code)}]: {terminal_line(error)}{details}{suffix}", file=sys.stderr)
        hint = error_hint(error.code)
        if hint:
            print(f"Hint: {hint}", file=sys.stderr)
        return 3 if error.code in conflict_codes else 2
    except (OSError, ValueError) as error:
        print(f"HiGantic CLI error: {terminal_line(error)}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"HiGantic CLI error: {terminal_line(error)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
