# HiGantic HTML Artifacts skill

Portable skill for Codex, Claude Code, and OpenCode. It creates static, versioned HTML review artifacts through HiGantic's direct non-LLM API. Repository Markdown and code remain canonical; artifacts are derivative presentation surfaces with source provenance.

## Install

Install this skill from the public HiGantic skills collection:

```bash
npx skills add Aneaire/higantic-skills --skill higantic-html-artifacts
```

For a global installation, add `--global`. The installed payload is self-contained and contains only `SKILL.md`, `README.md`, runtime `scripts/`, and bundled `references/`.

## Live product reference

Before using the product workflow, run `python3 scripts/fetch_live_reference.py` and read its locally rendered stdout. The fetcher loads installed version and exact endpoints from `references/live-reference.json`, then requests only `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/higantic-html-artifacts.json`. It disables environment proxies, sends no API key, cookies, Authorization header, or environment-derived headers, and never prints remote bytes or executes remote content.

The remote reference is closed-schema JSON with no descriptions, notes, Markdown, URLs, shell commands, or arbitrary strings. Validation covers duplicate keys, ASCII-only constrained values, local capability/command/scope allowlists, exact fields and types, booleans, nonnegative integer limits, timestamps, versions, exact origin/path, redirects, 64 KiB bounds, and SHA-256 consistency. Trusted local code renders only fixed explanations selected by known identifiers and constrained values.

Network or validation failure renders `references/live-reference-fallback.json` through the same local renderer. If `minimumInstalledVersion` exceeds the version in `references/live-reference.json`, the fallback is rendered and the script exits `3` with `npx skills update higantic-html-artifacts` guidance. Local `SKILL.md` safety, approval, credential, destination, destructive-action, and sharing rules remain authoritative.

## Authenticate with a profile

For interactive use, place this skill's `scripts/` directory on `PATH` and run:

```bash
export PATH="$PWD/scripts:$PATH"
higantic auth login
higantic auth status
```

Windows PowerShell uses the included `higantic.cmd` launcher:

```powershell
$env:Path = "$PWD\scripts;$env:Path"
higantic auth login
higantic auth status
```

`higantic auth login` preflights secure storage, shows a ten-minute browser verification URL and code on stderr, and waits for explicit approval of one active agent and a reviewed scope subset. Standard artifact scopes are requested by default; the high-trust `html_artifacts:share` scope is requested only with an explicit repeated `--scope` and is never preselected in the browser.

After successful interactive login, the CLI offers to review missing public HiGantic skills. The catalog is optional, every missing skill has a separate yes/no prompt, installed skills are skipped, and optional installation cannot turn a successful authentication into a failure. Redirected or noninteractive login never prompts; use `auth login --no-skill-offer` to suppress the offer explicitly. Run `higantic skills install` to revisit the catalog or `higantic skills install --yes` for deliberate noninteractive installation of every missing offered skill. The fixed skills.sh child process receives no HiGantic credential or custom-origin environment variables.

Issued keys are stored in macOS Keychain, Windows Credential Manager, or Linux Secret Service through a validated `secret-tool` executable. Profile metadata contains no key and is stored at `$XDG_CONFIG_HOME/higantic/config.json` or `~/.config/higantic/config.json` on Linux, `~/Library/Application Support/HiGantic/cli/config.json` on macOS, and `%APPDATA%\HiGantic\cli\config.json` on Windows.

Secure-storage failure is terminal. Protected-file storage is never selected automatically:

```bash
higantic auth login --storage file --allow-protected-file
```

POSIX protected storage enforces a user-owned, non-symlink `0700` directory and atomic `0600` file. Windows protected-file values use current-user DPAPI rather than plaintext. Pass `--allow-protected-file` again when using a profile configured with that storage.

Profile commands:

```bash
higantic auth status                 # validates remotely
higantic auth status --offline       # reads local metadata only
higantic auth use PROFILE
higantic auth logout                 # remote revoke, then local delete
higantic auth logout --local-only    # explicit local-only escape hatch
higantic auth import --stdin         # exactly one key line, remotely validated
higantic skills install              # review missing public skills one by one
```

Use global `--profile PROFILE` before an artifact command to override the current profile. Re-authentication is deliberately two-step: run `auth logout --profile PROFILE` so the exact old key is remotely revoked, then run login or import again. Logout confirms unless `--yes`, preserves the local credential when remote revocation fails, and never silently switches to another profile.

