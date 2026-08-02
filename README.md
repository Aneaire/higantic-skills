# HiGantic Skills

Public agent skills for creating clear, reviewable work in HiGantic. These skills are designed for coding agents and keep repository source material canonical while producing useful derivative artifacts for human review.

## Available skills

### `higantic-html-artifacts`

Creates and maintains safe, versioned, static HTML artifacts when a user explicitly chooses a HiGantic workspace, page, or artifact as the destination. It does not activate for generic report or visualization requests with no HiGantic destination.

The included dependency-free Python CLI supports stable page and artifact identity, optimistic concurrency, managed images, explicit deletion safeguards, and opt-in capability sharing.

## Branded live references

Installed skills can read current product state without accepting mutable remote prose or instructions. The maintained source manifest is `site/v1/manifest.source.json`; the deterministic build publishes `https://skills.higantic.com/v1/manifest.json` and the closed-schema HTML Artifacts reference at `https://skills.higantic.com/v1/references/higantic-html-artifacts.json`.

Each manifest-declared skill packages `scripts/fetch_live_reference.py`, `references/live-reference.json`, and `references/live-reference-fallback.json`. The canonical local config supplies that skill's installed version and exact URLs. The dependency-free fetcher disables environment proxies, sends no API key, cookies, Authorization header, or environment-derived headers, and validates exact paths, same-origin redirect policy, 64 KiB size limits, duplicate keys, ASCII-only constrained strings, fixed identifier allowlists, booleans, nonnegative integer limits, timestamps, semantic versions, and SHA-256 consistency. Remote bytes are never printed. Trusted installed code renders validated state through fixed local text; failures render the structured bundled fallback through the same renderer.

The source manifest and generated manifest are each limited to 64 KiB, as is every source/generated reference. Live structured state cannot override installed `SKILL.md` safety, approval, credential, destination, destructive-action, or sharing rules. A newer executable contract requires `npx skills update <skill-slug>`. This convention is required for future skills, while installable payloads remain limited to `SKILL.md`, `README.md`, `scripts/`, and `references/`.

## Install with skills.sh

The permanent source for this collection is `Aneaire/higantic-skills`. The commands below use the `skills` CLI through `npx`; this repository does not claim or require a separately published HiGantic npm package.

Install only the HTML Artifacts skill into the current project:

```bash
npx skills add Aneaire/higantic-skills --skill higantic-html-artifacts
```

Install every skill in the collection for every detected agent:

```bash
npx skills add Aneaire/higantic-skills --all
```

Install the HTML Artifacts skill globally:

```bash
npx skills add Aneaire/higantic-skills --skill higantic-html-artifacts --global
```

Install all skills globally:

```bash
npx skills add Aneaire/higantic-skills --all --global
```

You can review available skills before installation with:

```bash
npx skills add Aneaire/higantic-skills --list
```

## Prerequisites

- Node.js with `npx` available for installation through skills.sh.
- Python 3.9 or newer to run `higantic-html-artifacts`.
- Network access from the coding agent to your HiGantic agent server.
- A HiGantic agent ID and a scoped agent API key.

The skill has no third-party Python dependencies.

## Credentials, profiles, and scopes

For interactive use, place the skill's scripts directory on `PATH` and use browser-approved profile login:

```bash
export PATH="$PWD/skills/higantic-html-artifacts/scripts:$PATH"
higantic auth login
higantic auth status
```

On Windows PowerShell, add the same scripts directory to the current session and use the included `.cmd` launcher:

```powershell
$env:Path = "$PWD\skills\higantic-html-artifacts\scripts;$env:Path"
higantic auth login
higantic auth status
```

The literal command is `higantic auth login` when that directory is on `PATH`; no package publication or global Python installation is required. Login shows a ten-minute code and URL on stderr, requires explicit browser approval for one agent and a reviewed scope subset, then stores the issued key in the native OS credential store:

- macOS Keychain through the Security framework.
- Windows Credential Manager.
- Linux Secret Service through a validated `secret-tool` executable, with the key passed on stdin.

After a successful login in an interactive terminal, the CLI offers to review any missing public HiGantic skills. Entering the catalog is optional, and every missing skill receives its own yes/no prompt before the CLI runs the fixed global skills.sh installer command. Already-installed skills are skipped. Login never fails merely because an optional installation is declined or fails, and redirected/noninteractive login never prompts. Use `--no-skill-offer` to suppress the post-login offer explicitly.

Review the installed catalog again at any time:

```bash
higantic skills install
```

