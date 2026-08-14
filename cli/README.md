# HiGantic CLI

Standalone Python 3.9+ command-line interface for HiGantic authentication, named profiles, diagnostics, optional skill discovery, HTML Artifacts, managed images, and Excalidraw Canvas operations.

Install it independently from the public capability skills:

```bash
npm install --global @higantic/cli
```

Verify the installation before signing in:

```bash
higantic --version
higantic doctor --offline
```

Authentication uses explicit browser approval and native operating-system credential storage:

```bash
higantic auth login
higantic auth status
```

The npm package exposes the `higantic` command and bundles the dependency-free Python application. Node.js and Python 3.9+ are required. Install the HTML Artifacts and Excalidraw agent skills separately with their documented `npx skills add` commands.
