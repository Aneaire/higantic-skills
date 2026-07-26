# Maintainer rules

- Keep this repository public-only. Never add secrets, credentials, customer data, unpublished vulnerabilities, private implementation details, internal URLs, local workspace paths, or content copied from private sources unless it is explicitly approved for this public skill.
- Each skill lives at `skills/<name>/`, contains `SKILL.md`, and has frontmatter whose `name` matches the directory and whose `description` clearly states when the skill applies.
- Keep each installable skill self-contained with its runtime scripts and references; keep maintainer-only tests and evals in the repository-level `tests/` and `evals/` directories.
- Use progressive disclosure: make `SKILL.md` concise and operational, then place detailed contracts and API references under `references/`.
- Repository code and documentation remain the source of truth. Generated HTML artifacts are derivative, disposable review surfaces with visible provenance.
- Coordinate public skill changes with the supported HiGantic API. Do not document speculative routes, scopes, packages, flags, or behavior; compatibility changes require corresponding documentation and tests.
- Preserve environment-only API keys, explicit opt-in public sharing, optimistic concurrency, output redaction, and confirmation gates for destructive or sharing operations.
- Run the unit tests, Python compilation, JSON validation, and `scripts/validate_repository.py` before release.
- A release is ready only when public wording is accurate, links resolve, examples are safe, the skill is self-contained, required checks pass on Python 3.9 and current Python, and no private-only material remains.
