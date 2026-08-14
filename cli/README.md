# HiGantic CLI

Standalone Python 3.9+ command-line interface for HiGantic authentication, named profiles, diagnostics, optional skill discovery, HTML Artifacts, managed images, and Excalidraw Canvas operations.

Install it independently from the public capability skills:

```bash
npm install --global @higantic/cli
```

Confirm the installation and review every public HiGantic skill:

```bash
higantic setup
```

Each missing skill has its own `[Y/n]` prompt; pressing Enter installs it. For a deliberate noninteractive installation of every missing skill, run `higantic setup --yes`.

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

The npm package exposes the `higantic` command and bundles the dependency-free Python application. Node.js and Python 3.9+ are required. HTML Artifacts and Excalidraw remain separate agent-skill installations even when `higantic setup` offers both together.
