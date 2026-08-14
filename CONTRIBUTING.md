# Contributing

Thank you for improving HiGantic's public skills.

## Before you start

- Open an issue for substantial behavior or API compatibility changes so the intended contract can be coordinated.
- Do not include secrets, private customer data, internal paths, unpublished vulnerabilities, or private implementation details.
- Keep API keys environment-only and public sharing explicit and opt-in.

## Skill layout

Each skill belongs in `skills/<skill-name>/` and must include a `SKILL.md` file with `name`, `description`, and MIT `license` frontmatter. The name must match the directory. Keep only installable runtime material such as scripts and references in the skill folder. Maintainer-only tests and evals belong in `tests/<skill-name>/` and `evals/<skill-name>/` so they are not included in the installed payload.

Prefer a concise operational `SKILL.md`. Put detailed background, API behavior, and content contracts in `references/` so agents load them only when needed.

## Live-reference convention

Every skill added to `site/v1/manifest.source.json` must include dependency-free `scripts/fetch_live_reference.py`, canonical `references/live-reference.json`, and structured `references/live-reference-fallback.json`; its `SKILL.md` must run/read the locally rendered reference first. The deterministic build publishes `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/<skill-slug>.json`. Alternate origins, userinfo, queries, fragments, cross-origin redirects, agent-consumed remote Markdown, and remote prose or instructions are forbidden.

Remote reference schemas must be exact and closed: schema version, slug, UTC timestamp, supported capability/command identifiers selected from fixed local allowlists, fixed scope identifiers, exact boolean feature fields, and exact nonnegative safe-integer limits. Do not add descriptions, notes, URLs, commands to execute, arbitrary strings, unknown keys, or extensible metadata. Reject duplicate keys, non-ASCII and concealed Unicode, malformed data, and unknown identifiers.

The source/generated manifests and every source/generated reference must fit the fetcher's exact 64 KiB client limits. Fetchers load per-skill installed version and exact URLs from `references/live-reference.json`; never hard-code a repository-wide version in validator logic. Fetchers disable environment proxies, send no credentials or environment-derived headers, perform SHA-256 consistency checking, never print remote bytes, and render through fixed installed text. Network or remote-validation failures render the bundled structured fallback through that same renderer. Installed safety, confirmation, credential, destination, destructive-action, and sharing rules always remain authoritative.

Keep the released source reference and bundled fallback identical. Bump `minimumInstalledVersion` only when state depends on newer installed executable behavior. Maintainer tests belong under `tests/<skill-name>/`, never inside the installable payload.

## Changes

1. Make the smallest change that preserves existing public behavior.
2. Update instructions and references whenever commands, scopes, routes, or compatibility change.
3. Add or update tests for executable behavior.
4. Record user-visible changes in [CHANGELOG.md](CHANGELOG.md).
5. Use repo-relative paths in examples and provenance guidance.
6. Do not claim a package or integration is published unless it is publicly available. Agent skills use `npx skills add`; the standalone CLI uses the `@higantic/cli` npm package after its release gate passes.

## Validation

Run from the repository root:

```bash
node scripts/build-site.mjs
node scripts/test-site.mjs
npm --prefix cli test
npm pack ./cli --dry-run
python3 -m unittest discover -s tests/higantic-html-artifacts -p 'test_*.py'
python3 -m unittest discover -s tests/cli -p 'test_*.py'
python3 -m py_compile cli/higantic_cli/*.py skills/higantic-html-artifacts/scripts/*.py scripts/validate_repository.py tests/cli/*.py tests/higantic-html-artifacts/*.py
python3 -m json.tool site/v1/manifest.source.json >/dev/null
python3 -m json.tool site/v1/references/higantic-html-artifacts.json >/dev/null
python3 -m json.tool skills/higantic-html-artifacts/references/live-reference.json >/dev/null
python3 -m json.tool skills/higantic-html-artifacts/references/live-reference-fallback.json >/dev/null
python3 -m json.tool dist/v1/manifest.json >/dev/null
python3 -m json.tool dist/v1/references/higantic-html-artifacts.json >/dev/null
python3 scripts/validate_repository.py
```

All checks must pass on Python 3.9 and the current Python release before a release is considered ready.

## Security reports

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md).

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
