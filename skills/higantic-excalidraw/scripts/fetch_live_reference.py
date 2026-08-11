#!/usr/bin/env python3
"""Fetch constrained Canvas product state and render trusted local text."""

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
EXACT_MANIFEST_URL = PUBLIC_ORIGIN + "/v1/manifest.json"
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
ASCII_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")

CAPABILITY_TEXT = {
    "canvas-pages": "List existing Canvas pages and create one when required.",
    "canvas-scenes": "List, read, create, replace, and deliberately delete Canvas scenes.",
    "semantic-flowcharts": "Submit semantic nodes and edges for deterministic server-side layout and validation.",
}
COMMAND_TEXT = {
    "pages.list": "pages list",
    "pages.create": "pages create",
    "scenes.list": "scenes list",
    "scenes.get": "scenes get",
    "scenes.create": "scenes create",
    "scenes.replace": "scenes replace",
    "scenes.delete": "scenes delete",
}
SCOPE_TEXT = {
    "excalidraw:read": "list Canvas pages and scenes and read scene JSON",
    "excalidraw:write": "create, replace, and deliberately delete scenes",
    "excalidraw_pages:create": "create Canvas pages",
}
FEATURE_TEXT = {
    "semanticLayoutSupported": "Server-side semantic layout is supported",
    "optimisticConcurrencyRequired": "Scene replacement and deletion require optimistic concurrency",
    "rawSceneSupported": "Complete Excalidraw scene input is supported",
    "canvasPageDeletionSupported": "Direct Canvas page deletion is supported",
}
LIMIT_TEXT = {
    "sceneSourceBytes": "Maximum scene source bytes",
    "nodesPerFlowchart": "Maximum semantic nodes per flowchart",
    "edgesPerFlowchart": "Maximum semantic edges per flowchart",
    "requestsPerMinutePerKey": "Maximum requests per minute per key",
    "writesPerMinutePerKey": "Maximum writes per minute per key",
}
REFERENCE_FIELDS = {"schemaVersion", "slug", "updatedAt", "supportedCapabilities", "supportedCommands", "scopes", "features", "limits"}
CONFIG_FIELDS = {"schemaVersion", "slug", "installedVersion", "manifestUrl", "referenceUrl"}
MANIFEST_FIELDS = {"schemaVersion", "updatedAt", "references"}
MANIFEST_ENTRY_FIELDS = {"slug", "referenceUrl", "sha256", "minimumInstalledVersion"}


class LiveReferenceError(RuntimeError):
    pass


class UpdateRequiredError(LiveReferenceError):
    pass


def ensure_ascii(value: Any, label: str, pattern: Optional[re.Pattern] = None) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 or ord(char) > 0x7E for char in value):
        raise LiveReferenceError(label + " must be constrained ASCII")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise LiveReferenceError(label + " has an invalid value")
    return value


def unique_object(pairs):
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LiveReferenceError("duplicate JSON key")
        result[key] = value
    return result


def parse_json_bytes(raw: bytes, label: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LiveReferenceError(label + " is not UTF-8") from error
    if any(ord(char) > 0x7F for char in text):
        raise LiveReferenceError(label + " must contain ASCII JSON only")
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, LiveReferenceError) as error:
        raise LiveReferenceError(label + " is malformed") from error


