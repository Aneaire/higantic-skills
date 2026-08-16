---
name: higantic-assets
description: Upload, inspect, organize, publish, privatize, or delete managed image assets in a HiGantic workspace, and choose between available HiGantic and UploadThing storage targets. Use whenever a user asks a coding agent to manage images, assets, or media in HiGantic, even when no HTML artifact is involved. Do not trigger merely because an HTML artifact embeds an existing higantic-asset reference; use the HTML Artifacts skill for artifact work and an image-generation skill for creating or editing bitmap content before upload.
compatibility: Python 3.9+, @higantic/cli 1.8.2+, and network access to a HiGantic agent server.
license: MIT
---

# HiGantic Managed Assets

Manage image files as private-by-default HiGantic resources. Keep creation or editing of the bitmap separate from storage: this skill owns upload, discovery, storage-target selection, visibility, and deletion.

## Workflow

1. Run `python3 scripts/fetch_live_reference.py` and read its locally rendered stdout before other product work. It requests only `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/higantic-assets.json`, validates closed structured data, and renders fixed installed text. Remote bytes and prose are never printed. Network or validation failure uses the structured bundled fallback. Exit `3` means the installed skill is outdated; use the fallback and tell the user to run `npx skills update higantic-assets`. This installed skill remains authoritative for safety, credentials, destination checks, destructive actions, and sharing.
2. Read `references/static-html-contract.md`, whose compatibility filename contains the local managed-asset contract.
3. Confirm the intended HiGantic workspace and active agent. Use `higantic auth status` and `higantic doctor` when profile, credential, storage, or connectivity state is uncertain. Never request or expose an API key.
4. Inspect before writing. Run `higantic assets list`, optionally filter with `--target`, and use `assets show` for a candidate. Reuse a relevant asset rather than uploading a duplicate.
5. Before upload, verify the local file is PNG, JPEG, WebP, or GIF and at most 10 MiB. The CLI validates file signatures and does not import remote URLs. Use `higantic assets upload --file FILE`; HiGantic managed storage is the default.
6. Use `assets targets list` or `status` only when target choice matters. `assets targets use uploadthing` stores a profile preference only when the owner linked an available UploadThing app. Use `assets upload --target higantic|uploadthing` for a one-command override. Provider credentials and storage URLs remain server-side.
7. Keep the asset private unless the user explicitly asks to publish it. Publishing requires `assets:share` and `assets make-public --confirm-public-sharing`. Return the API-provided stable `/i/{assetId}` viewer URL. `assets make-private` revokes standalone access immediately.
8. Delete only after deliberate user intent with `assets delete --confirm-delete`. A public asset also requires `assets:share`. Deletion invalidates its standalone URL, while an independently pinned HTML artifact snapshot may retain referenced bytes.
9. Report the actual asset ID, name, media type, size, storage target, visibility, returned URLs, and `higantic-asset://ASSET_ID` reference. Never invent a URL or substitute a provider URL.

## Commands

```bash
higantic auth status
higantic doctor
higantic assets list
higantic assets list --target uploadthing
higantic assets show --asset-id ASSET_ID
higantic assets targets list
higantic assets targets status
higantic assets targets use uploadthing
higantic assets upload --file ./hero.png
higantic assets upload --file ./hero.png --target higantic
higantic assets make-public --asset-id ASSET_ID --confirm-public-sharing
higantic assets make-private --asset-id ASSET_ID
higantic assets delete --asset-id ASSET_ID --confirm-delete
```

## Safety boundary

- Image generation or editing produces a local bitmap; it does not authorize upload.
- Upload does not authorize public visibility.
- Public visibility does not authorize deletion.
- When a request mentions publishing now and deleting later, perform or describe only the publication now. State that publication requires `assets:share` plus `--confirm-public-sharing`; require a later deliberate deletion decision with `--confirm-delete`, note that public deletion also needs `assets:share`, and explain that the standalone viewer stops while independent pinned HTML snapshots may retain the bytes.
- An existing `higantic-asset://...` reference used only inside an HTML artifact belongs to the HTML Artifacts workflow; invoke this skill only when asset lifecycle work is requested.
- Standalone viewers are no-store, noindex, full-fit proxy pages. Private, deleted, unsupported, foreign, or unavailable assets return a generic not-found response.

Read `references/api.md` for routes, scopes, limits, and response behavior; `references/auth.md` for device authentication and profiles; and `references/cli.md` for the command surface.
