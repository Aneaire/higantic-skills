# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through [GitHub Security Advisories](https://github.com/Aneaire/higantic-skills/security/advisories/new). Do not include API keys, access tokens, customer data, private artifacts, or raw capability links in a public issue.

Include a concise description, affected files or commands, reproduction steps using non-sensitive test data, impact, and any suggested mitigation. Maintainers will acknowledge the report, investigate it, and coordinate disclosure and remediation as appropriate.

## Supported versions

The latest published revision of this repository is supported. Users should update installed skills and review release changes before using them in sensitive workflows.

## Credential and sharing model

- HiGantic API keys must be supplied only through process environment variables.
- The CLI does not accept an API key argument and defensively redacts configured credentials from output.
- Grant least-privilege scopes and reserve `html_artifacts:share` for deliberate sharing workflows.
- Public capability links are explicit opt-in, unlisted rather than access-controlled, and available to anyone who receives the link.
- Never share artifacts containing credentials, private customer data, confidential source, or unpublished vulnerabilities. Create a sanitized derivative instead.