The command prints a short English summary by default. Use `higantic skills install --json` when a script needs the structured result. Use `higantic skills install --yes` only when you deliberately want to install every missing offered skill noninteractively. The child installer receives none of the `HIGANTIC_*` credential or custom-origin variables. Node.js with `npx` is required only when a missing skill is actually selected for installation. The current public catalog contains `higantic-html-artifacts`, so an installation that already includes this CLI reports it as installed until more public HiGantic skills are released.

Profile metadata contains no secrets and lives at `$XDG_CONFIG_HOME/higantic/config.json` or `~/.config/higantic/config.json` on Linux, `~/Library/Application Support/HiGantic/cli/config.json` on macOS, and `%APPDATA%\HiGantic\cli\config.json` on Windows.

Secure storage fails closed. Protected-file storage is never automatic and requires both flags:

```bash
higantic auth login --storage file --allow-protected-file
```

The protected file uses a private `0700` directory and atomic `0600` file on POSIX; Windows encrypts values with current-user DPAPI. Commands using a protected-file profile must also pass `--allow-protected-file`.

Use `higantic auth use PROFILE` to select a current profile, `higantic --profile PROFILE ...` for one artifact command, `higantic auth status --offline` for local metadata, and `higantic auth logout` to revoke the current key before local deletion. Re-authentication requires logout first so an old key is never abandoned. `higantic auth import --stdin` accepts exactly one key line for controlled migration and validates it remotely; keys are never accepted as arguments or printed.

For CI and noninteractive automation, set the complete environment triple:

```bash
export HIGANTIC_API_BASE_URL="https://agent.higantic.com"
export HIGANTIC_AGENT_ID="your-agent-id"
export HIGANTIC_API_KEY="your-scoped-key"
```

If any variable in the triple is set, all three are required. A complete triple wins over profiles and is never combined with a profile key. Never place an API key in a repository, prompt, CLI argument, shell history, command transcript, or committed environment file.

The CLI accepts the exact official origin `https://agent.higantic.com` by default and validates the destination before reading a key. A trusted non-official HTTPS origin requires explicit opt-in:

```bash
export HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1
export HIGANTIC_API_BASE_URL="https://trusted-api.example.com"
```

This flag allows the API key to be sent to the configured custom origin, so enable it only for infrastructure you control and trust. Plain HTTP is rejected except for `127.0.0.1`, `localhost`, or `::1`, and local development additionally requires both flags:

```bash
export HIGANTIC_ALLOW_CUSTOM_API_BASE_URL=1
export HIGANTIC_ALLOW_INSECURE_LOCALHOST=1
export HIGANTIC_API_BASE_URL="http://127.0.0.1:8080"
```

Never use the insecure-localhost override for remote or production services. Cross-origin redirects are rejected so the Authorization header cannot follow a redirect to another origin.

Grant only the scopes required for the intended operation:

- `html_artifacts:read` and `html_artifacts:write` for artifacts and revisions.
- `html_assets:read` and `html_assets:write` for managed images.
- `html_pages:create` only when the agent must create a page.
- `html_artifacts:share` only for deliberate public capability-link operations.

Public sharing is never automatic. It requires explicit user intent, the non-default sharing scope, server-side support, and a confirmation flag. Replacing already-public content additionally binds that acknowledgement to the observed artifact version in the same backend transaction. Capability links are unlisted rather than access-controlled, so sanitize an artifact before sharing it.

## Updates

Update the project-installed skill from its recorded source:

```bash
npx skills update higantic-html-artifacts
```

Update a global installation:

```bash
npx skills update higantic-html-artifacts --global
```

Review upstream changes and rerun your repository's checks before relying on a newly updated skill in sensitive workflows.

## Development

Run the complete local validation suite from the repository root:

```bash
node scripts/build-site.mjs
node scripts/test-site.mjs
python3 -m unittest discover -s tests/higantic-html-artifacts -p 'test_*.py'
python3 -m py_compile skills/higantic-html-artifacts/scripts/*.py scripts/validate_repository.py tests/higantic-html-artifacts/*.py
python3 -m json.tool site/v1/manifest.source.json >/dev/null
python3 -m json.tool site/v1/references/higantic-html-artifacts.json >/dev/null
python3 -m json.tool skills/higantic-html-artifacts/references/live-reference.json >/dev/null
python3 -m json.tool skills/higantic-html-artifacts/references/live-reference-fallback.json >/dev/null
python3 -m json.tool dist/v1/manifest.json >/dev/null
python3 -m json.tool dist/v1/references/higantic-html-artifacts.json >/dev/null
python3 scripts/validate_repository.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution requirements, [SECURITY.md](SECURITY.md) for private vulnerability reporting guidance, and [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

Licensed under the [MIT License](LICENSE).
