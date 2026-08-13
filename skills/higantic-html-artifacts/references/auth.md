# Device authentication check

Verify that a device is authenticated before artifact work, and re-check whenever the CLI reports a profile, credential, or storage error. A profile is a named browser-approved credential stored in the OS credential store; it is the default way the CLI authenticates. The complete `HIGANTIC_API_BASE_URL` / `HIGANTIC_AGENT_ID` / `HIGANTIC_API_KEY` environment triple is the CI/noninteractive override and wins over profiles when fully set.

## Confirm the device is signed in

```bash
higantic auth status            # validates the active profile against the API
higantic auth status --offline  # reads local profile metadata only, no network
higantic auth profiles          # lists non-secret profile metadata, marks active
higantic doctor                 # read-only CLI, credential, storage, and API checks
higantic doctor --offline       # same, skipping the authenticated API check
higantic --version              # confirms the CLI is installed and runnable
```

Interpretation:

- `auth status` prints `Authenticated` with the agent, profile, check mode (`remote` or `offline`), API base URL, and granted scopes. A remote check reaches `GET /v1/auth/status` with the stored key.
- `auth profiles` lists only non-secret metadata and never reads stored keys; the active profile is marked. If it reports no profiles yet, sign in first.
- `doctor` runs checks for the CLI version, environment override, protected configuration, credential availability, authenticated API connectivity, the selected asset-storage target, secure-storage provider when relevant, and optional `npx` dependency. It prints `PASS`/`WARN`/`FAIL` per check, never prints a key, and exits nonzero only when a check fails. Missing optional setup is a warning.
- Named profiles may store a non-secret `assetDefaults.target` value of `higantic` or `uploadthing`. Existing version-1 configuration migrates in memory and defaults to `higantic`; the next write saves version 2. Complete environment credentials have no profile to mutate, default to `higantic`, and may use a one-command `--target` override.
- All auth commands print concise English by default; pass `--json` for structured output for scripts. JSON login suppresses the optional skill catalog.

## Signing in

```bash
export PATH="$PWD/scripts:$PATH"   # or use the installed scripts/ directory
higantic auth login                # ten-minute browser approval flow
```

Login preflights secure storage, shows a ten-minute browser verification URL and code, reports the approval wait and expiry, and waits for explicit approval of one active agent and a reviewed scope subset. Standard private artifact and Canvas scopes are requested by default; the high-trust `html_artifacts:share` and `assets:share` scopes are requested only with explicit repeated `--scope` flags and are never preselected. After success, the CLI may offer to review missing public skills; each install is optional and has its own confirmation. Use `--no-skill-offer` to suppress the offer.

Issued keys are stored in macOS Keychain, Windows Credential Manager, or Linux Secret Service and are returned once; the CLI never prints them and has no API-key argument. Never ask a user to paste a key into a prompt. Protected-file storage is explicit only with `--storage file --allow-protected-file`.

## Profiles

```bash
higantic auth use PROFILE             # select the active profile
higantic <command> --profile PROFILE  # per-command profile override
higantic auth logout                  # remote revoke, then local delete
higantic auth logout --local-only     # explicit local-only escape hatch
higantic auth import --stdin          # exactly one key line, remotely validated
```

Profile metadata contains no key and lives at `$XDG_CONFIG_HOME/higantic/config.json` or `~/.config/higantic/config.json` on Linux, `~/Library/Application Support/HiGantic/cli/config.json` on macOS, and `%APPDATA%\HiGantic\cli\config.json` on Windows. When login finds an existing profile, it explains how to inspect it, revoke and replace its API key safely, or create another named profile; it never silently overwrites a credential. Re-authentication is deliberately two-step: `auth logout --profile PROFILE` first so the exact old key is revoked, then login or import again. Logout confirms unless `--yes`, preserves the local credential when remote revocation fails, and never silently switches profiles.

## CI / noninteractive override

```bash
export HIGANTIC_API_BASE_URL="https://agent.higantic.com"
export HIGANTIC_AGENT_ID="your-agent-id"
export HIGANTIC_API_KEY="your-scoped-key"
```

If any member of the triple is set, all three are required, and the complete triple wins without mixing with a profile destination or agent. The exact official HTTPS origin is accepted by default; a trusted custom HTTPS origin requires `HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1`, and loopback HTTP additionally requires `HIGANTIC_ALLOW_INSECURE_LOCALHOST=1`. Never place a key in a repository, prompt, CLI argument, shell history, or committed environment file.

## Scope checklist

Grant only the scopes needed:

- `html_artifacts:read` and `html_artifacts:write`
- `assets:read` and `assets:write`
- `assets:share` only for explicit standalone image publication or deletion of an already-public image
- `html_pages:create` when page creation is required
- `excalidraw:read` and `excalidraw:write`
- `excalidraw:share` only when stable Canvas viewer links must be published
- `excalidraw_pages:create` when Canvas page creation is required
- `html_artifacts:share` only for deliberate stable publication or pinned capability links

Existing keys may report legacy `html_assets:*` grants; the server keeps those grants compatible on asset routes, while CLI 1.8.0 requests canonical `assets:*` scopes.

## Common errors

- `profile_not_selected` → run `higantic auth profiles`, then `higantic auth use PROFILE` or `higantic auth login`.
- `profile_not_found` → run `higantic auth profiles`, or create one with `higantic auth login --profile NAME`.
- `credential_not_found` → run `higantic doctor` to check secure storage; if a profile is broken, remove that exact profile with `higantic auth logout --profile PROFILE --local-only` and sign in again.
- `secure_storage_unavailable` → run `higantic doctor` for the failing credential-store dependency and suggested setup.
- `incomplete_environment` → set all three environment variables or unset all three.
- `environment_override_active` → unset the triple before managing named profiles.
- `invalid_api_key` → run `higantic doctor`; sign in again if the stored or environment key is no longer valid.
- `expired_token` / `authorization_denied` / `access_denied` → run `higantic auth login` again for a new ten-minute approval session.
- `connection_error` → check the network and run `higantic doctor` to test the configured API.
