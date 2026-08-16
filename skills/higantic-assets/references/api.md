# Managed Assets API contract

All routes are bearer-authenticated and agent-scoped under `/v1/agents/{agentId}`. Success responses use `{"data": ..., "requestId": "..."}`; failures use `{"error":{"code":"...","message":"...","details":...},"requestId":"..."}`. Responses use `Cache-Control: no-store`.

## Routes

- `GET /html-assets` — list same-agent assets; optional `target=higantic|uploadthing`.
- `GET /html-assets/{assetId}` — inspect one asset.
- `POST /html-assets` — upload a binary image body with `X-Asset-Name` and optional `X-Asset-Target`.
- `DELETE /html-assets/{assetId}` — delete with `X-Confirm-Delete: true`.
- `GET /html-assets/{assetId}/visibility` — read standalone visibility and stable public URL.
- `PUT /html-assets/{assetId}/visibility` — set `private|public`; public requires `confirmPublicSharing: true`.
- `GET /html-asset-targets` — list available storage targets.

## Scopes

- `assets:read` lists and inspects assets and targets.
- `assets:write` uploads, makes private, and deletes private assets.
- `assets:share` is additionally required to publish or delete an already-public asset.
- Legacy `html_assets:*` grants remain server-compatible, but current clients request canonical `assets:*` scopes.

## Upload and storage

Upload accepts PNG, JPEG, WebP, or GIF with matching magic bytes and a maximum body size of 10 MiB. Missing target defaults to `higantic`. `uploadthing` is valid only when the owner linked a usable UploadThing app. Provider credentials remain server-side. The service never imports a remote image URL.

Use the returned `higantic-asset://ASSET_ID` in HiGantic content. Do not use provider or storage URLs.

## Standalone visibility and deletion

Assets are private by default. Public visibility returns a stable `/i/{assetId}` full-fit proxy viewer with no-store/noindex behavior. Private, deleted, unsupported, unavailable, or foreign resources return the same generic not-found response.

Making private is immediate and needs no sharing confirmation. Publishing requires explicit acknowledgement and share scope. Deletion requires explicit confirmation; public deletion also requires share scope. Pinned HTML artifact snapshots are independent and can retain referenced bytes until their last snapshot reference disappears.

Rate limits are 120 requests and 30 writes per minute per key. CLI exit code `0` means success and `2` means an operational, configuration, or API error.
