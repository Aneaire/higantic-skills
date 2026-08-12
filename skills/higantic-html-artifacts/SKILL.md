---
name: higantic-html-artifacts
description: Create, update, or manage safe, versioned HTML reports in HiGantic. Use this skill only when the user explicitly asks to create, update, or manage a report or HTML artifact in HiGantic; mentions a HiGantic workspace, page, or artifact as the destination; or asks to manage HiGantic revisions, assets, visibility, or pinned shares. Do not trigger for generic reports, visualizations, dashboards, plans, reviews, or comparisons with no HiGantic destination.
compatibility: Python 3.9+ and network access to a HiGantic agent server; no third-party packages.
license: MIT
---

# HiGantic HTML Artifacts

Create static visual review surfaces in the user's HiGantic workspace. Repository Markdown and code remain canonical; every HTML artifact is a derivative, disposable presentation that must point reviewers back to its sources.

## Workflow

1. Run `python3 scripts/fetch_live_reference.py` and read its locally rendered stdout before other product work. It loads `references/live-reference.json`, requests only `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/higantic-html-artifacts.json`, validates the closed structured schema, exact origin/path, sizes, version gate, and SHA-256 consistency, then renders only fixed installed text selected by allowlisted identifiers and constrained values. Remote bytes and arbitrary prose are never printed. Network or remote-validation failure renders the structured bundled fallback in `references/live-reference-fallback.json` through the same local renderer. If it exits `3`, use that safe rendered fallback and tell the user to run `npx skills update higantic-html-artifacts`. This installed `SKILL.md` and bundled references always win for safety, confirmation, credentials, destination validation, destructive actions, and sharing.
2. Read `references/static-html-contract.md` before composing HTML.
3. Resolve credentials through a named CLI profile by default. If no profile exists, tell the user to place `scripts/` on `PATH` and run `higantic auth login` in their own terminal; never ask them to paste the resulting key into a prompt. Read `references/auth.md` to confirm the device is authenticated (`higantic auth status`) and to interpret profile, credential, and storage errors. Interactive login may separately offer missing public HiGantic skills after authentication; each installation remains optional and requires its own terminal confirmation. The complete `HIGANTIC_API_BASE_URL` / `HIGANTIC_AGENT_ID` / `HIGANTIC_API_KEY` triple is the CI/noninteractive override: if any one is set, all three are required and the complete triple wins without mixing with profile data. Never request, accept, or pass an API key through a CLI argument, prompt, source file, or committed env file. The live-reference fetch uses no credential.
4. Inspect the repository source first. Record repo-relative source paths, branch plus commit/ref, generated/updated date, current status, and decisions represented in the artifact. Do not make the artifact a competing source of truth.
5. Reuse a retained, valid page ID when the page's stable purpose still matches the work; do not list pages again just to rediscover it. Otherwise run `python3 scripts/higantic_html.py pages list`, reuse the matching page, or create one only when needed with a stable operation-specific idempotency key. Retain the returned page ID.
6. Give each maintained artifact a stable page-unique `externalId` derived from project and purpose. For a create or update, call `artifacts upsert` directly: the CLI performs its own required lookup/read and sends optimistic revision/version preconditions. Do not run a separate `artifacts lookup` immediately before that upsert. Use `artifacts lookup` only for read-only discovery or when another operation genuinely needs the current identity, then retain returned page/artifact IDs for ID-only operations.
7. When an image helps, run `assets list` and reuse a relevant managed image, inspect one with `assets show`, or upload a locally created image with `assets upload --file`. HiGantic managed storage is the default. Use `assets targets list/status/use` only when choosing between it and an owner-linked UploadThing app; `assets upload --target` is a one-command override. Embed `higantic-asset://...`; never hotlink storage URLs.
8. Write one complete static document to a local file. Include provenance and a clear status/decision summary. Preflight the exact source against `references/static-html-contract.md`: ensure every CSS custom property used is declared, mobile content remains readable, and no unsupported construct, remote dependency, motion-dependent meaning, or fake interactive control remains. Never include secrets, credentials, personal data, private customer data, unpublished vulnerabilities, or other sensitive material, especially if the artifact might later be shared.
9. Create/upsert the artifact or append a revision with `--html-file`. The CLI reads current revision/version and visibility first. If the artifact is already public, review the replacement for sensitive data and use `--confirm-public-sharing`; the CLI sends that acknowledgement and the observed artifact version into the write, while the backend atomically requires both plus the non-default share scope before live content can change. Exit code `3` means content, metadata, or visibility changed: read the latest source, compare it with repository truth and the intended update, reconcile deliberately, then retry. Never blindly overwrite.
10. Inspect the returned revision's `sanitization.removedCount` and `removedKinds`. A zero count means the revision saved cleanly. If anything was removed, replace those constructs with supported static equivalents and make at most one corrected upsert/revision using fresh preconditions. Inspect that result, then stop and report any residual removals truthfully; never loop, imply removed features survived, or describe the unsanitized source as the saved result.
11. Return the actual title, revision, sanitization status, and private dedicated artifact-viewer URL by default. If the user explicitly asked to publish, review the artifact for sensitive data, use `visibility set --visibility public --confirm-public-sharing`, and return the stable public URL from that response. Describe either artifact as derivative, static, and sandboxed, not a deployed app or canonical documentation.

## Identity and deletion

- Page identity: reuse a stable page purpose/label and persist its returned page ID; use the same idempotency key only for exact create retries.
- Artifact identity: use immutable `externalId` for deterministic lookup/upsert. An idempotency key protects one create request; it does not replace `externalId`.
- Delete only after deliberate user intent. `artifacts delete --confirm-delete` removes the artifact, revisions, shares, snapshots, and associated retry records. `assets delete --confirm-delete` removes the live managed asset and invalidates its standalone public URL; deleting a public image also requires `html_assets:share`, while pinned share snapshots may retain referenced bytes.
- HTML page deletion is not exposed. Delete contained artifacts individually.

