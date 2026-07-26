# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through [GitHub Security Advisories](https://github.com/Aneaire/higantic-skills/security/advisories/new). Do not include API keys, access tokens, customer data, private artifacts, or raw capability links in a public issue.

Include a concise description, affected files or commands, reproduction steps using non-sensitive test data, impact, and any suggested mitigation. Maintainers will acknowledge the report, investigate it, and coordinate disclosure and remediation as appropriate.

## Supported versions

The latest published revision of this repository is supported. Users should update installed skills and review release changes before using them in sensitive workflows.

## Live-reference trust model

The public manifest is fixed at `https://skills.higantic.com/v1/manifest.json`; references must use exact `https://skills.higantic.com/v1/references/<slug>.json` paths. Agent-consumed mutable Markdown and remote prose/instructions are prohibited. References have an exact closed JSON schema, ASCII-only constrained strings, fixed local identifier allowlists, booleans, and nonnegative safe-integer limits. Duplicate keys, concealed Unicode, unknown fields/identifiers, arbitrary strings, and malformed values are rejected.

Installed fetchers load per-skill version and URLs from canonical local config, disable environment proxies, send no API keys, cookies, Authorization header, or environment-derived headers, reject cross-origin redirects and unsafe paths, and enforce short timeouts plus 64 KiB limits. SHA-256 is used only to check consistency between manifest and reference bytes; it does not authenticate publisher intent. Remote bytes are never printed. Trusted installed code renders constrained state through fixed local explanations.

Installed `SKILL.md` safety, user approval, credential, destination, destructive-action, and sharing rules remain authoritative. Network or remote-validation failures render a bundled structured fallback through the same local renderer. A higher `minimumInstalledVersion` renders that fallback and requires `npx skills update <skill-slug>` rather than remotely changing executable behavior. Report manifest, hosting, redirect, cache, schema, Unicode, consistency, renderer, or safeguard-precedence weaknesses through the private process above.

## Credential and sharing model

- HiGantic API keys must be supplied only through process environment variables.
- The CLI does not accept an API key argument and defensively redacts configured credentials from output.
- Grant least-privilege scopes and reserve `html_artifacts:share` for deliberate sharing workflows.
- Public capability links are explicit opt-in, unlisted rather than access-controlled, and available to anyone who receives the link.
- Never share artifacts containing credentials, private customer data, confidential source, or unpublished vulnerabilities. Create a sanitized derivative instead.
