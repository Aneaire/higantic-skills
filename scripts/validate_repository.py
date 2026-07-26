#!/usr/bin/env python3
"""Validate the public skills repository without third-party dependencies."""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path
from unittest import mock
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SOURCE_MANIFEST = ROOT / "site" / "v1" / "manifest.source.json"
PUBLIC_ORIGIN = "https://skills.higantic.com"
MANIFEST_URL = f"{PUBLIC_ORIGIN}/v1/manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_REFERENCE_BYTES = 64 * 1024
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
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
TEXT_SUFFIXES = {".html", ".js", ".json", ".md", ".mjs", ".py", ".txt", ".yaml", ".yml"}
ALLOWED_SKILL_ENTRIES = {"SKILL.md", "README.md", "scripts", "references"}


class DuplicateKeyError(ValueError):
    pass


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate key {key!r}")
        value[key] = item
    return value


def parse_strict_json(raw: bytes, label: str, *, ascii_only: bool = False) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} is not UTF-8") from error
    if ascii_only and any(ord(character) > 0x7F for character in text):
        raise ValueError(f"{label} must contain ASCII JSON only")
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, DuplicateKeyError) as error:
        raise ValueError(f"{label} is malformed: {error}") from error


def read_json(path: Path, errors: List[str], label: str, *, ascii_only: bool = False) -> Optional[Any]:
    try:
        return parse_strict_json(path.read_bytes(), label, ascii_only=ascii_only)
    except (OSError, ValueError) as error:
        errors.append(str(error))
        return None


def validate_bounded_file(path: Path, maximum: int, errors: List[str], label: str) -> Optional[bytes]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        errors.append(f"{label}: {error}")
        return None
    if len(raw) > maximum:
        errors.append(f"{label}: exceeds {maximum} bytes")
    return raw


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


def parse_semver(value: Any) -> Optional[Tuple[int, int, int]]:
    if not isinstance(value, str) or SEMVER_PATTERN.fullmatch(value) is None:
        return None
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or TIMESTAMP_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def validate_skills(errors: List[str]) -> Set[str]:
    slugs: Set[str] = set()
    if not SKILLS_DIR.is_dir():
        errors.append("missing skills directory")
        return slugs
    for directory in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir() and path.name != "__pycache__"):
        slugs.add(directory.name)
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{skill_file.relative_to(ROOT)}: missing SKILL.md")
            continue
        metadata = frontmatter(skill_file)
        if metadata.get("name") != directory.name:
            errors.append(f"{skill_file.relative_to(ROOT)}: frontmatter name must match the directory")
        if not metadata.get("description"):
            errors.append(f"{skill_file.relative_to(ROOT)}: missing frontmatter description")
        if metadata.get("license") != "MIT":
            errors.append(f"{skill_file.relative_to(ROOT)}: frontmatter license must be MIT")
        for entry in directory.iterdir():
            if entry.name != "__pycache__" and entry.name not in ALLOWED_SKILL_ENTRIES:
                errors.append(f"{entry.relative_to(ROOT)}: installable skill payload entry is not allowed")
        for required in (directory / "README.md", directory / "scripts", directory / "references"):
            if not required.exists():
                errors.append(f"{required.relative_to(ROOT)}: missing required installable payload entry")
        for nested in directory.rglob("*"):
            if "__pycache__" in nested.parts or nested.suffix in (".pyc", ".pyo"):
                continue
            if nested.is_symlink():
                errors.append(f"{nested.relative_to(ROOT)}: symlinks are not allowed in an installable skill")
            if nested.is_dir() and nested.name.lower() in ("tests", "evals"):
                errors.append(f"{nested.relative_to(ROOT)}: maintainer-only directory must not be installed")
    return slugs


def validate_skills_manifest(errors: List[str]) -> Set[str]:
    manifest = read_json(ROOT / "skills.sh.json", errors, "skills.sh.json")
    seen: Set[str] = set()
    if not isinstance(manifest, dict):
        return seen
    if manifest.get("$schema") != "https://skills.sh/schemas/skills.sh.schema.json":
        errors.append("skills.sh.json: invalid $schema")
    groupings = manifest.get("groupings")
    if not isinstance(groupings, list) or not groupings:
        errors.append("skills.sh.json: groupings must be a non-empty array")
        return seen
    for grouping in groupings:
        if not isinstance(grouping, dict) or not isinstance(grouping.get("skills"), list):
            errors.append("skills.sh.json: each grouping must contain a skills array")
            continue
        for slug in grouping["skills"]:
            if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
                errors.append(f"skills.sh.json: invalid slug {slug!r}")
            elif slug in seen:
                errors.append(f"skills.sh.json: duplicate slug {slug!r}")
            else:
                seen.add(slug)
    return seen


