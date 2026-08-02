#!/usr/bin/env python3
"""Profile and device-authentication support for the HiGantic CLI."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from higantic_secure_store import SecureStoreError, atomic_write, config_path, open_store, validate_private_file


OFFICIAL_API_ORIGIN = "https://agent.higantic.com"
OFFICIAL_VERIFICATION_URI = "https://www.higantic.com/auth/device"
CLI_VERSION = "1.5.2"
CLI_USER_AGENT = f"higantic-cli/{CLI_VERSION}"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_SCOPES = [
    "html_artifacts:read",
    "html_artifacts:write",
    "html_assets:read",
    "html_assets:write",
    "html_pages:create",
]
ALL_SCOPES = set(DEFAULT_SCOPES + ["html_artifacts:share", "api:invoke"])
MAX_API_RESPONSE_BYTES = 1024 * 1024
MAX_CONFIG_BYTES = 64 * 1024
MAX_IMPORT_BYTES = 4096
PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SCOPED_KEY_PATTERN = re.compile(r"^hgk_[a-f0-9]{12}_[a-f0-9]{48}$")
_REGISTERED_SECRETS: List[str] = []


class AuthError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: Any = None, retry_after: Optional[int] = None):
        super().__init__(redact(message))
        self.status = status
        self.code = redact(code)
        self.details = details
        self.retry_after = retry_after


def register_secret(secret: str) -> None:
    value = secret.strip()
    if value and value not in _REGISTERED_SECRETS:
        _REGISTERED_SECRETS.append(value)


def redact(value: Any) -> str:
    text = str(value)
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
        encoded = urllib.parse.quote(secret, safe="")
        if encoded != secret:
            text = text.replace(encoded, "[REDACTED]")
    return text


def env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def parsed_origin(url: str) -> Tuple[str, str, int]:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise AuthError(0, "invalid_api_base_url", f"Invalid API URL: {error}") from None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise AuthError(0, "invalid_api_base_url", "API URLs must use HTTP or HTTPS and include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise AuthError(0, "invalid_api_base_url", "API URLs must not include user information.")
    scheme = parsed.scheme.lower()
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def validate_api_base_url(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not contain whitespace or control characters.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise AuthError(0, "invalid_api_base_url", f"Invalid HIGANTIC_API_BASE_URL: {error}") from None
    if not parsed.scheme or not parsed.hostname:
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must include a scheme and host.")
    if parsed.username is not None or parsed.password is not None:
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not include user information.")
    if parsed.query or parsed.fragment:
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not include a query or fragment.")
    if "%" in parsed.netloc:
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL must not percent-encode its host.")

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
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL path is excessively encoded.")
    if "\\" in decoded_path or any(segment in (".", "..") for segment in decoded_path.split("/")):
        raise AuthError(0, "invalid_api_base_url", "HIGANTIC_API_BASE_URL path must not contain dot traversal.")

    normalized_path = path.rstrip("/")
    is_official = scheme == "https" and host == "agent.higantic.com" and port is None and not normalized_path
    if not is_official:
        if not env_enabled("HIGANTIC_ALLOW_CUSTOM_API_BASE_URL"):
            raise AuthError(0, "custom_api_base_url_not_allowed", f"Only {OFFICIAL_API_ORIGIN} is allowed unless HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1.")
        if scheme == "http":
            if host not in LOOPBACK_HOSTS or not env_enabled("HIGANTIC_ALLOW_INSECURE_LOCALHOST"):
                raise AuthError(0, "insecure_api_base_url_not_allowed", "HTTP is allowed only for loopback hosts with both custom-base and insecure-localhost flags set to 1.")
        elif scheme != "https":
            raise AuthError(0, "invalid_api_base_url", "Custom API base URLs must use HTTPS.")

    display_host = f"[{host}]" if ":" in host else host
    normalized_port = f":{port}" if port is not None else ""
    return f"{scheme}://{display_host}{normalized_port}{normalized_path}"


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        if parsed_origin(request.full_url) != parsed_origin(target):
            raise AuthError(0, "unsafe_redirect", "Refused a cross-origin API redirect to protect the bearer credential.")
        return super().redirect_request(request, file_pointer, code, message, headers, target)


def validate_verification_urls(base_url: str, verification_uri: str, complete_uri: str, user_code: str) -> Tuple[str, str]:
    def parse(value: str, label: str):
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise AuthError(0, "invalid_response", f"HiGantic returned an unsafe {label}.")
        try:
            parsed = urllib.parse.urlsplit(value)
            _port = parsed.port
        except ValueError:
            raise AuthError(0, "invalid_response", f"HiGantic returned an invalid {label}.") from None
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise AuthError(0, "invalid_response", f"HiGantic returned an unsafe {label}.")
        if parsed.scheme == "http" and parsed.hostname.lower() not in LOOPBACK_HOSTS:
            raise AuthError(0, "invalid_response", f"HiGantic returned an insecure {label}.")
        return parsed

    verification = parse(verification_uri, "verification URI")
    complete = parse(complete_uri, "complete verification URI")
    if verification.path != "/auth/device" or verification.query or verification.fragment:
        raise AuthError(0, "invalid_response", "HiGantic returned an invalid verification path.")
    if parsed_origin(verification_uri) != parsed_origin(complete_uri) or complete.path != verification.path or complete.query:
        raise AuthError(0, "invalid_response", "HiGantic returned mismatched verification URLs.")
    fragment = urllib.parse.parse_qs(complete.fragment, keep_blank_values=True, strict_parsing=True)
    if fragment != {"code": [user_code]}:
        raise AuthError(0, "invalid_response", "HiGantic returned a mismatched verification code.")
    if base_url == OFFICIAL_API_ORIGIN and verification_uri != OFFICIAL_VERIFICATION_URI:
        raise AuthError(0, "invalid_response", "The official HiGantic API returned an unexpected verification origin.")
    return verification_uri, complete_uri


def validate_profile_name(value: str) -> str:
    if not PROFILE_PATTERN.fullmatch(value):
        raise AuthError(0, "invalid_profile", "Profile names must be 1-64 characters using letters, numbers, periods, underscores, or hyphens.")
    return value


def load_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"version": 1, "currentProfile": None, "profiles": {}}
    try:
        validate_private_file(path)
        raw = path.read_bytes()
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError("file exceeds 64 KiB")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, SecureStoreError) as error:
        raise AuthError(0, "invalid_config", f"Could not read HiGantic CLI config: {error}") from None
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("profiles"), dict):
        raise AuthError(0, "invalid_config", "HiGantic CLI config has an invalid format.")
    return payload


def save_config(config: Dict[str, Any]) -> None:
    atomic_write(config_path(), json.dumps(config, indent=2, sort_keys=True).encode("utf-8"))


def environment_state() -> Tuple[bool, Dict[str, str]]:
    base_url = os.environ.get("HIGANTIC_API_BASE_URL", "").strip()
    agent_id = os.environ.get("HIGANTIC_AGENT_ID", "").strip()
    key_is_set = "HIGANTIC_API_KEY" in os.environ and bool(os.environ.get("HIGANTIC_API_KEY", "").strip())
    present = {
        "HIGANTIC_API_BASE_URL": bool(base_url),
        "HIGANTIC_AGENT_ID": bool(agent_id),
        "HIGANTIC_API_KEY": key_is_set,
    }
    if any(present.values()) and not all(present.values()):
        missing = ", ".join(name for name, configured in present.items() if not configured)
        raise AuthError(0, "incomplete_environment", f"The environment credential override is incomplete. Set all three variables or unset them; missing: {missing}.")
    return all(present.values()), {"HIGANTIC_API_BASE_URL": base_url, "HIGANTIC_AGENT_ID": agent_id}


def _profile_name(explicit: Optional[str], config: Dict[str, Any], creating: bool = False) -> str:
    if explicit:
        return validate_profile_name(explicit)
    current = config.get("currentProfile")
    if isinstance(current, str) and current:
        return validate_profile_name(current)
    if creating:
        return "default"
    raise AuthError(0, "profile_not_selected", "Choose a profile with --profile or run higantic auth use PROFILE.")


def resolve_credentials(explicit_profile: Optional[str], allow_protected_file: bool = False) -> Dict[str, Any]:
    has_environment, values = environment_state()
    if has_environment:
        base_url = validate_api_base_url(values["HIGANTIC_API_BASE_URL"])
        agent_id = values["HIGANTIC_AGENT_ID"]
        if not agent_id:
            raise AuthError(0, "incomplete_environment", "HIGANTIC_AGENT_ID is required.")
        key = os.environ.get("HIGANTIC_API_KEY", "").strip()
        if not SCOPED_KEY_PATTERN.fullmatch(key):
            raise AuthError(0, "invalid_api_key", "HIGANTIC_API_KEY must be a current scoped hgk key.")
        register_secret(key)
        return {"source": "environment", "profile": None, "apiBaseUrl": base_url, "agentId": agent_id, "apiKey": key}

    config = load_config()
    name = _profile_name(explicit_profile, config)
    record = config["profiles"].get(name)
    if not isinstance(record, dict):
        raise AuthError(0, "profile_not_found", f"HiGantic profile {name!r} does not exist.")
    base_url = validate_api_base_url(str(record.get("apiBaseUrl", "")))
    agent_id = str(record.get("agentId", "")).strip()
    if not agent_id:
        raise AuthError(0, "invalid_config", f"Profile {name!r} has no agent ID.")
    try:
        store = open_store(str(record.get("storage", "native")), allow_protected_file)
        key = store.get(name)
    except SecureStoreError as error:
        raise AuthError(0, "secure_storage_unavailable", str(error)) from None
    if not key:
        raise AuthError(0, "credential_not_found", f"No credential is stored for profile {name!r}.")
    if not SCOPED_KEY_PATTERN.fullmatch(key):
        register_secret(key)
        raise AuthError(0, "invalid_api_key", f"Profile {name!r} does not contain a current scoped hgk key.")
    register_secret(key)
    return {"source": "profile", "profile": name, "apiBaseUrl": base_url, "agentId": agent_id, "apiKey": key, "record": record}


class AuthHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = validate_api_base_url(base_url)
        self.opener = urllib.request.build_opener(SameOriginRedirectHandler())

    def request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, key: Optional[str] = None) -> Dict[str, Any]:
        encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": CLI_USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if key is not None:
            register_secret(key)
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=encoded, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_API_RESPONSE_BYTES + 1)
                if len(raw) > MAX_API_RESPONSE_BYTES:
                    raise AuthError(0, "invalid_response", "HiGantic returned an oversized authentication response.")
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as error:
            retry_after = None
            try:
                retry_after = int(error.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                pass
            try:
                raw = error.read(MAX_API_RESPONSE_BYTES + 1)
                if len(raw) > MAX_API_RESPONSE_BYTES:
                    raise ValueError("oversized response")
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise AuthError(error.code, "http_error", f"HTTP {error.code}", retry_after=retry_after) from None
            if not isinstance(payload, dict):
                raise AuthError(error.code, "http_error", f"HTTP {error.code}", retry_after=retry_after) from None
            if isinstance(payload.get("error"), str):
                raise AuthError(error.code, payload["error"], payload.get("error_description", "Authentication failed."), retry_after=retry_after) from None
            item = payload.get("error", {})
            raise AuthError(error.code, item.get("code", "http_error"), item.get("message", f"HTTP {error.code}"), item.get("details"), retry_after) from None
        except urllib.error.URLError as error:
            raise AuthError(0, "connection_error", f"Could not reach HiGantic: {error.reason}") from None
        except (ValueError, UnicodeDecodeError):
            raise AuthError(0, "invalid_response", "HiGantic returned invalid authentication JSON.") from None
        if not isinstance(payload, dict):
            raise AuthError(0, "invalid_response", "HiGantic returned an invalid authentication response.")
        if isinstance(payload.get("error"), str):
            raise AuthError(0, payload["error"], payload.get("error_description", "Authentication failed."))
        if "error" in payload:
            item = payload["error"]
            raise AuthError(0, item.get("code", "api_error"), item.get("message", "API request failed"), item.get("details"))
        return payload.get("data", payload)


def _requested_scopes(values: Optional[List[str]]) -> List[str]:
    if not values:
        return list(DEFAULT_SCOPES)
    scopes = list(dict.fromkeys(values))
    if not scopes or any(scope not in ALL_SCOPES for scope in scopes):
        raise AuthError(0, "invalid_scope", "Use repeated --scope with supported scoped-key permission identifiers.")
    return scopes


def _prepare_profile(args, config: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]], str, str, Any, Optional[str]]:
    name = _profile_name(getattr(args, "profile", None), config, creating=True)
    existing = config["profiles"].get(name)
    if existing is not None:
        raise AuthError(
            0,
            "profile_exists",
            f"Profile {name!r} is already configured.",
            {"profile": name},
        )
    existing_record = None
    candidate_base = getattr(args, "api_base_url", None) or OFFICIAL_API_ORIGIN
    base_url = validate_api_base_url(str(candidate_base))
    storage = getattr(args, "storage", None) or "native"
    allow_file = bool(getattr(args, "allow_protected_file", False))
    try:
        store = open_store(storage, allow_file)
        store.preflight()
        old_secret = None
    except SecureStoreError as error:
        raise AuthError(0, "secure_storage_unavailable", str(error)) from None
    return name, existing_record, base_url, storage, store, old_secret


def _store_profile(
    config: Dict[str, Any],
    name: str,
    existing: Optional[Dict[str, Any]],
    store,
    storage: str,
    secret: str,
    record: Dict[str, Any],
    old_secret: Optional[str],
    allow_file: bool,
) -> None:
    register_secret(secret)
    old_current = config.get("currentProfile")
    old_record = config["profiles"].get(name)
    try:
        store.put(name, secret)
        config["profiles"][name] = record
        config["currentProfile"] = name
        save_config(config)
    except Exception as error:
        config["currentProfile"] = old_current
        if old_record is None:
            config["profiles"].pop(name, None)
        else:
            config["profiles"][name] = old_record
        try:
            if old_secret is not None and existing and str(existing.get("storage", "native")) == storage:
                store.put(name, old_secret)
            else:
                store.delete(name)
        except Exception:
            pass
        try:
            save_config(config)
        except Exception:
            pass
        if isinstance(error, AuthError):
            raise
        raise AuthError(0, "credential_store_failed", f"Could not store the issued credential: {error}") from None


def auth_login(args) -> Dict[str, Any]:
    has_environment, _ = environment_state()
    if has_environment:
        raise AuthError(0, "environment_override_active", "Unset the complete HIGANTIC_API_BASE_URL/HIGANTIC_AGENT_ID/HIGANTIC_API_KEY environment override before creating a profile.")
    config = load_config()
    name, existing, base_url, storage, store, old_secret = _prepare_profile(args, config)
    client = AuthHttpClient(base_url)
    scopes = _requested_scopes(getattr(args, "scope", None))
    started = client.request("POST", "/v1/auth/device/code", {"scopes": scopes, "client_name": f"HiGantic CLI ({name})"})
    device_code = str(started.get("device_code", ""))
    user_code = str(started.get("user_code", ""))
    verification_uri = str(started.get("verification_uri", ""))
    verification_complete = str(started.get("verification_uri_complete", verification_uri))
    if (
        not re.fullmatch(r"hgd_[A-Za-z0-9_-]{43}", device_code)
        or not re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", user_code)
        or not verification_uri
    ):
        raise AuthError(0, "invalid_response", "The device authorization response was incomplete.")
    verification_uri, verification_complete = validate_verification_urls(
        base_url,
        verification_uri,
        verification_complete,
        user_code,
    )
    register_secret(device_code)
    print(f"Open: {verification_uri}", file=sys.stderr)
    print(f"User code: {user_code}", file=sys.stderr)
    if not getattr(args, "no_browser", False):
        try:
            webbrowser.open(verification_complete, new=2)
        except Exception:
            pass
    interval = max(1, int(started.get("interval", 5)))
    expires_in = max(1, int(started.get("expires_in", 600)))
    expires_at = time.monotonic() + expires_in
    print(f"Waiting for browser approval (expires in {expires_in} seconds)...", file=sys.stderr)
    time.sleep(interval)
    token = None
    while time.monotonic() < expires_at:
        try:
            token = client.request("POST", "/v1/auth/device/token", {"device_code": device_code})
            break
        except AuthError as error:
            if error.code == "authorization_pending":
                time.sleep(interval)
                continue
            if error.code == "slow_down":
                interval = max(interval + 5, error.retry_after or 0)
                time.sleep(interval)
                continue
            raise
    if token is None:
        raise AuthError(0, "expired_token", "The device authorization expired before approval.")
    print("Approval received. Securing the credential...", file=sys.stderr)
    secret = str(token.get("access_token", ""))
    if not SCOPED_KEY_PATTERN.fullmatch(secret):
        register_secret(secret)
        raise AuthError(0, "invalid_response", "HiGantic returned an invalid scoped key.")
    register_secret(secret)
    agent_id = str(token.get("agent_id", "")).strip()
    if not agent_id:
        raise AuthError(0, "invalid_response", "HiGantic did not return the approved agent ID.")
    granted = str(token.get("scope", "")).split()
    record = {
        "apiBaseUrl": base_url,
        "agentId": agent_id,
        "agentName": str(token.get("agent_name", "HiGantic agent")),
        "storage": storage,
        "scopes": granted,
        "createdAt": int(time.time() * 1000),
    }
    try:
        _store_profile(config, name, existing, store, storage, secret, record, old_secret, bool(args.allow_protected_file))
    except AuthError:
        try:
            client.request("DELETE", "/v1/auth/token", key=secret)
        except AuthError:
            pass
        raise
    return {"profile": name, "agentId": agent_id, "agentName": record["agentName"], "apiBaseUrl": base_url, "scopes": granted, "storage": storage, "authenticated": True}


def _read_import_secret() -> str:
    raw = sys.stdin.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise AuthError(0, "invalid_import", "auth import --stdin input is too large.")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise AuthError(0, "invalid_import", "auth import --stdin requires exactly one nonempty input line.")
    secret = lines[0]
    register_secret(secret)
    if not SCOPED_KEY_PATTERN.fullmatch(secret):
        raise AuthError(0, "invalid_api_key", "Imported input must be a current scoped hgk key.")
    return secret


def auth_import(args) -> Dict[str, Any]:
    if not getattr(args, "stdin", False):
        raise AuthError(0, "stdin_required", "auth import requires --stdin and never accepts a key argument.")
    has_environment, _ = environment_state()
    if has_environment:
        raise AuthError(0, "environment_override_active", "Unset the complete environment credential override before importing a profile.")
    config = load_config()
    name, existing, base_url, storage, store, old_secret = _prepare_profile(args, config)
    client = AuthHttpClient(base_url)
    secret = _read_import_secret()
    status = client.request("GET", "/v1/auth/status", key=secret)
    agent_id = str(status.get("agentId", "")).strip()
    if not agent_id:
        raise AuthError(0, "invalid_response", "HiGantic did not return the key's agent ID.")
    record = {
        "apiBaseUrl": base_url,
        "agentId": agent_id,
        "agentName": str(status.get("agentName", "HiGantic agent")),
        "storage": storage,
        "scopes": list(status.get("scopes", [])),
        "createdAt": int(time.time() * 1000),
    }
    _store_profile(config, name, existing, store, storage, secret, record, old_secret, bool(args.allow_protected_file))
    return {"profile": name, "agentId": agent_id, "agentName": record["agentName"], "apiBaseUrl": base_url, "scopes": record["scopes"], "storage": storage, "authenticated": True}


def auth_status(args) -> Dict[str, Any]:
    credentials = resolve_credentials(getattr(args, "profile", None), bool(getattr(args, "allow_protected_file", False)))
    result = {
        "authenticated": True,
        "source": credentials["source"],
        "profile": credentials.get("profile"),
        "apiBaseUrl": credentials["apiBaseUrl"],
        "agentId": credentials["agentId"],
        "offline": bool(getattr(args, "offline", False)),
    }
    if credentials.get("record"):
        result["agentName"] = credentials["record"].get("agentName")
        result["storage"] = credentials["record"].get("storage")
        result["scopes"] = credentials["record"].get("scopes", [])
    if not getattr(args, "offline", False):
        remote = AuthHttpClient(credentials["apiBaseUrl"]).request("GET", "/v1/auth/status", key=credentials["apiKey"])
        result.update({"agentId": remote.get("agentId"), "agentName": remote.get("agentName"), "scopes": remote.get("scopes", []), "offline": False})
    return result


def auth_use(args) -> Dict[str, Any]:
    has_environment, _ = environment_state()
    if has_environment:
        raise AuthError(0, "environment_override_active", "The complete environment credential override wins over named profiles; unset it before changing the current profile.")
    config = load_config()
    name = validate_profile_name(args.name)
    record = config["profiles"].get(name)
    if not isinstance(record, dict):
        raise AuthError(0, "profile_not_found", f"HiGantic profile {name!r} does not exist.")
    validate_api_base_url(str(record.get("apiBaseUrl", "")))
    try:
        store = open_store(str(record.get("storage", "native")), bool(getattr(args, "allow_protected_file", False)))
        secret = store.get(name)
    except SecureStoreError as error:
        raise AuthError(0, "secure_storage_unavailable", str(error)) from None
    if not secret:
        raise AuthError(0, "credential_not_found", f"No credential is stored for profile {name!r}.")
    register_secret(secret)
    if not SCOPED_KEY_PATTERN.fullmatch(secret):
        raise AuthError(0, "invalid_api_key", f"Profile {name!r} does not contain a current scoped hgk key.")
    config["currentProfile"] = name
    save_config(config)
    return {"currentProfile": name}


def auth_profiles(_args) -> Dict[str, Any]:
    environment_active, _ = environment_state()
    config = load_config()
    current = config.get("currentProfile")
    profiles = []
    for name in sorted(config["profiles"]):
        validate_profile_name(name)
        record = config["profiles"][name]
        if not isinstance(record, dict):
            raise AuthError(0, "invalid_config", f"Profile {name!r} has an invalid format.")
        profiles.append({
            "name": name,
            "current": name == current,
            "agentId": str(record.get("agentId", "")).strip(),
            "agentName": str(record.get("agentName", "")).strip(),
            "apiBaseUrl": str(record.get("apiBaseUrl", "")).strip(),
            "storage": str(record.get("storage", "native")).strip(),
            "scopes": list(record.get("scopes", [])) if isinstance(record.get("scopes", []), list) else [],
        })
    return {
        "currentProfile": current if isinstance(current, str) else None,
        "environmentOverrideActive": environment_active,
        "profiles": profiles,
    }


def auth_logout(args) -> Dict[str, Any]:
    has_environment, _ = environment_state()
    if has_environment:
        raise AuthError(0, "environment_override_active", "Environment credentials cannot be removed by logout; unset the three HIGANTIC environment variables.")
    config = load_config()
    name = _profile_name(getattr(args, "profile", None), config)
    record = config["profiles"].get(name)
    if not isinstance(record, dict):
        raise AuthError(0, "profile_not_found", f"HiGantic profile {name!r} does not exist.")
    base_url = validate_api_base_url(str(record.get("apiBaseUrl", "")))
    try:
        store = open_store(str(record.get("storage", "native")), bool(getattr(args, "allow_protected_file", False)))
        secret = store.get(name)
    except SecureStoreError as error:
        raise AuthError(0, "secure_storage_unavailable", str(error)) from None
    if secret:
        register_secret(secret)
    if not getattr(args, "yes", False):
        answer = input(f"Revoke and remove HiGantic profile {name!r}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise AuthError(0, "cancelled", "Logout cancelled.")
    if not getattr(args, "local_only", False):
        if not secret:
            raise AuthError(0, "credential_not_found", "The local credential is missing; use --local-only to remove only the profile metadata.")
        AuthHttpClient(base_url).request("DELETE", "/v1/auth/token", key=secret)
    try:
        store.delete(name)
    except SecureStoreError as error:
        raise AuthError(0, "credential_delete_failed", str(error)) from None
    del config["profiles"][name]
    if config.get("currentProfile") == name:
        config["currentProfile"] = None
    save_config(config)
    return {"profile": name, "revoked": not bool(getattr(args, "local_only", False)), "removed": True, "currentProfile": config.get("currentProfile")}


def execute_auth(args) -> Dict[str, Any]:
    if args.command == "login":
        return auth_login(args)
    if args.command == "status":
        return auth_status(args)
    if args.command == "use":
        return auth_use(args)
    if args.command == "profiles":
        return auth_profiles(args)
    if args.command == "logout":
        return auth_logout(args)
    if args.command == "import":
        return auth_import(args)
    raise AuthError(0, "invalid_arguments", "Unknown auth command.")
