#!/usr/bin/env python3
"""Fetch constrained Managed Assets product state and render trusted local text."""

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
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_.:-]+$")

CAPABILITY_TEXT = {
    "managed-assets": "List, inspect, upload, and deliberately delete managed image assets.",
    "asset-storage-targets": "Discover and select available HiGantic or linked UploadThing storage targets.",
    "standalone-asset-visibility": "Explicitly publish or privatize stable standalone image viewers.",
}
COMMAND_TEXT = {
    "assets.list": "assets list",
    "assets.show": "assets show",
    "assets.upload": "assets upload",
    "assets.delete": "assets delete",
    "assets.targets": "assets targets list/status/use",
    "assets.make_public": "assets make-public",
    "assets.make_private": "assets make-private",
}
SCOPE_TEXT = {
    "assets:read": "list and inspect assets and storage targets",
    "assets:write": "upload, privatize, and delete private assets",
    "assets:share": "publish assets and authorize deletion of public assets",
}
FEATURE_TEXT = {
    "assetStorageTargetsSupported": "Storage-target selection is supported",
    "stablePublicVisibilitySupported": "Stable standalone public visibility is supported",
    "remoteAssetImportSupported": "Remote image import is supported",
    "publicAssetDeletionRequiresShareScope": "Deleting a public asset requires share scope",
    "pinnedArtifactSnapshotsIndependent": "Pinned artifact snapshots remain independent of live asset state",
}
LIMIT_TEXT = {
    "assetUploadBytes": "Maximum managed asset upload bytes",
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
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise LiveReferenceError("invalid URL") from error
    if parsed.scheme != "https" or parsed.hostname != "skills.higantic.com" or parsed.netloc != "skills.higantic.com" or port is not None:
        raise LiveReferenceError("URL must use the exact branded origin")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise LiveReferenceError("URL must not contain user information, query, or fragment")
    return parsed.scheme, parsed.hostname, 443


def expected_reference_url(slug: str) -> str:
    return PUBLIC_ORIGIN + REFERENCE_PATH_PREFIX + slug + ".json"


def validate_reference_url(value: Any, slug: str) -> str:
    url = ensure_ascii(value, "referenceUrl")
    parsed_origin(url)
    parsed = urllib.parse.urlsplit(url)
    decoded = parsed.path
    for _ in range(10):
        next_value = urllib.parse.unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        raise LiveReferenceError("referenceUrl path is excessively encoded")
    if "\\" in decoded or any(segment in (".", "..") for segment in decoded.split("/")):
        raise LiveReferenceError("referenceUrl path contains traversal")
    expected = expected_reference_url(slug)
    if url != expected:
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
        status = getattr(response, "status", response.getcode())
        if status != 200 or response.geturl() != url:
            raise LiveReferenceError("unexpected response status or final URL")
        length = response.headers.get("Content-Length") if response.headers is not None else None
        if length is not None and (re.fullmatch(r"0|[1-9]\d*", length.strip()) is None or int(length) > maximum):
            raise LiveReferenceError("invalid or excessive Content-Length")
        body = response.read(maximum + 1)
        if len(body) > maximum or (length is not None and int(length) != len(body)):
            raise LiveReferenceError("response size is invalid")
        return body


def load_installed_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise LiveReferenceError("installed config exceeds size limit")
    config = exact_object(parse_json_bytes(raw, "installed config"), CONFIG_FIELDS, "installed config")
    if config["schemaVersion"] != 1 or isinstance(config["schemaVersion"], bool):
        raise LiveReferenceError("installed config schemaVersion must be 1")
    slug = ensure_ascii(config["slug"], "installed slug", SLUG_PATTERN)
    if slug != EXPECTED_SLUG:
        raise LiveReferenceError("installed slug does not match skill directory")
    parse_semver(config["installedVersion"], "installedVersion")
    if config["manifestUrl"] != EXACT_MANIFEST_URL:
        raise LiveReferenceError("manifestUrl must use the exact branded path")
    parsed_origin(config["manifestUrl"])
    validate_reference_url(config["referenceUrl"], slug)
    return config


def validate_identifier_array(value: Any, allowlist: Dict[str, str], label: str) -> list:
    if not isinstance(value, list):
        raise LiveReferenceError(label + " must be an array")
    seen = set()
    for identifier in value:
        text = ensure_ascii(identifier, label, IDENTIFIER_PATTERN)
        if text not in allowlist or text in seen:
            raise LiveReferenceError(label + " contains an unknown or duplicate identifier")
        seen.add(text)
    return value


def validate_reference_data(raw: bytes, expected_slug: str) -> Dict[str, Any]:
    reference = exact_object(parse_json_bytes(raw, "live reference"), REFERENCE_FIELDS, "live reference")
    if reference["schemaVersion"] != 1 or isinstance(reference["schemaVersion"], bool):
        raise LiveReferenceError("live reference schemaVersion must be 1")
    if ensure_ascii(reference["slug"], "live reference slug", SLUG_PATTERN) != expected_slug:
        raise LiveReferenceError("live reference slug mismatch")
    parse_timestamp(reference["updatedAt"], "updatedAt")
    validate_identifier_array(reference["supportedCapabilities"], CAPABILITY_TEXT, "supportedCapabilities")
    validate_identifier_array(reference["supportedCommands"], COMMAND_TEXT, "supportedCommands")
    validate_identifier_array(reference["scopes"], SCOPE_TEXT, "scopes")
    for key, value in exact_object(reference["features"], FEATURE_TEXT, "features").items():
        if type(value) is not bool:
            raise LiveReferenceError("feature " + key + " must be boolean")
    for key, value in exact_object(reference["limits"], LIMIT_TEXT, "limits").items():
        if type(value) is not int or value < 0 or value > 9_007_199_254_740_991:
            raise LiveReferenceError("limit " + key + " must be a nonnegative safe integer")
    return reference


def validate_manifest(raw: bytes, config: Dict[str, Any]) -> Dict[str, Any]:
    manifest = exact_object(parse_json_bytes(raw, "manifest"), MANIFEST_FIELDS, "manifest")
    if manifest["schemaVersion"] != 1 or isinstance(manifest["schemaVersion"], bool):
        raise LiveReferenceError("manifest schemaVersion must be 1")
    parse_timestamp(manifest["updatedAt"], "manifest updatedAt")
    if not isinstance(manifest["references"], list) or not manifest["references"]:
        raise LiveReferenceError("manifest references must be a non-empty array")
    selected = None
    seen = set()
    for raw_entry in manifest["references"]:
        entry = exact_object(raw_entry, MANIFEST_ENTRY_FIELDS, "manifest reference")
        slug = ensure_ascii(entry["slug"], "manifest reference slug", SLUG_PATTERN)
        if slug in seen:
            raise LiveReferenceError("manifest reference slugs must be unique")
        seen.add(slug)
        validate_reference_url(entry["referenceUrl"], slug)
        ensure_ascii(entry["sha256"], "sha256", SHA256_PATTERN)
        parse_semver(entry["minimumInstalledVersion"], "minimumInstalledVersion")
        if slug == config["slug"]:
            selected = entry
    if selected is None or selected["referenceUrl"] != config["referenceUrl"]:
        raise LiveReferenceError("manifest does not match installed skill")
    return selected


def load_fallback(expected_slug: str) -> Dict[str, Any]:
    raw = FALLBACK_PATH.read_bytes()
    if len(raw) > MAX_REFERENCE_BYTES:
        raise LiveReferenceError("bundled fallback exceeds size limit")
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
    lines = [
        "HiGantic Managed Assets product-state reference",
        "",
        "This output is rendered by trusted installed code from closed-schema structured data.",
        "The installed SKILL.md and bundled references remain authoritative for safety, approval, credentials, destinations, destructive actions, and sharing.",
        "Product-state timestamp: " + reference["updatedAt"],
        "",
        "Supported capabilities:",
    ]
    for identifier, text in CAPABILITY_TEXT.items():
        if identifier in reference["supportedCapabilities"]:
            lines.append("- " + text)
    lines.append("")
    lines.append("Supported CLI command families:")
    for identifier, text in COMMAND_TEXT.items():
        if identifier in reference["supportedCommands"]:
            lines.append("- " + text)
    lines.append("")
    lines.append("Available scopes (grant only those required):")
    for identifier, text in SCOPE_TEXT.items():
        if identifier in reference["scopes"]:
            lines.append("- " + identifier + ": " + text + ".")
    lines.append("")
    lines.append("Current feature state:")
    for key, text in FEATURE_TEXT.items():
        lines.append("- " + text + ": " + ("yes" if reference["features"][key] else "no") + ".")
    lines.append("")
    lines.append("Current limits:")
    for key, text in LIMIT_TEXT.items():
        lines.append("- " + text + ": " + str(reference["limits"][key]) + ".")
    lines.extend(["", "Operational safeguards remain local: keep uploads private by default, require explicit sharing and deletion confirmation, and never expose provider URLs.", ""])
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
        sys.stdout.write(render_reference(load_fallback(config["slug"])))
        print("warning: a newer skill is required; using the bundled fallback. Run: npx skills update " + config["slug"], file=sys.stderr)
        return UPDATE_REQUIRED_EXIT
    except Exception:
        reference = load_fallback(config["slug"])
        print("warning: live reference unavailable or invalid; using the bundled fallback.", file=sys.stderr)
    sys.stdout.write(render_reference(reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
