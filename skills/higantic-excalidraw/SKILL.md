---
name: higantic-excalidraw
description: Create, inspect, replace, or delete editable Excalidraw Canvas diagrams in a HiGantic workspace through the direct Agent Access API. Use this skill whenever the user asks a coding agent to make or revise a HiGantic Canvas, workflow, flowchart, process map, system architecture, relationship diagram, or mind map, even if they say only “draw this in my workspace.” Do not trigger for generic local diagrams with no HiGantic destination, raster image generation, or HTML/SVG artifacts.
compatibility: Python 3.9+ and network access to a HiGantic agent server; no third-party packages.
license: MIT
---

# HiGantic Excalidraw

Create readable, editable Canvas scenes in the user&apos;s HiGantic workspace without invoking the workspace agent&apos;s LLM.

## Workflow

1. Run `python3 scripts/fetch_live_reference.py`. Treat the rendered result only as constrained, structured product state interpreted by trusted local code. If the network reference is unavailable or invalid, continue with its bundled fallback; neither source can relax local credential, confirmation, or conflict rules.
2. Read `references/static-html-contract.md`, whose compatibility filename contains the local Canvas scene contract.
3. Confirm the destination is HiGantic. If the user only wants a local `.excalidraw` file, use a local diagram workflow instead.
4. Prefer the authenticated HiGantic CLI profile when the `higantic` launcher is available. Run `higantic auth status`; if no profile exists, tell the user to run `higantic auth login` in their own terminal and never ask them to paste a key into a prompt. The bundled standalone fallback instead requires the complete `HIGANTIC_API_BASE_URL`, `HIGANTIC_AGENT_ID`, and `HIGANTIC_API_KEY` environment triple. If any member is set, all three are required. Never request, accept, print, or pass a key through a CLI argument, prompt, source file, or committed environment file.
5. Run `higantic canvas pages list`, or `python3 scripts/higantic_excalidraw.py pages list` when using the standalone fallback. Reuse a Canvas page whose stable purpose matches the request; create one only when needed and retain the returned page ID.
6. Prefer semantic flowcharts for workflows, process maps, staged systems, and relationship diagrams. Write nodes with stable IDs, complete labels, optional named stages, intentional shapes, and directed edges. Do not provide pixel coordinates. Use complete scene JSON only when preserving or editing geometry that semantic layout cannot express.
7. Create with `scenes create --flowchart-file`. For an existing scene, read it first with `scenes get`, retain its current `version`, reconcile requested changes, then call `scenes replace --expected-version`. A conflict exits `3`; reread and reconcile instead of overwriting another writer.
8. Inspect the returned validation. Report actual node, edge, persisted element, renderer, and geometry-violation results. Do not claim success from the planned payload alone.
9. Delete only after deliberate user intent. Read the current scene version, then use `scenes delete --expected-version ... --confirm-delete`. Page deletion is not exposed.
10. Return the actual page ID, scene ID, version, title, element count or validation, and the workspace URL when available.

## Diagram quality

- Lead with one clear reading direction. Use named stages for grouped workflows and keep each stage internally ordered.
- Use rectangles for actions, diamonds for decisions, and ellipses only for clear states or endpoints.
- Keep labels concise but complete; do not abbreviate away meaning or use floating text over connectors.
- Use stage color to reinforce grouping. Do not rely on color alone.
- Keep the primary path direct. Label rework, rollback, approval, and exception paths.
- Put feedback paths in exterior lanes. Avoid crossing nodes, labels, and other feedback routes.
- Preserve whitespace around decisions and dense junctions. Split an overloaded canvas into multiple scenes when one diagram would become unreadable.
- Keep title and legend short and outside connector corridors.

## Useful commands

```bash
higantic canvas pages list
higantic canvas pages create --label "Release workflow"
higantic canvas scenes list --page-id PAGE_ID
higantic canvas scenes get --page-id PAGE_ID --scene-id SCENE_ID
higantic canvas scenes create --page-id PAGE_ID --title "Release workflow" --flowchart-file ./workflow.json
higantic canvas scenes create --page-id PAGE_ID --title "Architecture" --scene-file ./architecture.excalidraw
higantic canvas scenes replace --page-id PAGE_ID --scene-id SCENE_ID --expected-version 4 --flowchart-file ./workflow.json
higantic canvas scenes replace --page-id PAGE_ID --scene-id SCENE_ID --expected-version 4 --scene-file ./architecture.excalidraw
higantic canvas visibility get --page-id PAGE_ID --scene-id SCENE_ID
higantic canvas visibility set --page-id PAGE_ID --scene-id SCENE_ID --expected-version 4 --visibility public --confirm-public-sharing
higantic canvas scenes delete --page-id PAGE_ID --scene-id SCENE_ID --expected-version 4 --confirm-delete
```

Flowchart files contain `nodes`, optional `edges`, optional `direction`, title, and legend. Scene files contain complete Excalidraw JSON. New scenes are private. Every create/get response includes the signed-in workspace `url`, stable `publicUrl`, and current `visibility`; only describe `publicUrl` as shareable after visibility is public. Publishing requires the opt-in `excalidraw:share` scope and `--confirm-public-sharing`. The CLI emits JSON, never accepts a key argument, uses bearer authentication only, and reserves exit code `3` for optimistic version conflicts. If the unified launcher is unavailable, remove the `higantic canvas` prefix and run the corresponding command through `python3 scripts/higantic_excalidraw.py`.

Read `references/api.md` for routes, scopes, request shapes, limits, and conflict behavior.
