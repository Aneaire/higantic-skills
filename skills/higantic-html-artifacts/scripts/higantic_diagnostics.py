#!/usr/bin/env python3
"""Read-only diagnostics for the HiGantic CLI."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from higantic_auth import (
    AuthError,
    AuthHttpClient,
    CLI_VERSION,
    environment_state,
    load_config,
    resolve_credentials,
)
from higantic_secure_store import SecureStoreError, open_store
from higantic_skill_install import installer_available


def _check(checks: List[Dict[str, str]], name: str, status: str, message: str) -> None:
    checks.append({"name": name, "status": status, "message": message})


def run_doctor(
    profile: Optional[str] = None,
    allow_protected_file: bool = False,
    offline: bool = False,
) -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []
    _check(checks, "CLI", "ok", f"HiGantic CLI {CLI_VERSION} is running.")

    environment_valid = True
    environment_active = False
    try:
        environment_active, _ = environment_state()
        message = "A complete environment credential override is active." if environment_active else "No environment credential override is active."
        _check(checks, "Environment", "ok", message)
    except AuthError as error:
        environment_valid = False
        _check(checks, "Environment", "error", str(error))

    config = None
    try:
        config = load_config()
        count = len(config["profiles"])
        current = config.get("currentProfile")
        if count:
            current_text = f" Current profile: {current}." if current else " No profile is currently selected."
            _check(checks, "Configuration", "ok", f"Found {count} configured profile(s).{current_text}")
        elif environment_active:
            _check(checks, "Configuration", "ok", "No named profiles are configured; the environment override supplies credentials.")
        else:
            _check(checks, "Configuration", "warning", "No profiles are configured. Run: higantic auth login")
    except AuthError as error:
        _check(checks, "Configuration", "error", str(error))

    credentials = None
    if environment_valid:
        try:
            credentials = resolve_credentials(profile, allow_protected_file)
            source = "environment variables" if credentials["source"] == "environment" else f"profile {credentials['profile']!r}"
            _check(checks, "Credentials", "ok", f"A valid scoped key is available from {source}.")
        except AuthError as error:
            expected = {"profile_not_selected", "profile_not_found"}
            status = "warning" if error.code in expected else "error"
            _check(checks, "Credentials", status, str(error))
    else:
        _check(checks, "Credentials", "skipped", "Fix the environment override before checking credentials.")

    if credentials is None and config is not None and not config["profiles"]:
        try:
            open_store("native", allow_protected_file)
            _check(checks, "Secure storage", "ok", "The native credential-store provider is available.")
        except SecureStoreError as error:
            _check(checks, "Secure storage", "error", str(error))

    if offline:
        _check(checks, "HiGantic API", "skipped", "Remote connectivity was skipped with --offline.")
    elif credentials is None:
        _check(checks, "HiGantic API", "skipped", "Configure valid credentials before checking API connectivity.")
    else:
        try:
            AuthHttpClient(credentials["apiBaseUrl"]).request("GET", "/v1/auth/status", key=credentials["apiKey"])
            _check(checks, "HiGantic API", "ok", "Authentication and API connectivity are working.")
        except AuthError as error:
            _check(checks, "HiGantic API", "error", str(error))

    installer = installer_available()
    _check(
        checks,
        "Skills installer",
        "ok" if installer["available"] else "warning",
        str(installer["message"]),
    )

    if any(item["status"] == "error" for item in checks):
        status = "error"
    elif any(item["status"] == "warning" for item in checks):
        status = "warning"
    else:
        status = "ok"
    return {"version": CLI_VERSION, "status": status, "healthy": status != "error", "checks": checks}
