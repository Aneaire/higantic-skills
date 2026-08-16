# Device authentication check

Use a named CLI profile for interactive work. Never request, accept, print, or pass an API key in a prompt or CLI argument.

```bash
higantic auth status
higantic auth profiles
higantic doctor
```

If the CLI is missing:

```bash
npm install --global @higantic/cli && higantic setup
higantic auth login
```

Login uses browser approval and secure OS credential storage. For CI, the complete `HIGANTIC_API_BASE_URL`, `HIGANTIC_AGENT_ID`, and `HIGANTIC_API_KEY` triple may override profiles; if any is set, all three are required. Never commit the triple.

Grant only the needed scopes: `assets:read` to inspect, `assets:write` to upload/change private state/delete private assets, and `assets:share` only for deliberate publication or deletion of an already-public asset.

Run `higantic doctor` for profile, credential-store, API, or storage-target errors. A profile may store only the non-secret default target `higantic|uploadthing`; provider credentials stay in HiGantic.
