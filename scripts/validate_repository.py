#!/usr/bin/env python3
"""Validate the public skills repository without third-party dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FORBIDDEN_FRAGMENTS = (
    "/" + "home/",
    "/" + "Users" + "/",
    "C:" + "\\Users\\",
    "/private/" + "var/",
    "/mnt/" + "c/" + "Users/",
    "Desktop/" + "Projects/",
    "HiGantic/" + ".agents/",
    ".agents/" + "skills/higantic-html-artifacts",
    ".claude/" + "projects/",
)
CREDENTIAL_PATTERNS = (
    re.compile(r"\bhgk_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhgs_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk_(?:live|prod)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
FIXTURE_MARKERS = ("test", "example", "dummy", "fake", "fixture", "redacted", "placeholder", "never_echo")
TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".txt"}


def frontmatter(path: Path) -> Dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip('"\'')
    return {}


def validate_skills(errors: List[str]) -> None:
    if not SKILLS_DIR.is_dir():
        errors.append("missing skills directory")
        return
    for directory in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{skill_file.relative_to(ROOT)}: missing SKILL.md")
            continue
        metadata = frontmatter(skill_file)
        if not metadata.get("name"):
            errors.append(f"{skill_file.relative_to(ROOT)}: missing frontmatter name")
        elif metadata["name"] != directory.name:
            errors.append(f"{skill_file.relative_to(ROOT)}: name must match directory {directory.name!r}")
        if not metadata.get("description"):
            errors.append(f"{skill_file.relative_to(ROOT)}: missing frontmatter description")
        if metadata.get("license") != "MIT":
            errors.append(f"{skill_file.relative_to(ROOT)}: frontmatter license must be MIT")
        for nested in directory.rglob("*"):
            if nested.is_dir() and nested.name.lower() in ("tests", "evals"):
                errors.append(f"{nested.relative_to(ROOT)}: maintainer-only directory must not be inside an installable skill")


def validate_manifest(errors: List[str]) -> None:
    path = ROOT / "skills.sh.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"skills.sh.json: {error}")
        return
    if manifest.get("$schema") != "https://skills.sh/schemas/skills.sh.schema.json":
        errors.append("skills.sh.json: $schema must use the official skills.sh schema URL")
    if "notGrouped" in manifest and manifest["notGrouped"] not in ("top", "bottom"):
        errors.append("skills.sh.json: notGrouped must be 'top' or 'bottom'")
    groupings = manifest.get("groupings")
    if not isinstance(groupings, list) or not groupings:
        errors.append("skills.sh.json: groupings must be a non-empty array")
        return
    seen = set()
    slug_pattern = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    for index, grouping in enumerate(groupings):
        if not isinstance(grouping, dict):
            errors.append(f"skills.sh.json: grouping {index} must be an object")
            continue
        title = grouping.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"skills.sh.json: grouping {index} needs a non-empty title")
        description = grouping.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"skills.sh.json: grouping {index} description must be a string")
        entries = grouping.get("skills")
        if not isinstance(entries, list) or not entries:
            errors.append(f"skills.sh.json: grouping {title!r} needs skill entries")
            continue
        for slug in entries:
            if not isinstance(slug, str) or not slug_pattern.fullmatch(slug):
                errors.append(f"skills.sh.json: invalid skill slug {slug!r}")
                continue
            if slug in seen:
                errors.append(f"skills.sh.json: duplicate skill slug {slug!r}")
            seen.add(slug)
            if not (SKILLS_DIR / slug / "SKILL.md").is_file():
                errors.append(f"skills.sh.json: skill slug does not resolve to skills/{slug}/SKILL.md")


def validate_links(errors: List[str]) -> None:
    for path in ROOT.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if relative and not (path.parent / relative).resolve().exists():
                errors.append(f"{path.relative_to(ROOT)}: broken relative link {target!r}")


def validate_public_content(errors: List[str]) -> None:
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment.lower() in text.lower():
                errors.append(f"{path.relative_to(ROOT)}: forbidden private workspace path fragment {fragment!r}")
        for pattern in CREDENTIAL_PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                if not any(marker in token.lower() for marker in FIXTURE_MARKERS):
                    errors.append(f"{path.relative_to(ROOT)}: possible credential with prefix {token.split('_', 1)[0]!r}")


def main() -> int:
    errors: List[str] = []
    validate_skills(errors)
    validate_manifest(errors)
    validate_links(errors)
    validate_public_content(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
