#!/usr/bin/env python3
"""Consent-driven installer for optional public HiGantic skills."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


SKILL_REPOSITORY = "Aneaire/higantic-skills"
SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INSTALL_TIMEOUT_SECONDS = 300
INSTALLER_MESSAGE_LIMIT = 240
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_STYLES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "amber": "33", "cyan": "36"}
SENSITIVE_CHILD_ENVIRONMENT = {
    "HIGANTIC_AGENT_ID",
    "HIGANTIC_API_BASE_URL",
    "HIGANTIC_API_KEY",
    "HIGANTIC_ALLOW_CUSTOM_API_BASE_URL",
    "HIGANTIC_ALLOW_INSECURE_LOCALHOST",
}

# This installed catalog is deliberately local and reviewed with each release.
# Add a public skill here only when the same slug exists in skills.sh.json.
SKILL_CATALOG = (
    {
        "slug": "higantic-html-artifacts",
        "name": "HTML Artifacts",
        "description": "Create and maintain safe, versioned HTML artifacts in HiGantic.",
    },
    {
        "slug": "higantic-assets",
        "name": "Managed Assets",
        "description": "Upload, organize, and deliberately share managed images in HiGantic.",
    },
    {
        "slug": "higantic-excalidraw",
        "name": "Excalidraw Canvas",
        "description": "Create and maintain editable Excalidraw Canvas diagrams in HiGantic.",
    },
)


class SkillInstallError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.status = 0
        self.details = None


def _catalog(selected: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    seen = set()
    for raw in SKILL_CATALOG:
        if set(raw) != {"slug", "name", "description"} or any(not isinstance(value, str) for value in raw.values()):
            raise SkillInstallError("invalid_skill_catalog", "The installed HiGantic skill catalog is invalid.")
        entry = dict(raw)
        slug = entry["slug"]
        if (
            not SKILL_SLUG_PATTERN.fullmatch(slug)
            or slug in seen
            or not entry["name"].strip()
            or not entry["description"].strip()
            or any(ord(character) < 32 for value in entry.values() for character in value)
        ):
            raise SkillInstallError("invalid_skill_catalog", "The installed HiGantic skill catalog is invalid.")
        seen.add(slug)
        entries.append(entry)
    if not entries:
        raise SkillInstallError("invalid_skill_catalog", "The installed HiGantic skill catalog is empty.")
    requested = list(dict.fromkeys(selected or []))
    unknown = [slug for slug in requested if slug not in seen]
    if unknown:
        raise SkillInstallError("unknown_skill", f"Unknown HiGantic skill: {unknown[0]}")
    return entries if not requested else [entry for entry in entries if entry["slug"] in requested]


def _skill_is_installed(slug: str) -> bool:
    current_skill = Path(__file__).resolve().parent.parent
    if current_skill.name == slug and (current_skill / "SKILL.md").is_file():
        return True
    return (Path.home() / ".agents" / "skills" / slug / "SKILL.md").is_file()


def missing_skills(selected: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
    return [entry for entry in _catalog(selected) if not _skill_is_installed(entry["slug"])]


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()


def _color_enabled(stream) -> bool:
    return (
        os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM", "").lower() != "dumb"
        and bool(getattr(stream, "isatty", lambda: False)())
    )


def _paint(value: str, *styles: str, stream=None) -> str:
    target = sys.stderr if stream is None else stream
    if not styles or not _color_enabled(target):
        return value
    codes = ";".join(ANSI_STYLES[style] for style in styles)
    return f"\033[{codes}m{value}\033[0m"


def _glyph(value: str, fallback: str, stream=None) -> str:
    target = sys.stderr if stream is None else stream
    encoding = getattr(target, "encoding", None) or "utf-8"
    try:
        value.encode(encoding)
        return value
    except (LookupError, UnicodeEncodeError):
        return fallback


def _ask_yes_no(question: str) -> bool:
    print(question, end=" ", file=sys.stderr, flush=True)
    answer = sys.stdin.readline()
    if answer == "":
        return False
    return answer.strip().lower() in {"", "y", "yes"}


def _npx_executable() -> str:
    candidates = ("npx.cmd", "npx.exe", "npx") if os.name == "nt" else ("npx",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise SkillInstallError(
        "skills_installer_unavailable",
        "Node.js with npx is required to install HiGantic skills.",
    )


def _child_environment() -> Dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in SENSITIVE_CHILD_ENVIRONMENT}


def installer_available() -> Dict[str, Any]:
    try:
        _npx_executable()
        return {"available": True, "message": "Node.js and npx are available."}
    except SkillInstallError as error:
        return {"available": False, "message": str(error)}


def _installer_failure_message(completed: subprocess.CompletedProcess) -> str:
    output = completed.stderr or completed.stdout or ""
    lines = []
    for raw in output.splitlines():
        cleaned = ANSI_ESCAPE_PATTERN.sub("", raw)
        cleaned = "".join(character if not unicodedata.category(character).startswith("C") else " " for character in cleaned)
        cleaned = " ".join(cleaned.split())
        if cleaned:
            lines.append(cleaned)
    if not lines:
        return "No additional details were returned."
    message = lines[-1]
    return message if len(message) <= INSTALLER_MESSAGE_LIMIT else message[: INSTALLER_MESSAGE_LIMIT - 1] + "…"


def _install(entry: Dict[str, str]) -> None:
    command = [
        _npx_executable(),
        "--yes",
        "skills",
        "add",
        SKILL_REPOSITORY,
        "--skill",
        entry["slug"],
        "--global",
        "--agent",
        "*",
        "--yes",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
            env=_child_environment(),
        )
    except subprocess.TimeoutExpired:
        raise SkillInstallError("skill_install_timeout", f"Installation timed out for {entry['name']}.") from None
    except OSError as error:
        raise SkillInstallError("skill_install_failed", f"Could not start the skills installer: {error}") from None
    if completed.returncode != 0:
        reason = _installer_failure_message(completed)
        raise SkillInstallError(
            "skill_install_failed",
            f"The skills installer exited with code {completed.returncode} while installing {entry['name']}. {reason}",
        )


def install_skills(selected: Optional[Sequence[str]] = None, assume_yes: bool = False) -> Dict[str, Any]:
    entries = _catalog(selected)
    installed = [entry["slug"] for entry in entries if _skill_is_installed(entry["slug"])]
    pending = [entry for entry in entries if entry["slug"] not in installed]
    result: Dict[str, Any] = {
        "scope": "global",
        "installed": [],
        "alreadyInstalled": installed,
        "declined": [],
        "failed": [],
    }
    if not pending:
        return result
    if not assume_yes and not _interactive_terminal():
        raise SkillInstallError(
            "interactive_required",
            "Run this command in an interactive terminal or pass --yes to install every missing offered skill.",
        )
    for index, entry in enumerate(pending, start=1):
        step = _paint(f"{index:02d}/{len(pending):02d}", "cyan", "bold", stream=sys.stderr)
        print(f"\n{step}  {_paint(entry['name'], 'bold', stream=sys.stderr)}", file=sys.stderr)
        print(f"       {_paint(entry['description'], 'dim', stream=sys.stderr)}", file=sys.stderr)
        if not assume_yes:
            if not _ask_yes_no("       Install globally? [Y/n]"):
                result["declined"].append(entry["slug"])
                print(f"       {_paint(_glyph('—', '-', sys.stderr) + ' Skipped', 'amber', stream=sys.stderr)}", file=sys.stderr)
                continue
        try:
            _install(entry)
            result["installed"].append(entry["slug"])
            print(f"       {_paint(_glyph('✓', 'OK', sys.stderr) + ' Installed globally', 'green', 'bold', stream=sys.stderr)}", file=sys.stderr)
        except SkillInstallError as error:
            result["failed"].append({"slug": entry["slug"], "code": error.code, "message": str(error)})
            print(f"       {_paint(_glyph('✕', 'X', sys.stderr) + ' Installation failed', 'red', 'bold', stream=sys.stderr)}", file=sys.stderr)
            print(f"       {_paint(str(error), 'dim', stream=sys.stderr)}", file=sys.stderr)
    return result


def format_install_result(result: Dict[str, Any]) -> str:
    names = {entry["slug"]: entry["name"] for entry in _catalog()}

    def display_name(slug: str) -> str:
        return names.get(slug, slug)

    installed = [display_name(slug) for slug in result.get("installed", [])]
    already_installed = [display_name(slug) for slug in result.get("alreadyInstalled", [])]
    declined = [display_name(slug) for slug in result.get("declined", [])]
    failed = result.get("failed", [])

    rail = _paint(_glyph("│", "|", sys.stdout), "cyan", stream=sys.stdout)
    title = "Skill setup finished with issues" if failed else "Skill setup complete"
    lines = [_paint(f"{_glyph('╭─', '+-', sys.stdout)} {title}", "cyan", "bold", stream=sys.stdout)]
    if installed:
        lines.append(f"{rail}  {_paint(_glyph('✓', 'OK', sys.stdout), 'green', 'bold', stream=sys.stdout)} {_paint('Installed', 'dim', stream=sys.stdout)}  {', '.join(installed)}")
    if already_installed:
        lines.append(f"{rail}  {_paint(_glyph('•', '*', sys.stdout), 'cyan', stream=sys.stdout)} {_paint('Ready', 'dim', stream=sys.stdout)}      {', '.join(already_installed)}")
    if declined:
        lines.append(f"{rail}  {_paint(_glyph('—', '-', sys.stdout), 'amber', stream=sys.stdout)} {_paint('Skipped', 'dim', stream=sys.stdout)}    {', '.join(declined)}")
    if failed:
        failures = []
        for item in failed:
            slug = item.get("slug", "unknown") if isinstance(item, dict) else str(item)
            code = item.get("code") if isinstance(item, dict) else None
            message = item.get("message") if isinstance(item, dict) else None
            label = display_name(slug)
            if isinstance(message, str) and message:
                failures.append(f"{label} — {message}")
            else:
                failures.append(f"{label} ({code})" if code else label)
        lines.append(f"{rail}  {_paint(_glyph('✕', 'X', sys.stdout), 'red', 'bold', stream=sys.stdout)} {_paint('Failed', 'dim', stream=sys.stdout)}     {', '.join(failures)}")
    if len(lines) == 1:
        lines.append(f"{rail}  {_paint(_glyph('✓', 'OK', sys.stdout), 'green', 'bold', stream=sys.stdout)} All selected skills are ready")
    lines.append(_paint(_glyph("╰────────────────────────", "+------------------------", sys.stdout), "cyan", stream=sys.stdout))
    return "\n".join(lines)


def offer_skills_after_login(disabled: bool = False) -> Optional[Dict[str, Any]]:
    if disabled or not _interactive_terminal() or not missing_skills():
        return None
    return install_skills()