For CI/noninteractive use, set all three environment variables:

```bash
export HIGANTIC_API_BASE_URL="https://agent.higantic.com"
export HIGANTIC_AGENT_ID="your-agent-id"
export HIGANTIC_API_KEY="your-scoped-key"
```

If any member of the environment triple is set, all are required. A complete triple wins and is never combined with a profile destination or agent. The exact official origin is accepted by default. A trusted custom HTTPS origin requires `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1`; loopback HTTP additionally requires `HIGANTIC_ALLOW_INSECURE_LOCALHOST=1`. Destination validation happens before a profile secret is read, and cross-origin redirects are rejected.

Grant only the scopes needed:

- `html_artifacts:read` and `html_artifacts:write`
- `html_assets:read` and `html_assets:write`
- `html_pages:create` when page creation is required
- `html_artifacts:share` only for deliberate stable publication or pinned capability links

Never place a key in a repository, prompt, CLI argument, shell history, command transcript, or committed environment file. The CLI registers environment, profile, imported, and issued keys for process-local redaction and never prints them. It intentionally has no API-key argument.

Run `higantic --help` or `python3 scripts/higantic_html.py --help`. The launchers and modules support Python 3.9+ with no third-party dependencies.

## Operating model

1. Treat repository Markdown/code as source of truth and HTML as derivative.
2. Reuse a page by stable purpose/label and retain its ID. Use operation-specific idempotency keys only for exact create retries.
3. Use a stable page-unique artifact `externalId` for lookup/upsert and retain returned IDs.
4. Add visible provenance: repo-relative sources, branch plus commit/ref, generated/updated date, status, decisions, and a canonical-source note.
5. On exit code `3`, fetch the latest artifact/repository state and reconcile. Do not overwrite a newer revision or artifact version blindly.
6. Keep potentially shared artifacts free of secrets, credentials, personal/private data, and unpublished security details.

## Managed assets and deletion

```bash
python3 scripts/higantic_html.py assets list
python3 scripts/higantic_html.py assets upload --file ./hero.png
python3 scripts/higantic_html.py assets delete --asset-id ASSET_ID --confirm-delete
python3 scripts/higantic_html.py artifacts delete --page-id PAGE_ID --artifact-id ARTIFACT_ID --confirm-delete
```

Use `higantic-asset://<assetId>` as an HTML `<img src>`; never copy temporary storage URLs into artifacts. Artifact deletion cascades through revisions and shares. Asset deletion removes the live record while bytes referenced by a pinned share snapshot may remain until no references exist.

## Opt-in public visibility and pinned links

Artifacts remain private on create/upsert. Stable publication and pinned links require explicit commands, the non-default `html_artifacts:share` scope for writes, server-side sharing support, and confirmation before granting new public access. Publishing also requires a current revision and at most 100 managed images. Once public, HTML upsert, append, and restore require `--confirm-public-sharing`, the share scope, and the latest artifact version because they replace live content immediately; the backend checks these atomically.

```bash
python3 scripts/higantic_html.py visibility get --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py visibility set --page-id PAGE_ID --artifact-id ARTIFACT_ID --visibility public --confirm-public-sharing
python3 scripts/higantic_html.py visibility set --page-id PAGE_ID --artifact-id ARTIFACT_ID --visibility private
python3 scripts/higantic_html.py shares list --page-id PAGE_ID --artifact-id ARTIFACT_ID
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --revision 2 --expires-in-hours 24 --confirm-public-sharing
python3 scripts/higantic_html.py shares create --page-id PAGE_ID --artifact-id ARTIFACT_ID --expires-at-ms 1893456000000 --confirm-public-sharing
python3 scripts/higantic_html.py shares revoke --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-revoke
python3 scripts/higantic_html.py shares rotate --page-id PAGE_ID --artifact-id ARTIFACT_ID --share-id SHARE_ID --confirm-public-sharing
```

The stable `/p/{artifactId}` URL follows the current revision while public and stops resolving immediately when made private. Making it private does not revoke pinned links. Omit `--revision` on `shares create` to pin the current revision, and omit both expiration options for no expiration. Pinned capability links are unlisted but accessible to anyone with the link; the complete URL is shown only on create/rotate and cannot be recovered later. If sharing is unavailable, affected commands fail with `share_management_unavailable` and exit code `2`.
