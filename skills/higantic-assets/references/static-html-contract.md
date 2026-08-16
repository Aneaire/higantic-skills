# Managed asset contract

The filename is retained for live-reference package compatibility; this document defines asset behavior, not HTML composition.

- Accepted uploads: PNG, JPEG, WebP, and GIF with matching magic bytes.
- Maximum upload size: 10 MiB.
- Remote image import is unsupported.
- Default storage target: `higantic`.
- Optional target: an owner-linked, currently available UploadThing app.
- Uploads are private by default.
- Canonical embedded reference: `higantic-asset://ASSET_ID`.
- Never expose or hotlink provider/storage URLs.
- Public visibility and deletion are distinct, explicitly confirmed operations.
- A public asset viewer uses `/i/{assetId}`, proxies validated bytes, and is no-store/noindex.
- Making private or deleting revokes the standalone viewer immediately.
- Pinned HTML artifact snapshots are independent and may retain referenced bytes.
