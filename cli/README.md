# HiGantic CLI

Standalone Python 3.9+ command-line interface for HiGantic authentication, named profiles, diagnostics, optional skill discovery, HTML Artifacts, managed images, and Excalidraw Canvas operations.

Install it independently from the public capability skills, then immediately start the guided skill setup:

```bash
npm install --global @higantic/cli && higantic setup
```

Setup confirms the installation. Each missing skill has its own `[Y/n]` prompt; pressing Enter installs it. For a deliberate noninteractive installation of every missing skill, run `higantic setup --yes`.

The interactive display uses a compact setup panel and a numbered rail so it is easy to see which skill is being reviewed:

```text
╭─ HiGantic setup
│  ✓ CLI 1.8.3 ready
│
│  Command        higantic
│  Public skills  3
╰────────────────────────

Choose optional agent skills
Enter installs · n skips

01/03  HTML Artifacts
       Create and maintain safe, versioned HTML artifacts in HiGantic.
       Install globally? [Y/n]
```

Color is used only in an interactive terminal. `NO_COLOR` and limited terminal encodings receive the same hierarchy without ANSI color and with ASCII-safe symbols.

Check the version and local diagnostics at any time:

```bash
higantic --version
higantic doctor --offline
```

Authentication uses explicit browser approval and native operating-system credential storage:

```bash
higantic auth login
higantic auth status
```

The npm package exposes the `higantic` command and bundles the dependency-free Python application. Node.js and Python 3.9+ are required. HTML Artifacts, Managed Assets, and Excalidraw remain separate agent-skill installations even when `higantic setup` offers all three together.
