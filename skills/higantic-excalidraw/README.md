# HiGantic Excalidraw skill

Portable coding-agent skill for creating and maintaining editable Excalidraw Canvas scenes through HiGantic Agent Access.

The installed skill checks the closed-schema product reference at `https://skills.higantic.com/v1/manifest.json` and `https://skills.higantic.com/v1/references/higantic-excalidraw.json`. Trusted local code renders only allowlisted structured fields and uses the identical bundled fallback when the network is unavailable; live data never changes credential, confirmation, deletion, or conflict safeguards.

## Install

```bash
npx skills add Aneaire/higantic-skills --skill higantic-excalidraw
```

Add `--global` for a global installation.

## Configure Agent Access

In HiGantic, open the target agent&apos;s **Settings → Excalidraw** section. Review the Canvas design instructions and generate a dedicated scoped key. Store the key outside source control:

```bash
export HIGANTIC_API_BASE_URL="https://agent.higantic.com"
export HIGANTIC_AGENT_ID="your-agent-id"
export HIGANTIC_API_KEY="your-scoped-key"
```

Scopes:

- `excalidraw:read` — list pages/scenes and read complete scene JSON.
- `excalidraw:write` — create, replace, and delete scenes.
- `excalidraw_pages:create` — create Canvas pages.

The API key is never accepted as a command argument. Keep it in an operating-system or CI secret store and out of prompts, logs, repositories, and committed environment files.

## First workflow

```bash
higantic auth status
higantic canvas pages list
higantic canvas pages create --label "Release workflow"
higantic canvas scenes create \
  --page-id PAGE_ID \
  --title "Release workflow" \
  --flowchart-file ./workflow.json
```

The unified `higantic` launcher uses secure named profiles and browser device login. If it is not installed, the skill remains self-contained: use `python3 scripts/higantic_excalidraw.py ...` with the environment triple above.

Example `workflow.json`:

```json
{
  "title": "Release workflow",
  "direction": "left-to-right",
  "nodes": [
    { "id": "plan", "label": "Plan release", "stage": "Planning" },
    { "id": "build", "label": "Build candidate", "stage": "Build" },
    { "id": "approve", "label": "Approve release", "stage": "Verification", "shape": "diamond" }
  ],
  "edges": [
    { "from": "plan", "to": "build" },
    { "from": "build", "to": "approve" },
    { "from": "approve", "to": "build", "label": "rework" }
  ]
}
```

Read a scene before replacing it and pass the returned `version`. Conflict exit code `3` means another writer changed the scene; reread and reconcile. Deletion requires both the latest version and `--confirm-delete`.