## Sharing is opt-in

Never publish stable visibility, change the live content of an already-public artifact, or create/rotate a pinned link unless the user explicitly asks. Sharing and public-content replacement require the non-default `html_artifacts:share` scope and server support. Artifact create/upsert never changes private visibility to public.

Standalone managed images are also private by default. Publish only an explicitly approved PNG/JPEG/WebP/GIF with `assets make-public --confirm-public-sharing` and the non-default `html_assets:share` scope. Return the stable `/i/{assetId}` URL from the response; it is a no-store/noindex full-fit viewer that proxies the bytes. `assets make-private` revokes standalone access immediately without affecting published artifact snapshots.

- `visibility get` reads normalized private/public state, stable public URL, version, and update time with read scope.
- `visibility set --visibility public` requires `--confirm-public-sharing`; the stable `/p/{artifactId}` URL follows the current revision until made private.
- Publishing requires a current revision and at most 100 managed images. Later HTML upsert, append, or restore operations on that public artifact also require `--confirm-public-sharing`, the share scope, and the latest artifact version because they replace live content immediately. The backend checks all three atomically.
- `visibility set --visibility private` is immediate and needs no confirmation. It does not revoke pinned links.
- Pinned `/s/{token}` links are separate immutable snapshots that remain active until expiry/revocation even if stable visibility becomes private.
- `shares list` returns metadata and token prefixes only.
- `shares create` requires `--confirm-public-sharing`. Omit `--revision` to pin the current revision or pass a specific immutable revision. Choose no expiration, `--expires-at-ms`, or `--expires-in-hours` deliberately.
- `shares revoke` requires `--confirm-revoke`.
- `shares rotate` requires `--confirm-public-sharing`, invalidates the old link, and returns a replacement.
- The full capability URL appears only on successful create/rotate and cannot be recovered later. It is unlisted, not access-controlled: anyone with the link can view the pinned revision until expiry or revocation.
- Review the artifact for sensitive data before sharing. If it contains any, do not share it; create a sanitized derivative instead.
- If public sharing is unavailable, visibility writes and pinned-link commands exit `2` with a clear `share_management_unavailable` message.

## Useful commands

```bash
higantic auth login
higantic auth status
higantic auth profiles
higantic auth use PROFILE
higantic auth logout
higantic auth import --stdin
higantic doctor
higantic --version
higantic skills install
higantic skills install --json
python3 scripts/higantic_html.py pages list
python3 scripts/higantic_html.py pages create --label "Visual reports" --idempotency-key "project:visual-reports-page"
python3 scripts/higantic_html.py assets list
python3 scripts/higantic_html.py assets show --asset-id ASSET_ID
python3 scripts/higantic_html.py assets targets list
python3 scripts/higantic_html.py assets targets status
python3 scripts/higantic_html.py assets targets use uploadthing
python3 scripts/higantic_html.py assets upload --file ./hero.png
python3 scripts/higantic_html.py assets upload --file ./hero.png --target higantic
python3 scripts/higantic_html.py assets make-public --asset-id ASSET_ID --confirm-public-sharing
python3 scripts/higantic_html.py assets make-private --asset-id ASSET_ID
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
python3 scripts/higantic_html.py visibility get --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py visibility set --page-id PAGE_ID --artifact-id ARTIFACT_ID --visibility public --confirm-public-sharing
python3 scripts/higantic_html.py visibility set --page-id PAGE_ID --artifact-id ARTIFACT_ID --visibility private
python3 scripts/higantic_html.py shares list --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2 --expires-in-hours 24 --confirm-public-sharing
python3 scripts/higantic_html.py shares revoke --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-revoke
python3 scripts/higantic_html.py shares rotate --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-public-sharing
python3 scripts/higantic_html.py url --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2
```

Use `--html-file -` to read HTML from standard input. The CLI emits JSON except for `url`, which prints the API-returned private dedicated-viewer URL for an artifact or revision, or the workspace URL when only a page is requested. Visibility responses include the stable public URL even while private, but that URL resolves publicly only while visibility is `public`. The CLI never accepts an API key argument and defensively redacts environment, profile, imported, and issued keys plus raw share capabilities from output and errors. Native secure storage is required by default; protected-file storage is explicit only with both `--storage file` and `--allow-protected-file`. Exit code `3` is reserved for revision/artifact-version conflicts; other operational errors use `2`.

## Artifact quality

- Lead with the decision, status, or main finding.
- Use a clear visual hierarchy, responsive layout, semantic landmarks, and readable contrast.
- Include concrete evidence: repo-relative files, stages, trade-offs, risks, acceptance criteria, and next actions.
- Include a visible provenance block with repository/ref/date/status/decisions and state that repository sources are canonical.
- Keep the artifact self-contained and disposable. Avoid pretending that static controls work.
- Prefer HTML/CSS grids, tables, proportional bars, timelines, labeled small multiples, callouts, and ordinary safe links over SVG, canvas, animation, or controls. Every visible affordance must be truthful in the saved static document.
- Before writing, verify every CSS variable resolves, the narrow-screen layout does not clip or collapse into unreadable columns, and the summary describes the saved artifact rather than planned or sanitized-away features.
- Preserve purpose and identity across revisions; make targeted updates instead of redesigning without cause.

Read `references/api.md` when debugging authentication, scopes, response envelopes, feature flags, rate limits, deletion behavior, sharing, or conflicts. Read `references/auth.md` to verify device sign-in and profiles. Read `references/cli.md` for how the CLI works, its command groups, and its documentation links.