def validate_source_manifest(errors: List[str]) -> Tuple[Set[str], Dict[str, Dict[str, Any]], Optional[Dict[str, Any]]]:
    raw = validate_bounded_file(SOURCE_MANIFEST, MAX_MANIFEST_BYTES, errors, "site/v1/manifest.source.json")
    if raw is None:
        return set(), {}, None
    try:
        manifest = parse_strict_json(raw, "site/v1/manifest.source.json", ascii_only=True)
    except ValueError as error:
        errors.append(str(error))
        return set(), {}, None
    if not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "updatedAt", "references"}:
        errors.append("site/v1/manifest.source.json: invalid exact schema")
        return set(), {}, manifest if isinstance(manifest, dict) else None
    if manifest["schemaVersion"] != 1 or isinstance(manifest["schemaVersion"], bool):
        errors.append("site/v1/manifest.source.json: schemaVersion must be 1")
    if not valid_timestamp(manifest["updatedAt"]):
        errors.append("site/v1/manifest.source.json: updatedAt is invalid")
    references = manifest["references"]
    if not isinstance(references, list) or not references:
        errors.append("site/v1/manifest.source.json: references must be a non-empty array")
        return set(), {}, manifest
    slugs: Set[str] = set()
    entries: Dict[str, Dict[str, Any]] = {}
    for index, entry in enumerate(references):
        label = f"site/v1/manifest.source.json: reference {index}"
        if not isinstance(entry, dict) or set(entry) != {"slug", "path", "minimumInstalledVersion"}:
            errors.append(f"{label} has invalid exact fields")
            continue
        slug = entry["slug"]
        if not isinstance(slug, str) or SLUG_PATTERN.fullmatch(slug) is None:
            errors.append(f"{label} has an invalid slug")
            continue
        if slug in slugs:
            errors.append(f"{label} duplicates slug {slug!r}")
        slugs.add(slug)
        entries[slug] = entry
        if entry["path"] != f"references/{slug}.json":
            errors.append(f"{label} path must be references/{slug}.json")
        if parse_semver(entry["minimumInstalledVersion"]) is None:
            errors.append(f"{label} minimumInstalledVersion must be semantic x.y.z")
        reference_path = ROOT / "site" / "v1" / str(entry["path"])
        validate_bounded_file(reference_path, MAX_REFERENCE_BYTES, errors, str(reference_path.relative_to(ROOT)))
        if reference_path.is_symlink():
            errors.append(f"{reference_path.relative_to(ROOT)}: source reference must not be a symlink")
    return slugs, entries, manifest


def load_fetcher(path: Path, slug: str, errors: List[str]):
    try:
        spec = importlib.util.spec_from_file_location(f"live_reference_{slug.replace('-', '_')}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not create import specification")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as error:
        errors.append(f"{path.relative_to(ROOT)}: could not import fetcher: {error}")
        return None


def compare_installed_config(errors: List[str], slug: str, source_entry: Dict[str, Any], config: Dict[str, Any], label: str) -> None:
    expected_url = f"{PUBLIC_ORIGIN}/v1/references/{slug}.json"
    if set(config) != {"schemaVersion", "slug", "installedVersion", "manifestUrl", "referenceUrl"}:
        errors.append(f"{label}: invalid exact schema")
        return
    if config.get("schemaVersion") != 1 or isinstance(config.get("schemaVersion"), bool):
        errors.append(f"{label}: schemaVersion must be 1")
    if config.get("slug") != slug:
        errors.append(f"{label}: slug must match the skill directory")
    installed = parse_semver(config.get("installedVersion"))
    minimum = parse_semver(source_entry.get("minimumInstalledVersion"))
    if installed is None:
        errors.append(f"{label}: installedVersion must be semantic x.y.z")
    elif minimum is not None and installed < minimum:
        errors.append(f"{label}: installedVersion is lower than the source manifest minimum")
    if config.get("manifestUrl") != MANIFEST_URL:
        errors.append(f"{label}: manifestUrl must be {MANIFEST_URL}")
    if config.get("referenceUrl") != expected_url:
        errors.append(f"{label}: referenceUrl must be {expected_url}")


