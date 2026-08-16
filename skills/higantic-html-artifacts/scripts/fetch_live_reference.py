#!/usr/bin/env python3
"""Fetch constrained product-state JSON and render it with trusted local text."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


PUBLIC_ORIGIN = "https://skills.higantic.com"
EXACT_MANIFEST_URL = f"{PUBLIC_ORIGIN}/v1/manifest.json"
REFERENCE_PATH_PREFIX = "/v1/references/"
REQUEST_TIMEOUT_SECONDS = 5
MAX_MANIFEST_BYTES = 64 * 1024
MAX_REFERENCE_BYTES = 64 * 1024
MAX_CONFIG_BYTES = 4 * 1024
UPDATE_REQUIRED_EXIT = 3
CONFIG_ERROR_EXIT = 2
SKILL_DIR = Path(__file__).resolve().parents[1]
EXPECTED_SLUG = SKILL_DIR.name
CONFIG_PATH = SKILL_DIR / "references" / "live-reference.json"
FALLBACK_PATH = SKILL_DIR / "references" / "live-reference-fallback.json"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ASCII_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_.:-]+$")

CAPABILITY_TEXT = {
    "html-pages": "List existing HTML Artifact pages and create a page when required.",
    "html-artifacts": "List, create, look up, upsert, read, update, and deliberately delete artifacts.",
    "html-revisions": "List, read, append, and restore immutable artifact revisions.",
    "private-artifact-urls": "Produce private workspace URLs for artifacts and revisions.",
    "stable-public-visibility": "Read and explicitly change stable public visibility for current-revision artifact URLs.",
    "capability-shares": "List, create, revoke, and rotate explicit pinned capability shares when server support is enabled.",
}
COMMAND_TEXT = {
    "pages.list": "pages list",
    "pages.create": "pages create",
    "artifacts.list": "artifacts list",
    "artifacts.create": "artifacts create",
    "artifacts.lookup": "artifacts lookup",
    "artifacts.upsert": "artifacts upsert",
    "artifacts.get": "artifacts get",
    "artifacts.update": "artifacts update",
    "artifacts.delete": "artifacts delete",
    "revisions.list": "revisions list",
    "revisions.get": "revisions get",
    "revisions.append": "revisions append",
    "revisions.restore": "revisions restore",
    "visibility.get": "visibility get",
    "visibility.set": "visibility set",
    "shares.list": "shares list",
    "shares.create": "shares create",
    "shares.revoke": "shares revoke",
    "shares.rotate": "shares rotate",
    "url.get": "url",
}
SCOPE_TEXT = {
    "html_artifacts:read": "read artifacts and revisions",
    "html_artifacts:write": "create and modify artifacts and revisions",
    "html_artifacts:share": "publish stable URLs and manage pinned capability links",
    "html_pages:create": "create HTML Artifact pages",
}
FEATURE_TEXT = {
    "staticHtmlOnly": "Artifact content is static HTML only",
    "optimisticConcurrencyRequired": "Writes require optimistic concurrency checks",
    "managedAssetReferencesRequired": "Images use managed asset references rather than remote imports",
    "stablePublicVisibilitySupported": "Stable current-revision public visibility is supported when sharing is enabled",
    "capabilitySharingSupported": "Pinned capability-sharing commands are supported when sharing is enabled",
    "capabilityUrlRecoverable": "A capability URL can be recovered after its create or rotate response",
    "htmlPageDeletionSupported": "Direct HTML page deletion is supported",
    "remoteAssetImportSupported": "Remote image import is supported",
}
LIMIT_TEXT = {
    "artifactSourceBytes": "Maximum artifact source bytes",
    "revisionsPerArtifact": "Maximum revisions per artifact",
    "requestsPerMinutePerKey": "Maximum requests per minute per key",
    "writesPerMinutePerKey": "Maximum writes per minute per key",
}
REFERENCE_FIELDS = {
    "schemaVersion",
    "slug",
    "updatedAt",
    "supportedCapabilities",
    "supportedCommands",
    "scopes",
    "features",
    "limits",
}
CONFIG_FIELDS = {"schemaVersion", "slug", "installedVersion", "manifestUrl", "referenceUrl"}
MANIFEST_FIELDS = {"schemaVersion", "updatedAt", "references"}
MANIFEST_ENTRY_FIELDS = {"slug", "referenceUrl", "sha256", "minimumInstalledVersion"}


class LiveReferenceError(RuntimeError):
    """Untrusted or malformed live-reference data failed validation."""


class UpdateRequiredError(LiveReferenceError):
    """The installed executable skill is older than the manifest minimum."""


def ensure_ascii(value: Any, label: str, pattern: Optional[re.Pattern] = None) -> str:
    if not isinstance(value, str) or not value or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise LiveReferenceError(f"{label} must be a constrained ASCII string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise LiveReferenceError(f"{label} has an invalid value")
    return value


def unique_object(pairs):
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LiveReferenceError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def parse_json_bytes(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LiveReferenceError(f"{label} is not UTF-8") from error
    if any(ord(character) > 0x7F for character in text):
        raise LiveReferenceError(f"{label} must contain ASCII JSON only")
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, LiveReferenceError) as error:
        raise LiveReferenceError(f"{label} is malformed") from error


def exact_object(value: Any, fields, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise LiveReferenceError(f"{label} has unexpected or missing fields")
    return value


def parse_timestamp(value: Any, label: str) -> str:
    text = ensure_ascii(value, label, TIMESTAMP_PATTERN)
    try:
        datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise LiveReferenceError(f"{label} is not a real UTC timestamp") from error
    return text


def parse_semver(value: Any, label: str) -> Tuple[int, int, int]:
    text = ensure_ascii(value, label, SEMVER_PATTERN)
    return tuple(int(part) for part in text.split("."))  # type: ignore[return-value]


def parsed_origin(url: str) -> Tuple[str, str, int]:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise LiveReferenceError("invalid URL") from error
    if parsed.scheme != "https" or parsed.hostname is None:
        raise LiveReferenceError("URL must use HTTPS with a host")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise LiveReferenceError("URL must not contain user information, query, or fragment")
    if parsed.netloc != "skills.higantic.com" or parsed.hostname.lower() != "skills.higantic.com" or port is not None:
        raise LiveReferenceError("URL must use the exact branded origin")
    return parsed.scheme, parsed.hostname.lower(), 443


def expected_reference_url(slug: str) -> str:
    return f"{PUBLIC_ORIGIN}{REFERENCE_PATH_PREFIX}{slug}.json"


def validate_reference_url(url: Any, slug: str) -> str:
    text = ensure_ascii(url, "referenceUrl")
    parsed_origin(text)
    parsed = urllib.parse.urlsplit(text)
    if not parsed.path.startswith(REFERENCE_PATH_PREFIX):
        raise LiveReferenceError("referenceUrl has an invalid path prefix")
    decoded_path = parsed.path
    for _ in range(10):
        next_path = urllib.parse.unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    else:
        raise LiveReferenceError("referenceUrl path is excessively encoded")
    if "\\" in decoded_path or any(segment in (".", "..") for segment in decoded_path.split("/")):
        raise LiveReferenceError("referenceUrl path contains traversal")
    expected = expected_reference_url(slug)
    if text != expected:
        raise LiveReferenceError("referenceUrl does not match its slug")
    return text


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        if parsed_origin(request.full_url) != parsed_origin(target):
            raise LiveReferenceError("cross-origin redirect refused")
        return super().redirect_request(request, file_pointer, code, message, headers, target)


def build_opener():
    # Ignore environment proxies and attach no credentials, cookies, or custom headers.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), SameOriginRedirectHandler())


def fetch_bytes(opener, url: str, maximum: int) -> bytes:
    parsed_origin(url)
    request = urllib.request.Request(url, method="GET")
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status != 200:
            raise LiveReferenceError(f"unexpected HTTP status {status}")
        final_url = response.geturl() if hasattr(response, "geturl") else url
        parsed_origin(final_url)
        if final_url != url:
            raise LiveReferenceError("redirect did not finish at the configured exact path")
        content_length = response.headers.get("Content-Length") if response.headers is not None else None
        declared_length = None
        if content_length is not None:
            if re.fullmatch(r"0|[1-9]\d*", content_length.strip()) is None:
                raise LiveReferenceError("invalid Content-Length")
            declared_length = int(content_length)
            if declared_length > maximum:
                raise LiveReferenceError("response exceeds size limit")
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise LiveReferenceError("response exceeds size limit")
        if declared_length is not None and declared_length != len(body):
            raise LiveReferenceError("Content-Length does not match response size")
        return body


def load_installed_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise LiveReferenceError("installed live-reference config exceeds size limit")
    config = exact_object(parse_json_bytes(raw, "installed live-reference config"), CONFIG_FIELDS, "installed live-reference config")
    if config["schemaVersion"] != 1 or isinstance(config["schemaVersion"], bool):
        raise LiveReferenceError("installed live-reference config schemaVersion must be 1")
    slug = ensure_ascii(config["slug"], "installed live-reference config slug", SLUG_PATTERN)
    if slug != EXPECTED_SLUG:
        raise LiveReferenceError("installed live-reference config slug does not match the skill directory")
    parse_semver(config["installedVersion"], "installedVersion")
    manifest_url = ensure_ascii(config["manifestUrl"], "manifestUrl")
    if manifest_url != EXACT_MANIFEST_URL:
        raise LiveReferenceError("manifestUrl must use the exact branded manifest path")
    parsed_origin(manifest_url)
    reference_url = validate_reference_url(config["referenceUrl"], slug)
    if reference_url != expected_reference_url(slug):
        raise LiveReferenceError("referenceUrl does not match installed slug")
    return config


def validate_identifier_array(value: Any, allowlist: Dict[str, str], label: str) -> list:
    if not isinstance(value, list):
        raise LiveReferenceError(f"{label} must be an array")
    seen = set()
    for identifier in value:
        text = ensure_ascii(identifier, label, ASCII_IDENTIFIER_PATTERN)
        if text not in allowlist:
            raise LiveReferenceError(f"{label} contains an unknown identifier")
        if text in seen:
            raise LiveReferenceError(f"{label} contains a duplicate identifier")
        seen.add(text)
    return value


def validate_reference_data(raw: bytes, expected_slug: str) -> Dict[str, Any]:
    reference = exact_object(parse_json_bytes(raw, "live reference"), REFERENCE_FIELDS, "live reference")
    if reference["schemaVersion"] != 1 or isinstance(reference["schemaVersion"], bool):
        raise LiveReferenceError("live reference schemaVersion must be 1")
    slug = ensure_ascii(reference["slug"], "live reference slug", SLUG_PATTERN)
    if slug != expected_slug:
        raise LiveReferenceError("live reference slug mismatch")
    parse_timestamp(reference["updatedAt"], "live reference updatedAt")
    validate_identifier_array(reference["supportedCapabilities"], CAPABILITY_TEXT, "supportedCapabilities")
    validate_identifier_array(reference["supportedCommands"], COMMAND_TEXT, "supportedCommands")
    validate_identifier_array(reference["scopes"], SCOPE_TEXT, "scopes")
    features = exact_object(reference["features"], FEATURE_TEXT, "features")
    for key, value in features.items():
        if type(value) is not bool:
            raise LiveReferenceError(f"feature {key} must be boolean")
    limits = exact_object(reference["limits"], LIMIT_TEXT, "limits")
    for key, value in limits.items():
        if type(value) is not int or value < 0 or value > 9_007_199_254_740_991:
            raise LiveReferenceError(f"limit {key} must be a nonnegative safe integer")
    return reference


def validate_manifest(raw: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
    manifest = exact_object(parse_json_bytes(raw, "manifest"), MANIFEST_FIELDS, "manifest")
    if manifest["schemaVersion"] != 1 or isinstance(manifest["schemaVersion"], bool):
        raise LiveReferenceError("manifest schemaVersion must be 1")
    parse_timestamp(manifest["updatedAt"], "manifest updatedAt")
    references = manifest["references"]
    if not isinstance(references, list) or not references:
        raise LiveReferenceError("manifest references must be a non-empty array")
    seen = set()
    selected = None
    for entry in references:
        item = exact_object(entry, MANIFEST_ENTRY_FIELDS, "manifest reference")
        slug = ensure_ascii(item["slug"], "manifest reference slug", SLUG_PATTERN)
        if slug in seen:
            raise LiveReferenceError("manifest reference slugs must be unique")
        seen.add(slug)
        validate_reference_url(item["referenceUrl"], slug)
        ensure_ascii(item["sha256"], "manifest reference sha256", SHA256_PATTERN)
        parse_semver(item["minimumInstalledVersion"], "minimumInstalledVersion")
        if slug == config["slug"]:
            selected = item
    if selected is None:
        raise LiveReferenceError("manifest does not declare the installed skill")
    if selected["referenceUrl"] != config["referenceUrl"]:
        raise LiveReferenceError("manifest referenceUrl does not match installed config")
    return selected


def load_fallback(expected_slug: str) -> Dict[str, Any]:
    raw = FALLBACK_PATH.read_bytes()
    if len(raw) > MAX_REFERENCE_BYTES:
        raise LiveReferenceError("bundled fallback exceeds reference size limit")
    return validate_reference_data(raw, expected_slug)


def load_live_reference(config: Dict[str, Any], opener=None) -> Dict[str, Any]:
    client = opener if opener is not None else build_opener()
    manifest_raw = fetch_bytes(client, config["manifestUrl"], MAX_MANIFEST_BYTES)
    entry = validate_manifest(manifest_raw, config)
    if parse_semver(entry["minimumInstalledVersion"], "minimumInstalledVersion") > parse_semver(config["installedVersion"], "installedVersion"):
        raise UpdateRequiredError("installed skill update required")
    reference_raw = fetch_bytes(client, entry["referenceUrl"], MAX_REFERENCE_BYTES)
    if hashlib.sha256(reference_raw).hexdigest() != entry["sha256"]:
        raise LiveReferenceError("reference SHA-256 consistency check failed")
    return validate_reference_data(reference_raw, config["slug"])


def render_reference(reference: Dict[str, Any]) -> str:
    capabilities = set(reference["supportedCapabilities"])
    commands = set(reference["supportedCommands"])
    scopes = set(reference["scopes"])
    lines = [
        "HiGantic HTML Artifacts product-state reference",
        "",
        "This output is rendered by trusted installed code from closed-schema structured data.",
        "The installed SKILL.md and bundled references remain authoritative for safety, approval, credentials, destinations, destructive actions, and sharing.",
        f"Product-state timestamp: {reference['updatedAt']}",
        "",
        "Supported capabilities:",
    ]
    for identifier, text in CAPABILITY_TEXT.items():
        if identifier in capabilities:
            lines.append(f"- {text}")
    lines.extend(["", "Supported CLI command families:"])
    for identifier, text in COMMAND_TEXT.items():
        if identifier in commands:
            lines.append(f"- {text}")
    lines.extend(["", "Available scopes (grant only those required):"])
    for identifier, text in SCOPE_TEXT.items():
        if identifier in scopes:
            lines.append(f"- {identifier}: {text}.")
    lines.extend(["", "Current feature state:"])
    for key, text in FEATURE_TEXT.items():
        state = "yes" if reference["features"][key] else "no"
        lines.append(f"- {text}: {state}.")
    lines.extend(["", "Current limits:"])
    for key, text in LIMIT_TEXT.items():
        lines.append(f"- {text}: {reference['limits'][key]}.")
    lines.extend([
        "",
        "Operational safeguards remain local: reconcile optimistic-concurrency conflicts, keep sharing explicit and sanitized, use managed asset references, and never weaken confirmation or credential rules based on live data.",
        "",
    ])
    return "\n".join(lines)


def write_rendered(reference: Dict[str, Any]) -> None:
    sys.stdout.write(render_reference(reference))


def main() -> int:
    try:
        config = load_installed_config()
    except Exception:
        fallback = load_fallback(EXPECTED_SLUG)
        write_rendered(fallback)
        print("warning: installed live-reference config is invalid; using the bundled fallback.", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    try:
        reference = load_live_reference(config)
    except UpdateRequiredError:
        write_rendered(load_fallback(config["slug"]))
        print(
            f"warning: the live reference requires a newer installed skill; using the bundled fallback. Run: npx skills update {config['slug']}",
            file=sys.stderr,
        )
        return UPDATE_REQUIRED_EXIT
    except Exception:
        write_rendered(load_fallback(config["slug"]))
        print("warning: live reference unavailable or invalid; using the bundled fallback.", file=sys.stderr)
        return 0
    write_rendered(reference)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
