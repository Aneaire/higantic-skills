# HiGantic HTML Artifacts skill

Portable skill for Codex, Claude Code, and OpenCode. It creates static, versioned HTML review artifacts through HiGantic's direct non-LLM API. Repository Markdown and code remain canonical; artifacts are derivative presentation surfaces with source provenance.

## Install

Install this skill from the public HiGantic skills collection:

```bash
npx skills add Aneaire/higantic-skills --skill higantic-html-artifacts
```

For a global installation, add `--global`. The installed skill is self-contained and supports coding agents recognized by the `skills` CLI.

Set credentials only in the coding agent's process environment:

```bash
export HIGANTIC_API_BASE_URL="https://agent.higantic.com"
export HIGANTIC_AGENT_ID="your-agent-id"
export HIGANTIC_API_KEY="your-scoped-key"
```

The exact official origin `https://agent.higantic.com` is accepted by default. The CLI validates and normalizes the destination before loading the bearer key, rejects cross-origin redirects, and does not accept userinfo, queries, fragments, or path traversal in the base URL.

A trusted non-official HTTPS origin requires `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1`. This explicitly permits the API key to be sent to that custom origin, so use it only for infrastructure you control. Plain HTTP is allowed only for `127.0.0.1`, `localhost`, or `::1` when both `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1` and `HIGANTIC_ALLOW_INSECURE_LOCALHOST=1` are set. Never enable the insecure-localhost override for a remote or production service.

Generate a key in HiGantic agent settings with only the needed scopes:

- `html_artifacts:read` and `html_artifacts:write`
- `html_assets:read` and `html_assets:write`
- `html_pages:create` when page creation is required
- `html_artifacts:share` only when the user deliberately needs public capability links

The secret is shown once and only its hash is stored. Do not place it in a repository, prompt, CLI argument, shell history, command transcript, or committed env file. The CLI intentionally has no API-key argument.

Run `python3 scripts/higantic_html.py --help`. The script supports Python 3.9+ and has no third-party dependencies.

## Operating model

1. Treat repository Markdown/code as source of truth and HTML as derivative.
2. Reuse a page by stable purpose/label and retain its ID. Use operation-specific idempotency keys only for exact create retries.
3. Use a stable page-unique artifact `externalId` for lookup/upsert and retain returned IDs.
4. Add visible provenance: repo-relative sources, branch plus commit/ref, generated/updated date, status, decisions, and a canonical-source note.
5. On exit code `3`, fetch the latest artifact/repository state and reconcile. Do not overwrite a newer revision or artifact version blindly.
6. Keep potentially shared artifacts free of secrets, credentials, personal/private data, and unpublished security details.

## Managed assets and deletion

```bash
python3 scripts/higantic_html.py assets list
python3 scripts/higantic_html.py assets upload --file ./hero.png
python3 scripts/higantic_html.py assets delete --asset-id ASSET_ID --confirm-delete
python3 scripts/higantic_html.py artifacts delete --page-id PAGE_ID --artifact-id ARTIFACT_ID --confirm-delete
```

Use `higantic-asset://<assetId>` as an HTML `<img src>`; never copy temporary storage URLs into artifacts. Artifact deletion cascades through revisions and shares. Asset deletion removes the live record while bytes referenced by a pinned share snapshot may remain until no references exist.

## Opt-in capability sharing

Shares are never created by default. They require explicit commands, the non-default `html_artifacts:share` scope, server-side sharing enabled, and confirmation flags.

```bash
python3 scripts/higantic_html.py shares list --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2 --expires-in-hours 24 --confirm-public-sharing
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --expires-at-ms 1893456000000 --confirm-public-sharing
python3 scripts/higantic_html.py shares revoke --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-revoke
python3 scripts/higantic_html.py shares rotate --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-public-sharing
```

Omit `--revision` to pin the current revision. Omit both expiration options for no expiration. Capability links are unlisted but accessible to anyone with the link. The complete URL is shown only on create/rotate and cannot be recovered later. List/revoke output never exposes it. If sharing is disabled on the server, commands fail with `share_management_unavailable` and exit code `2`.