def validate_live_reference_skill(errors: List[str], slug: str, source_entry: Dict[str, Any]) -> Tuple[Any, Optional[Dict[str, Any]]]:
    directory = SKILLS_DIR / slug
    fetcher_path = directory / "scripts" / "fetch_live_reference.py"
    fallback_path = directory / "references" / "live-reference-fallback.json"
    config_path = directory / "references" / "live-reference.json"
    skill_path = directory / "SKILL.md"
    readme_path = directory / "README.md"
    for required in (fetcher_path, fallback_path, config_path, skill_path, readme_path):
        if not required.is_file():
            errors.append(f"{required.relative_to(ROOT)}: required live-reference package file is missing")
    if not fetcher_path.is_file() or not config_path.is_file():
        return None, None
    module = load_fetcher(fetcher_path, slug, errors)
    if module is None:
        return None, None
    try:
        config = module.load_installed_config(config_path)
    except Exception as error:
        errors.append(f"{config_path.relative_to(ROOT)}: fetcher rejected installed config: {error}")
        config = read_json(config_path, errors, str(config_path.relative_to(ROOT)), ascii_only=True)
    if isinstance(config, dict):
        compare_installed_config(errors, slug, source_entry, config, str(config_path.relative_to(ROOT)))
    else:
        config = None

    if getattr(module, "MAX_MANIFEST_BYTES", None) != MAX_MANIFEST_BYTES:
        errors.append(f"{fetcher_path.relative_to(ROOT)}: manifest size limit must be {MAX_MANIFEST_BYTES}")
    if getattr(module, "MAX_REFERENCE_BYTES", None) != MAX_REFERENCE_BYTES:
        errors.append(f"{fetcher_path.relative_to(ROOT)}: reference size limit must be {MAX_REFERENCE_BYTES}")
    if getattr(module, "EXPECTED_SLUG", None) != slug:
        errors.append(f"{fetcher_path.relative_to(ROOT)}: fetcher must derive the current skill slug")
    if hasattr(module, "INSTALLED_VERSION"):
        errors.append(f"{fetcher_path.relative_to(ROOT)}: installed version must come only from live-reference.json")
    try:
        with mock.patch.object(
            module.urllib.request,
            "getproxies",
            side_effect=RuntimeError("environment proxy lookup attempted"),
        ):
            opener = module.build_opener()
        sensitive = {name.lower() for name, _value in opener.addheaders} & {"authorization", "cookie", "proxy-authorization"}
        if sensitive:
            errors.append(f"{fetcher_path.relative_to(ROOT)}: fetcher opener contains credential-bearing headers")
        if not any(isinstance(handler, module.SameOriginRedirectHandler) for handler in opener.handlers):
            errors.append(f"{fetcher_path.relative_to(ROOT)}: same-origin redirect handler is missing")
    except Exception as error:
        errors.append(f"{fetcher_path.relative_to(ROOT)}: could not verify opener behavior: {error}")

    source_path = ROOT / "site" / "v1" / str(source_entry.get("path", ""))
    source_raw = validate_bounded_file(source_path, MAX_REFERENCE_BYTES, errors, str(source_path.relative_to(ROOT)))
    if source_raw is not None:
        try:
            module.validate_reference_data(source_raw, slug)
        except Exception as error:
            errors.append(f"{source_path.relative_to(ROOT)}: fetcher rejected source reference: {error}")
    fallback_raw = validate_bounded_file(fallback_path, MAX_REFERENCE_BYTES, errors, str(fallback_path.relative_to(ROOT))) if fallback_path.is_file() else None
    if fallback_raw is not None:
        try:
            fallback = module.validate_reference_data(fallback_raw, slug)
            rendered = module.render_reference(fallback)
            if not isinstance(rendered, str) or not rendered.strip() or rendered.lstrip().startswith("{"):
                errors.append(f"{fetcher_path.relative_to(ROOT)}: renderer must emit fixed local text, not raw JSON")
        except Exception as error:
            errors.append(f"{fallback_path.relative_to(ROOT)}: fetcher rejected fallback: {error}")
        if source_raw is not None and fallback_raw != source_raw:
            errors.append(f"{fallback_path.relative_to(ROOT)}: bundled fallback must match the released source reference")

    if skill_path.is_file():
        skill_text = skill_path.read_text(encoding="utf-8")
        command_index = skill_text.find("python3 scripts/fetch_live_reference.py")
        contract_index = skill_text.find("references/static-html-contract.md")
        if command_index < 0 or contract_index < 0 or command_index > contract_index:
            errors.append(f"{skill_path.relative_to(ROOT)}: must run/read the live reference first")
        for phrase in ("structured", "local", "bundled fallback"):
            if phrase not in skill_text.lower():
                errors.append(f"{skill_path.relative_to(ROOT)}: missing live-reference safeguard term {phrase!r}")
    combined_docs = ""
    for path in (skill_path, readme_path):
        if path.is_file():
            combined_docs += path.read_text(encoding="utf-8")
    expected_url = f"{PUBLIC_ORIGIN}/v1/references/{slug}.json"
    if MANIFEST_URL not in combined_docs or expected_url not in combined_docs:
        errors.append(f"{directory.relative_to(ROOT)}: documentation must include both exact branded URLs")
    return module, config


