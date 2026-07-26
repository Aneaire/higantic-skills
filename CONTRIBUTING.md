# Contributing

Thank you for improving HiGantic's public skills.

## Before you start

- Open an issue for substantial behavior or API compatibility changes so the intended contract can be coordinated.
- Do not include secrets, private customer data, internal paths, unpublished vulnerabilities, or private implementation details.
- Keep API keys environment-only and public sharing explicit and opt-in.

## Skill layout

Each skill belongs in `skills/<skill-name>/` and must include a `SKILL.md` file with `name`, `description`, and MIT `license` frontmatter. The name must match the directory. Keep only installable runtime material such as scripts and references in the skill folder. Maintainer-only tests and evals belong in `tests/<skill-name>/` and `evals/<skill-name>/` so they are not included in the installed payload.

Prefer a concise operational `SKILL.md`. Put detailed background, API behavior, and content contracts in `references/` so agents load them only when needed.

## Changes

1. Make the smallest change that preserves existing public behavior.
2. Update instructions and references whenever commands, scopes, routes, or compatibility change.
3. Add or update tests for executable behavior.
4. Record user-visible changes in [CHANGELOG.md](CHANGELOG.md).
5. Use repo-relative paths in examples and provenance guidance.
6. Do not claim a package or integration is published unless it is publicly available. Installation from this repository uses `npx skills add`.

## Validation

Run from the repository root:

```bash
python3 -m unittest discover -s tests/higantic-html-artifacts -p 'test_*.py'
python3 -m py_compile skills/higantic-html-artifacts/scripts/higantic_html.py scripts/validate_repository.py tests/higantic-html-artifacts/test_higantic_html.py
python3 -m json.tool skills.sh.json >/dev/null
python3 -m json.tool evals/higantic-html-artifacts/evals.json >/dev/null
python3 scripts/validate_repository.py
```

All checks must pass on Python 3.9 and the current Python release before a release is considered ready.

## Security reports

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md).

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
