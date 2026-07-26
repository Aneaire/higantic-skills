---
name: higantic-html-artifacts
description: Create, update, or manage safe, versioned HTML reports in HiGantic. Use this skill only when the user explicitly asks to create, update, or manage a report or HTML artifact in HiGantic; mentions a HiGantic workspace, page, or artifact as the destination; or asks to manage HiGantic revisions, assets, or shares. Do not trigger for generic reports, visualizations, dashboards, plans, reviews, or comparisons with no HiGantic destination.
compatibility: Python 3.9+ and network access to a HiGantic agent server; no third-party packages.
license: MIT
---

# HiGantic HTML Artifacts

Create static visual review surfaces in the user's HiGantic workspace. Repository Markdown and code remain canonical; every HTML artifact is a derivative, disposable presentation that must point reviewers back to its sources.

## Workflow

1. Read `references/static-html-contract.md` before composing HTML.
2. Confirm `HIGANTIC_API_BASE_URL`, `HIGANTIC_AGENT_ID`, and `HIGANTIC_API_KEY` are present in the process environment. Never request, accept, or pass an API key through a CLI argument, prompt, source file, or committed env file.
3. Inspect the repository source first. Record repo-relative source paths, branch plus commit/ref, generated/updated date, current status, and decisions represented in the artifact. Do not make the artifact a competing source of truth.
4. Run `python3 scripts/higantic_html.py pages list`. Reuse the page whose stable purpose/label matches the work and retain its returned ID. Create only when needed, with a stable operation-specific idempotency key.
5. Give each maintained artifact a stable page-unique `externalId` derived from project and purpose. Run `artifacts lookup`, then `artifacts upsert`. Retain returned page/artifact IDs for ID-only operations.
6. When an image helps, run `assets list` and reuse a relevant managed image, or upload a locally created image with `assets upload --file`. Embed `higantic-asset://...`; never hotlink storage URLs.
7. Write one complete static document to a local file. Include provenance and a clear status/decision summary. Never include secrets, credentials, personal data, private customer data, unpublished vulnerabilities, or other sensitive material, especially if the artifact might later be shared.
8. Create/upsert the artifact or append a revision with `--html-file`. The CLI reads current revision/version preconditions. Exit code `3` means content or metadata changed: read the latest source, compare it with repository truth and the intended update, reconcile deliberately, then retry. Never blindly overwrite.
9. Return the private URL printed by the API. Describe it as a derivative, static, sandboxed artifact, not a deployed app or canonical documentation.

## Identity and deletion

- Page identity: reuse a stable page purpose/label and persist its returned page ID; use the same idempotency key only for exact create retries.
- Artifact identity: use immutable `externalId` for deterministic lookup/upsert. An idempotency key protects one create request; it does not replace `externalId`.
- Delete only after deliberate user intent. `artifacts delete --confirm-delete` removes the artifact, revisions, shares, snapshots, and associated retry records. `assets delete --confirm-delete` removes the live managed asset while pinned share snapshots may retain referenced bytes.
- HTML page deletion is not exposed. Delete contained artifacts individually.

## Sharing is opt-in

Never create or rotate a share unless the user explicitly asks to publish an unlisted capability link. Sharing requires the non-default `html_artifacts:share` scope and server feature flag.

- `shares list` returns metadata and token prefixes only.
- `shares create` requires `--confirm-public-sharing`. Omit `--revision` to pin the current revision or pass a specific immutable revision. Choose no expiration, `--expires-at-ms`, or `--expires-in-hours` deliberately.
- `shares revoke` requires `--confirm-revoke`.
- `shares rotate` requires `--confirm-public-sharing`, invalidates the old link, and returns a replacement.
- The full capability URL appears only on successful create/rotate and cannot be recovered later. It is unlisted, not access-controlled: anyone with the link can view the pinned revision until expiry or revocation.
- Review the artifact for sensitive data before sharing. If it contains any, do not share it; create a sanitized derivative instead.
- If the server feature flag is disabled, share commands exit `2` with a clear `share_management_unavailable` message.

## Useful commands

```bash
python3 scripts/higantic_html.py pages list
python3 scripts/higantic_html.py pages create --label "Visual reports" --idempotency-key "project:visual-reports-page"
python3 scripts/higantic_html.py assets list
python3 scripts/higantic_html.py assets upload --file ./hero.png
python3 scripts/higantic_html.py assets delete --asset-id ASSET_ID --confirm-delete
python3 scripts/higantic_html.py artifacts list --page-id PAGE_ID
python3 scripts/higantic_html.py artifacts create --page-id PAGE_ID --title "Release plan" --external-id "project:release-plan" --html-file plan.html --idempotency-key "project:release-plan:create"
python3 scripts/higantic_html.py artifacts lookup --page-id PAGE_ID --external-id "project:release-plan"
python3 scripts/higantic_html.py artifacts upsert --page-id PAGE_ID --external-id "project:release-plan" --title "Release plan" --html-file plan.html
python3 scripts/higantic_html.py artifacts get --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py artifacts update --page-id PAGE_ID --artifact-id ARTIFACT_ID --title "Release plan — approved"
python3 scripts/higantic_html.py artifacts delete --page-id PAGE_ID --artifact-id ARTIFACT_ID --confirm-delete
python3 scripts/higantic_html.py revisions list --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py revisions get --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2
python3 scripts/higantic_html.py revisions append --page-id PAGE_ID --artifact-id ARTIFACT_ID --html-file plan.html
python3 scripts/higantic_html.py revisions restore --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 1
python3 scripts/higantic_html.py shares list --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2 --expires-in-hours 24 --confirm-public-sharing
python3 scripts/higantic_html.py shares revoke --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-revoke
python3 scripts/higantic_html.py shares rotate --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-public-sharing
python3 scripts/higantic_html.py url --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2
```

Use `--html-file -` to read HTML from standard input. The CLI emits JSON except for `url`, which prints only the private URL. It never accepts an API key argument. It defensively redacts configured credentials and raw share capabilities from list/error output. Exit code `3` is reserved for revision/artifact-version conflicts; other operational errors use `2`.

## Artifact quality

- Lead with the decision, status, or main finding.
- Use a clear visual hierarchy, responsive layout, semantic landmarks, and readable contrast.
- Include concrete evidence: repo-relative files, stages, trade-offs, risks, acceptance criteria, and next actions.
- Include a visible provenance block with repository/ref/date/status/decisions and state that repository sources are canonical.
- Keep the artifact self-contained and disposable. Avoid pretending that static controls work.
- Preserve purpose and identity across revisions; make targeted updates instead of redesigning without cause.

Read `references/api.md` when debugging authentication, scopes, response envelopes, feature flags, rate limits, deletion behavior, sharing, or conflicts.
