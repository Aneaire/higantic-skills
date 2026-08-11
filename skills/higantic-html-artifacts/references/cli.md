# How the CLI works

The skill ships a dependency-free Python 3.9+ command-line interface in `scripts/`. Two launchers run the same program:

- `higantic` (POSIX) and `higantic.cmd` (Windows PowerShell) when `scripts/` is on `PATH`.
- `python3 scripts/higantic_html.py ...` when it is not.

Both accept the same commands and flags. `higantic --version` and `higantic --help` work through either launcher. The CLI emits JSON for product commands except `url`, which prints the API-returned private dedicated-viewer URL. Authentication and `doctor` print concise English by default; pass `--json` for structured output.

## Command groups

```bash
higantic auth ...                # login, status, use, logout, import, profiles
higantic doctor                  # read-only CLI, credential, storage, and API checks
higantic skills install          # review and install optional public skills
higantic pages list              # list HTML pages
higantic pages create            # create an HTML page
higantic canvas pages list       # list Excalidraw Canvas pages
higantic canvas pages create     # create a Canvas page
higantic canvas scenes list / get
higantic canvas scenes create    # semantic flowchart or complete scene JSON
higantic canvas scenes replace   # optimistic version required
higantic canvas scenes delete    # version and --confirm-delete required
higantic canvas visibility get / set --visibility public|private
higantic assets list             # list managed images
higantic assets upload --file    # upload a PNG/JPEG/WebP/GIF
higantic assets delete --asset-id ASSET_ID --confirm-delete
higantic artifacts list --page-id PAGE_ID
higantic artifacts create        # create with an idempotency key
higantic artifacts lookup --page-id PAGE_ID --external-id EXTERNAL_ID
higantic artifacts upsert --page-id PAGE_ID --external-id EXTERNAL_ID --html-file FILE
higantic artifacts get / update / delete --confirm-delete
higantic revisions list / get / append --html-file FILE / restore
higantic visibility get / set --visibility public|private
higantic shares list / create / revoke / rotate
higantic url --page-id PAGE_ID --artifact-id ARTIFACT_ID [--revision N]
```

Every command group and subcommand has `--help`. Global `--profile PROFILE` overrides the active profile for a single artifact command.

## Key behavior

- **Identity**: page IDs come from `pages list`/`pages create`; artifacts use an immutable page-unique `externalId` for deterministic lookup/upsert. Retain returned IDs for ID-based commands.
- **Idempotency**: `pages create` and `artifacts create` may pass `--idempotency-key` for exact create retries only; it never replaces `externalId`.
- **Concurrency**: upsert, append, and restore send `expectedCurrentRevision`; metadata and visibility writes send `expectedArtifactVersion`; Canvas replacement and deletion require the latest scene version. Stale state returns a conflict and exit code `3`.
- **Sharing is opt-in**: HTML publish/pinned-link commands require `html_artifacts:share`; Canvas publishing requires `excalidraw:share`. Both require `--confirm-public-sharing`, while deletion requires `--confirm-delete`.
- **Public content**: once an artifact is public, HTML upsert/append/restore also require `--confirm-public-sharing`, the share scope, and the latest artifact version.
- **Redaction**: the CLI registers environment, profile, imported, and issued keys plus raw share capabilities for process-local redaction and never prints them. It intentionally has no API-key argument.
- **Exit codes**: `0` success, `3` revision/artifact/scene version conflicts, `2` all other operational/configuration/API errors.

## See also

- `references/api.md` — full route list, auth/scopes, identity, conflicts, deletion, visibility, sharing, assets, limits, envelopes, and exit codes.
- `references/auth.md` — device authentication check and profiles.
- The repository README for install, live-reference, authentication, and sharing details.
- The live product reference (closed structured JSON) rendered by `scripts/fetch_live_reference.py` and reachable at `https://skills.higantic.com/v1/references/higantic-html-artifacts.json`.
- Run `higantic --help`, `higantic auth --help`, or `python3 scripts/higantic_html.py --help` for the exact current surface.
