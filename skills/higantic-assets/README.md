# HiGantic Managed Assets skill

Portable skill for managing image assets in a HiGantic workspace independently from HTML artifacts or Canvas diagrams.

## Install

Install the standalone CLI and review all optional public skills:

```bash
npm install --global @higantic/cli && higantic setup
higantic auth login
```

Or install only this skill:

```bash
npx skills add Aneaire/higantic-skills --skill higantic-assets --global
```

The skill handles upload, listing, inspection, storage-target selection, standalone public/private visibility, and deliberate deletion. It accepts local PNG, JPEG, WebP, and GIF files up to 10 MiB. Assets remain private unless explicitly published.

HTML artifact work remains in `higantic-html-artifacts`. That skill may embed an existing `higantic-asset://ASSET_ID` reference without taking ownership of the asset lifecycle. Image generation or editing should happen before this skill uploads the resulting local file.

## Live product reference

Run `python3 scripts/fetch_live_reference.py` first. It fetches only `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/higantic-assets.json`, validates exact closed-schema JSON, and renders only fixed local text. No API key, cookies, authorization header, environment proxy, or arbitrary remote prose is accepted. A structured bundled fallback is used when the network or remote validation fails.

Local skill instructions always win for confirmation, credentials, destination validation, destructive operations, and sharing.

## Private by default

Upload creates a private managed asset and returns an immutable `higantic-asset://ASSET_ID` reference. Publishing is separate and requires both `assets:share` and `--confirm-public-sharing`. Making an asset private revokes the standalone viewer immediately. Deleting requires `--confirm-delete`; deleting an already-public asset also requires share scope.

See `references/api.md`, `references/auth.md`, and `references/cli.md` for the full contract.