def exact_object(value: Any, fields, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise LiveReferenceError(label + " has unexpected or missing fields")
    return value


def parse_semver(value: Any, label: str) -> Tuple[int, int, int]:
    text = ensure_ascii(value, label, SEMVER_PATTERN)
    return tuple(int(part) for part in text.split("."))  # type: ignore[return-value]


def parse_timestamp(value: Any, label: str) -> str:
    text = ensure_ascii(value, label, TIMESTAMP_PATTERN)
    try:
        datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise LiveReferenceError(label + " is not a real UTC timestamp") from error
    return text


def parsed_origin(url: str) -> Tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "skills.higantic.com" or parsed.netloc != "skills.higantic.com":
        raise LiveReferenceError("URL must use the exact branded HTTPS origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port is not None:
        raise LiveReferenceError("URL contains forbidden components")
    return (parsed.scheme, parsed.hostname, 443)


def expected_reference_url(slug: str) -> str:
    return PUBLIC_ORIGIN + REFERENCE_PATH_PREFIX + slug + ".json"


def validate_reference_url(value: Any, slug: str) -> str:
    url = ensure_ascii(value, "referenceUrl")
    parsed_origin(url)
    if url != expected_reference_url(slug):
        raise LiveReferenceError("referenceUrl does not match its slug")
    return url


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        if parsed_origin(request.full_url) != parsed_origin(target):
            raise LiveReferenceError("cross-origin redirect refused")
        return super().redirect_request(request, file_pointer, code, message, headers, target)


def build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), SameOriginRedirectHandler())


def fetch_bytes(opener, url: str, maximum: int) -> bytes:
    parsed_origin(url)
    request = urllib.request.Request(url, method="GET")
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        status = getattr(response, "status", response.getcode() if hasattr(response, "getcode") else None)
        if status != 200 or response.geturl() != url:
            raise LiveReferenceError("unexpected HTTP response")
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise LiveReferenceError("response exceeds size limit")
        return body


def load_installed_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise LiveReferenceError("installed config exceeds size limit")
    config = exact_object(parse_json_bytes(raw, "installed config"), CONFIG_FIELDS, "installed config")
    if config["schemaVersion"] != 1 or isinstance(config["schemaVersion"], bool):
        raise LiveReferenceError("invalid config schemaVersion")
    if ensure_ascii(config["slug"], "slug", SLUG_PATTERN) != EXPECTED_SLUG:
        raise LiveReferenceError("installed slug mismatch")
    parse_semver(config["installedVersion"], "installedVersion")
    if ensure_ascii(config["manifestUrl"], "manifestUrl") != EXACT_MANIFEST_URL:
        raise LiveReferenceError("manifestUrl mismatch")
    validate_reference_url(config["referenceUrl"], config["slug"])
    return config


def validate_identifier_array(value: Any, allowlist: Dict[str, str], label: str) -> list:
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise LiveReferenceError(label + " must be a unique array")
    for item in value:
        if ensure_ascii(item, label, ASCII_IDENTIFIER_PATTERN) not in allowlist:
            raise LiveReferenceError(label + " contains an unknown identifier")
    return value


def validate_reference_data(raw: bytes, expected_slug: str) -> Dict[str, Any]:
    data = exact_object(parse_json_bytes(raw, "live reference"), REFERENCE_FIELDS, "live reference")
    if data["schemaVersion"] != 1 or isinstance(data["schemaVersion"], bool):
        raise LiveReferenceError("invalid reference schemaVersion")
    if ensure_ascii(data["slug"], "slug", SLUG_PATTERN) != expected_slug:
        raise LiveReferenceError("live reference slug mismatch")
    parse_timestamp(data["updatedAt"], "updatedAt")
    validate_identifier_array(data["supportedCapabilities"], CAPABILITY_TEXT, "supportedCapabilities")
    validate_identifier_array(data["supportedCommands"], COMMAND_TEXT, "supportedCommands")
    validate_identifier_array(data["scopes"], SCOPE_TEXT, "scopes")
    features = exact_object(data["features"], FEATURE_TEXT, "features")
    if any(type(value) is not bool for value in features.values()):
        raise LiveReferenceError("feature values must be booleans")
    limits = exact_object(data["limits"], LIMIT_TEXT, "limits")
    if any(type(value) is not int or value < 0 or value > 9_007_199_254_740_991 for value in limits.values()):
        raise LiveReferenceError("limit values must be nonnegative safe integers")
    return data


