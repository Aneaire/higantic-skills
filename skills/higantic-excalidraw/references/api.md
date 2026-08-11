# Direct Excalidraw API

Base route: `/v1/agents/{agentId}/excalidraw-pages`. Use `Authorization: Bearer <key>` only.

| Method | Route | Scope |
|---|---|---|
| GET | `/excalidraw-pages` | `excalidraw:read` |
| POST | `/excalidraw-pages` | `excalidraw_pages:create` |
| GET | `/excalidraw-pages/{pageId}/scenes` | `excalidraw:read` |
| POST | `/excalidraw-pages/{pageId}/scenes` | `excalidraw:write` |
| GET | `/excalidraw-pages/{pageId}/scenes/{sceneId}` | `excalidraw:read` |
| PUT | `/excalidraw-pages/{pageId}/scenes/{sceneId}` | `excalidraw:write` |
| DELETE | `/excalidraw-pages/{pageId}/scenes/{sceneId}` | `excalidraw:write` |
| GET | `/excalidraw-pages/{pageId}/scenes/{sceneId}/visibility` | `excalidraw:read` |
| PUT | `/excalidraw-pages/{pageId}/scenes/{sceneId}/visibility` | `excalidraw:share` |

New scenes are private. Scene responses include the private workspace `url`, stable `publicUrl`, and `visibility`. Publishing requires `confirmPublicSharing: true`; replacing a public scene requires `excalidraw:share` plus `confirmPublicWrite: true`.

Create and replace accept exactly one of `flowchart` or `scene`. Replace also requires `expectedVersion`. Delete requires `If-Match: <version>` and `X-Confirm-Delete: true`.

Flowcharts support at most 100 nodes and 200 edges. Scene JSON is limited to the HiGantic Canvas storage contract. Responses use `{ "data": ..., "requestId": "..." }`; errors use `{ "error": { "code": "...", "message": "...", "details": ... }, "requestId": "..." }` and are not cached.

`409 scene_version_conflict` means the current version changed. Read the scene, reconcile, and retry with the newly observed version. Do not automate blind retries. Each key is limited to 120 requests per minute including no more than 30 writes.
