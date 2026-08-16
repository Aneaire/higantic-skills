# Managed Assets CLI

The independently installed `@higantic/cli` exposes:

```bash
higantic assets list [--target higantic|uploadthing]
higantic assets show --asset-id ASSET_ID
higantic assets targets list
higantic assets targets status
higantic assets targets use higantic|uploadthing
higantic assets upload --file FILE [--target higantic|uploadthing]
higantic assets make-public --asset-id ASSET_ID --confirm-public-sharing
higantic assets make-private --asset-id ASSET_ID
higantic assets delete --asset-id ASSET_ID --confirm-delete
```

Commands return JSON. Global `--profile PROFILE` selects a named profile for one command. Identifiers are validated as a single safe path segment before any request. Secrets and unexpected capability fields are redacted from output and errors.

Uploads use the profile's target preference, defaulting to `higantic`; `--target` overrides it once. Environment-based credentials cannot persist a profile preference and default to `higantic`.

The public/private and delete confirmations are intentional gates. Do not infer publication from upload or deletion from publication. Exit code `0` means success; operational failures use `2`.