def validate_generated_output(
    errors: List[str],
    source_entries: Dict[str, Dict[str, Any]],
    source_manifest: Optional[Dict[str, Any]],
    runtimes: Dict[str, Tuple[Any, Optional[Dict[str, Any]]]],
) -> None:
    manifest_path = ROOT / "dist" / "v1" / "manifest.json"
    if not manifest_path.exists():
        return
    raw = validate_bounded_file(manifest_path, MAX_MANIFEST_BYTES, errors, "dist/v1/manifest.json")
    if raw is None:
        return
    try:
        manifest = parse_strict_json(raw, "dist/v1/manifest.json", ascii_only=True)
    except ValueError as error:
        errors.append(str(error))
        return
    if not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "updatedAt", "references"}:
        errors.append("dist/v1/manifest.json: invalid exact schema")
        return
    if manifest.get("schemaVersion") != 1 or not valid_timestamp(manifest.get("updatedAt")):
        errors.append("dist/v1/manifest.json: invalid schema version or timestamp")
    if source_manifest is not None and manifest.get("updatedAt") != source_manifest.get("updatedAt"):
        errors.append("dist/v1/manifest.json: updatedAt differs from source manifest")
    references = manifest.get("references")
    if not isinstance(references, list) or len(references) != len(source_entries):
        errors.append("dist/v1/manifest.json: generated reference set differs from source")
        return
    seen = set()
    for entry in references:
        if not isinstance(entry, dict) or set(entry) != {"slug", "referenceUrl", "sha256", "minimumInstalledVersion"}:
            errors.append("dist/v1/manifest.json: invalid generated reference entry")
            continue
        slug = entry.get("slug")
        if slug not in source_entries or slug in seen:
            errors.append(f"dist/v1/manifest.json: invalid or duplicate slug {slug!r}")
            continue
        seen.add(slug)
        expected_url = f"{PUBLIC_ORIGIN}/v1/references/{slug}.json"
        if entry.get("referenceUrl") != expected_url:
            errors.append(f"dist/v1/manifest.json: referenceUrl must be {expected_url}")
        parsed = urlsplit(str(entry.get("referenceUrl", "")))
        if parsed.scheme != "https" or parsed.netloc != "skills.higantic.com" or parsed.query or parsed.fragment or parsed.username is not None:
            errors.append(f"dist/v1/manifest.json: dangerous reference URL for {slug}")
        if not isinstance(entry.get("sha256"), str) or SHA256_PATTERN.fullmatch(entry["sha256"]) is None:
            errors.append(f"dist/v1/manifest.json: invalid SHA-256 for {slug}")
            continue
        generated_path = ROOT / "dist" / "v1" / "references" / f"{slug}.json"
        generated_raw = validate_bounded_file(generated_path, MAX_REFERENCE_BYTES, errors, str(generated_path.relative_to(ROOT)))
        source_path = ROOT / "site" / "v1" / source_entries[slug]["path"]
        if generated_raw is not None:
            if hashlib.sha256(generated_raw).hexdigest() != entry["sha256"]:
                errors.append(f"dist/v1/manifest.json: SHA-256 consistency failure for {slug}")
            if source_path.is_file() and generated_raw != source_path.read_bytes():
                errors.append(f"{generated_path.relative_to(ROOT)}: generated reference differs from source")
        if entry.get("minimumInstalledVersion") != source_entries[slug].get("minimumInstalledVersion"):
            errors.append(f"dist/v1/manifest.json: minimum version differs from source for {slug}")
        module, config = runtimes.get(slug, (None, None))
        if module is not None and isinstance(config, dict):
            try:
                module.validate_manifest(raw, config)
                if generated_raw is not None:
                    module.validate_reference_data(generated_raw, slug)
            except Exception as error:
                errors.append(f"dist live-reference behavior validation failed for {slug}: {error}")


