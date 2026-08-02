# Static HTML contract

Produce one complete document with `<!doctype html>`, `<html>`, `<head>`, inline `<style>`, and `<body>`.

Use semantic HTML, responsive CSS, system font stacks, accessible contrast, visible focus where relevant, concise labels, and layouts that remain readable on narrow screens.

Repository Markdown and code are canonical. The artifact is derivative and must include a visible provenance section containing:

- repo-relative source paths (never local absolute paths)
- branch and commit SHA, tag, or other explicit ref
- generated or last-updated date
- current status and the decisions represented
- a short statement that repository sources remain canonical

If a fact cannot be tied to current repository source, label it as an assumption or recommendation. Do not let a stale artifact silently override newer code or documentation.

Allowed content is static HTML and inline CSS. Credential-free absolute HTTPS links are retained and forced to open safely in a new tab. Images may use `higantic-asset://<assetId>` references returned by `assets list`/`assets upload`; data-image sources may survive for compatibility, but managed assets are preferred.

Do not include JavaScript, event handlers, forms or form controls, HTTP/relative/credential-bearing links, iframes, objects, embeds, SVG, canvas, audio/video, arbitrary remote images/fonts/assets, CSS `url()`, `@import`, meta refresh, or arbitrary CSP. HiGantic sanitizes all writes and renders them in an opaque sandbox; only managed image storage origins and user-initiated safe HTTPS links are available.

Do not include API keys, access tokens, passwords, connection strings, private customer or personal data, confidential source excerpts, unpublished vulnerabilities, internal-only URLs with credentials, or other sensitive data. Capability shares are unlisted, not private: anyone with the URL can read the pinned artifact. Create a sanitized derivative before sharing when necessary.

Static controls must look explanatory rather than interactive. Use cards, tables, timelines, status badges, diagrams built from HTML/CSS, decision logs, risks, and acceptance checklists where they improve review.

Translate dynamic design ideas into honest static equivalents: use semantic tables or proportional CSS bars instead of canvas/SVG charts; visible sections or comparison columns instead of tabs and accordions; inline annotations and legends instead of hover-only explanations; and numbered stages, small multiples, or before/after panels instead of animation. Use system font stacks and make one subject-specific HTML/CSS element carry the visual identity rather than relying on remote assets or generic dashboard decoration.

Preflight the exact file passed to `--html-file`:

- every CSS custom property used is declared, with a safe fallback where useful
- foreground/background contrast, type size, line length, and dense data remain readable
- the narrow-screen layout has no clipped content, tiny columns, or horizontal dependency
- there are no unsupported elements, attributes, remote dependencies, motion-dependent meanings, or fake controls
- labels, evidence, status, provenance, title, and summary describe the artifact that will actually be saved

After a write, inspect `revision.sanitization`. If `removedCount` is nonzero, replace the reported kinds with static equivalents and submit at most one corrected revision/upsert. Inspect the second result and report any remaining removals; do not retry indefinitely or claim stripped content survived.