def validate_manifest(raw: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
    manifest = exact_object(parse_json_bytes(raw, "manifest"), MANIFEST_FIELDS, "manifest")
    if manifest["schemaVersion"] != 1 or isinstance(manifest["schemaVersion"], bool):
        raise LiveReferenceError("invalid manifest schemaVersion")
    parse_timestamp(manifest["updatedAt"], "updatedAt")
    if not isinstance(manifest["references"], list) or not manifest["references"]:
        raise LiveReferenceError("manifest references must be nonempty")
    selected = None
    seen = set()
    for raw_entry in manifest["references"]:
        entry = exact_object(raw_entry, MANIFEST_ENTRY_FIELDS, "manifest reference")
        slug = ensure_ascii(entry["slug"], "slug", SLUG_PATTERN)
        if slug in seen:
            raise LiveReferenceError("duplicate manifest slug")
        seen.add(slug)
        validate_reference_url(entry["referenceUrl"], slug)
        ensure_ascii(entry["sha256"], "sha256", SHA256_PATTERN)
        parse_semver(entry["minimumInstalledVersion"], "minimumInstalledVersion")
        if slug == config["slug"]:
            selected = entry
    if selected is None or selected["referenceUrl"] != config["referenceUrl"]:
        raise LiveReferenceError("manifest does not declare the installed skill")
    return selected


def load_fallback(expected_slug: str) -> Dict[str, Any]:
    raw = FALLBACK_PATH.read_bytes()
    if len(raw) > MAX_REFERENCE_BYTES:
        raise LiveReferenceError("bundled fallback exceeds size limit")
    return validate_reference_data(raw, expected_slug)


def load_live_reference(config: Dict[str, Any], opener=None) -> Dict[str, Any]:
    client = opener or build_opener()
    entry = validate_manifest(fetch_bytes(client, config["manifestUrl"], MAX_MANIFEST_BYTES), config)
    if parse_semver(entry["minimumInstalledVersion"], "minimumInstalledVersion") > parse_semver(config["installedVersion"], "installedVersion"):
        raise UpdateRequiredError("installed skill update required")
    raw = fetch_bytes(client, entry["referenceUrl"], MAX_REFERENCE_BYTES)
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise LiveReferenceError("reference SHA-256 consistency check failed")
    return validate_reference_data(raw, config["slug"])


def render_reference(reference: Dict[str, Any]) -> str:
    lines = [
        "HiGantic Excalidraw product-state reference", "",
        "This output is rendered by trusted installed code from closed-schema structured data.",
        "Local skill instructions remain authoritative for credentials, conflicts, and destructive actions.",
        "Product-state timestamp: " + reference["updatedAt"], "", "Supported capabilities:",
    ]
    lines.extend("- " + CAPABILITY_TEXT[item] for item in reference["supportedCapabilities"])
    lines.extend(["", "Supported CLI command families:"])
    lines.extend("- " + COMMAND_TEXT[item] for item in reference["supportedCommands"])
    lines.extend(["", "Available scopes:"])
    lines.extend("- %s: %s." % (item, SCOPE_TEXT[item]) for item in reference["scopes"])
    lines.extend(["", "Current feature state:"])
    lines.extend("- %s: %s." % (text, "yes" if reference["features"][key] else "no") for key, text in FEATURE_TEXT.items())
    lines.extend(["", "Current limits:"])
    lines.extend("- %s: %s." % (text, reference["limits"][key]) for key, text in LIMIT_TEXT.items())
    lines.extend(["", "Operational safeguards remain local: read before replacement, reconcile conflicts, and confirm deletion.", ""])
    return "\n".join(lines)


def main() -> int:
    try:
        config = load_installed_config()
    except Exception:
        sys.stdout.write(render_reference(load_fallback(EXPECTED_SLUG)))
        print("warning: installed live-reference config is invalid; using the bundled fallback.", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    try:
        reference = load_live_reference(config)
    except UpdateRequiredError:
        reference = load_fallback(config["slug"])
        print("warning: a newer skill is required; using the bundled fallback.", file=sys.stderr)
        sys.stdout.write(render_reference(reference))
        return UPDATE_REQUIRED_EXIT
    except Exception:
        reference = load_fallback(config["slug"])
        print("warning: live reference unavailable or invalid; using the bundled fallback.", file=sys.stderr)
    sys.stdout.write(render_reference(reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
