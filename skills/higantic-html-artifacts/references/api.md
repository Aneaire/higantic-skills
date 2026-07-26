# Direct HTML Artifacts API

Base path: `/v1/agents/{agentId}/html-pages`

Authentication uses only `Authorization: Bearer <scoped-key>` sourced from `HIGANTIC_API_KEY`. Query-string keys and CLI key arguments are rejected/unsupported. Legacy unscoped keys cannot access `/v1`.

## API destination safety

`HIGANTIC_API_BASE_URL` is parsed and validated before the CLI loads the bearer key. The exact official HTTPS origin `https://agent.higantic.com` is accepted by default. User information, queries, fragments, missing hosts, non-HTTP(S) schemes, and base paths containing dot traversal after percent-decoding are rejected. The normalized URL retains a deliberate base path without a trailing slash.

A non-official HTTPS origin is permitted only when `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1`. Enabling this flag explicitly allows the credential to be sent to the configured custom origin; use it only with infrastructure you control and trust.

HTTP is permitted only for the loopback hosts `127.0.0.1`, `localhost`, and `::1`, and only when both `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1` and `HIGANTIC_ALLOW_INSECURE_LOCALHOST=1` are set. The insecure override is for local development only and must never be used for remote or production services.

Automatic redirects are restricted to the same origin. A cross-origin redirect fails with `unsafe_redirect` before the Authorization header can be sent to the new destination.

Scopes:

- `html_artifacts:read`: list pages/artifacts/revisions and read source.
- `html_artifacts:write`: create, update, revise, restore, and delete artifacts.
- `html_artifacts:share`: list/create/revoke/rotate capability shares; high-trust, non-default scope.
- `html_assets:read`: list managed images.
- `html_assets:write`: upload and delete managed images.
- `html_pages:create`: create HTML Artifact pages.
- `api:invoke`: invoke legacy user-defined `/api` endpoints; unrelated to artifact access.

Routes:

- `GET|POST /v1/agents/{agentId}/html-assets`
- `DELETE /v1/agents/{agentId}/html-assets/{assetId}`
- `GET|POST /html-pages`
- `GET|POST /html-pages/{pageId}/artifacts`
- `GET|PUT /html-pages/{pageId}/artifacts/by-external-id/{externalId}`
- `GET|PATCH|DELETE /html-pages/{pageId}/artifacts/{artifactId}`
- `GET|POST /html-pages/{pageId}/artifacts/{artifactId}/revisions`
- `GET /html-pages/{pageId}/artifacts/{artifactId}/revisions/{revision}`
- `POST /html-pages/{pageId}/artifacts/{artifactId}/revisions/{revision}/restore`
- `GET|POST /html-pages/{pageId}/artifacts/{artifactId}/shares`
- `DELETE /html-pages/{pageId}/artifacts/{artifactId}/shares/{shareId}`
- `POST /html-pages/{pageId}/artifacts/{artifactId}/shares/{shareId}/rotate`

## Identity, retries, and conflicts

`externalId` is an immutable 1–128 character client key unique within one page. Use a stable project/purpose key for deterministic lookup/upsert. Retain returned page and artifact IDs for ID-based commands.

Before constructing any resource path, the CLI validates agent, page, artifact, asset, external, and share identifiers as one safe path segment. Empty values, control characters, literal or recursively percent-decoded `.`/`..`, decoded slash or backslash separators, and excessive recursive encoding fail with `invalid_path_segment` before any request. Colons and ordinary spaces remain supported and are percent-encoded for transport.

Page and artifact create calls may send a 1–255 visible-ASCII `Idempotency-Key`. An exact replay returns the original resource; reuse with different input returns `idempotency_conflict`. Use idempotency only for transport retries. It does not replace stable page selection or artifact `externalId`.

Append, restore, and external-ID upsert require `expectedCurrentRevision`. Metadata `PATCH` and upsert also require `expectedArtifactVersion`. Use both as zero only when external-ID lookup returned 404 and the upsert will create. Stale content returns `revision_conflict`; stale metadata returns `artifact_version_conflict`. The CLI exits `3`: re-read repository and artifact state, compare changes, reconcile deliberately, and retry with fresh preconditions. Never blindly retry or overwrite.

## Deletion

Artifact deletion atomically removes the artifact, revisions, capability shares/snapshots, and artifact-targeted idempotency records. Existing capability links then return generic 404. Repeating deletion returns `not_found`.

Managed asset deletion removes the live record. Storage bytes remain while a pinned share snapshot references the same object and are removed after the final live/snapshot reference disappears. Direct HTML page deletion is not exposed; delete contained artifacts individually.

The CLI requires `--confirm-delete` for both destructive commands.

## Capability shares

Share routes require `html_artifacts:share` and are registered only when `shareManagementEnabled` or `HTML_ARTIFACT_PUBLIC_SHARING_ENABLED=true`. A disabled route returns generic `404 not_found`; the CLI reports contextual `share_management_unavailable` and exit code `2`.

Sharing is opt-in and never part of artifact creation/upsert. `shares create` requires `--confirm-public-sharing`. Omit `--revision` to pin the current immutable revision, or choose a positive revision. Choose no expiration, a future Unix millisecond `--expires-at-ms`, or a relative `--expires-in-hours`. `shares revoke` requires `--confirm-revoke`; rotate requires `--confirm-public-sharing`.

Capability links are unlisted but accessible to anyone with the link. Create and rotate return the full `capabilityUrl` once. List returns only metadata and `tokenPrefix`; it must never return raw tokens, hashes, or capability URLs. Revocation invalidates a link. Rotation revokes the old link and returns a new one once. The CLI defensively redacts unexpected token/hash/capability fields from list/error output.

Do not share artifacts containing credentials, personal/private data, confidential source, unpublished vulnerabilities, or other sensitive information. Produce a sanitized derivative instead.

## Assets and content

Asset upload accepts a binary PNG/JPEG/WebP/GIF body with matching magic bytes, `X-Asset-Name`, and a 10 MiB maximum. Use returned `higantic-asset://<assetId>` references, never storage URLs. The service never imports remote images.

Canonical source supports static HTML, inline CSS, safe credential-free HTTPS links, and managed images. Limits: 250 KiB source, 100 revisions/artifact, 120 requests/minute/key, and 30 writes/minute/key.

Success envelope: `{"data": {...}, "requestId": "..."}`. Error envelope: `{"error":{"code":"...","message":"...","details":...},"requestId":"..."}`. Responses use `Cache-Control: no-store`.

CLI exit codes:

- `0`: success
- `3`: `revision_conflict` or `artifact_version_conflict`
- `2`: all other operational/configuration/API errors