def validate_site_package(errors: List[str]) -> None:
    package = read_json(ROOT / "package.json", errors, "package.json")
    if isinstance(package, dict):
        if package.get("private") is not True:
            errors.append("package.json: package must be private")
        if "dependencies" in package:
            errors.append("package.json: runtime dependencies are not allowed")
        scripts = package.get("scripts")
        if not isinstance(scripts, dict) or scripts.get("build") != "node scripts/build-site.mjs" or "validate" not in scripts:
            errors.append("package.json: exact build and validation scripts are required")
    for path in (
        ROOT / "scripts" / "build-site.mjs",
        ROOT / "scripts" / "live-reference-schema.mjs",
        ROOT / "scripts" / "test-site.mjs",
        ROOT / "site" / "index.html",
        ROOT / "vercel.json",
    ):
        if not path.is_file():
            errors.append(f"{path.relative_to(ROOT)}: required site file is missing")
    forbidden_site = list((ROOT / "site" / "v1").rglob("*.md")) if (ROOT / "site" / "v1").exists() else []
    for path in forbidden_site:
        errors.append(f"{path.relative_to(ROOT)}: agent-consumed mutable Markdown is forbidden")

    vercel = read_json(ROOT / "vercel.json", errors, "vercel.json")
    if isinstance(vercel, dict):
        if vercel.get("buildCommand") != "node scripts/build-site.mjs" or vercel.get("outputDirectory") != "dist":
            errors.append("vercel.json: invalid buildCommand/outputDirectory")
        serialized = json.dumps(vercel, sort_keys=True)
        for required in (
            "application/json; charset=utf-8",
            "public, max-age=300, s-maxage=300, stale-while-revalidate=3600",
            "X-Content-Type-Options",
            "Access-Control-Allow-Origin",
            "Content-Security-Policy",
            "/v1/references/(.*)",
        ):
            if required not in serialized:
                errors.append(f"vercel.json: missing required value {required!r}")
        obsolete_route = "/v1/" + "guides/"
        obsolete_type = "text/" + "markdown"
        if "Access-Control-Allow-Credentials" in serialized or obsolete_route in serialized or obsolete_type in serialized:
            errors.append("vercel.json: unsafe credentials or obsolete free-form reference route")


def repository_files():
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in (".git", "__pycache__") for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in (".pyc", ".pyo"):
            yield path


def validate_links(errors: List[str]) -> None:
    for path in repository_files():
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if relative and not (path.parent / relative).resolve().exists():
                errors.append(f"{path.relative_to(ROOT)}: broken relative link {target!r}")


def validate_public_content(errors: List[str]) -> None:
    obsolete = (
        "fetch_live_" + "guide",
        "live-" + "guide-fallback",
        "/v1/" + "guides/",
        "authenticated-" + "by-hash",
    )
    for path in repository_files():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment.lower() in text.lower():
                errors.append(f"{path.relative_to(ROOT)}: forbidden private path fragment {fragment!r}")
        for fragment in obsolete:
            if fragment.lower() in text.lower():
                errors.append(f"{path.relative_to(ROOT)}: obsolete free-form reference fragment {fragment!r}")
        lowered = text.lower()
        forbidden_hash_claims = (
            "hash " + "authenticates",
            "hash " + "authenticate",
            "sha-256 " + "authentic",
        )
        if any(claim in lowered for claim in forbidden_hash_claims):
            errors.append(f"{path.relative_to(ROOT)}: hash must be described only as consistency/integrity checking")
        for pattern in CREDENTIAL_PATTERNS:
            for match in pattern.finditer(text):
                token = match.group(0)
                if not any(marker in token.lower() for marker in FIXTURE_MARKERS):
                    errors.append(f"{path.relative_to(ROOT)}: possible credential with prefix {token.split('_', 1)[0]!r}")


def main() -> int:
    errors: List[str] = []
    directory_slugs = validate_skills(errors)
    skills_manifest_slugs = validate_skills_manifest(errors)
    live_slugs, source_entries, source_manifest = validate_source_manifest(errors)
    if directory_slugs != skills_manifest_slugs:
        errors.append("skills.sh.json skill set must exactly match skills/ directories")
    if live_slugs != skills_manifest_slugs:
        errors.append("source live-reference set must exactly match skills.sh.json")
    validate_site_package(errors)
    runtimes = {}
    for slug in sorted(live_slugs):
        runtimes[slug] = validate_live_reference_skill(errors, slug, source_entries[slug])
    validate_generated_output(errors, source_entries, source_manifest, runtimes)
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
