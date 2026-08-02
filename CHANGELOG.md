# Changelog

## Unreleased

- Added `higantic skills install` plus an optional post-login catalog that skips installed skills, confirms each missing skill separately, remains silent in noninteractive sessions, and strips HiGantic credential variables from the cross-platform skills.sh child process.
- Replaced agent-consumed mutable Markdown with closed-schema structured JSON at `https://skills.higantic.com/v1/references/higantic-html-artifacts.json`; remote bytes and arbitrary prose are never printed, and fixed installed renderer text remains subordinate to local skill safeguards.
- Added canonical per-skill `references/live-reference.json` configuration, structured fallback rendering, duplicate-key/ASCII/Unicode/allowlist/type/path/version/size validation, and SHA-256 consistency checking without authentication claims.
- Enforced matching 64 KiB publisher/client limits for source/generated manifests and references, deterministic oversize build tests, behavior-based repository validation, mocked-network/config/Unicode/rendering tests, Node 24 CI coverage, and the reusable convention for future skills.
- Hardened API destination validation and redirect handling for bearer credentials.
- Reject unsafe or recursively encoded resource path segments before any API request.
- Kept maintainer-only tests and evals outside the installable skill payload.
- Narrowed skill activation to explicit HiGantic destinations and management requests.
- Bound public-content replacement confirmation and artifact-version preconditions to the backend write, and switched artifact/revision links to API-returned dedicated viewer URLs.

## Initial public release — 2026-07-26

- Added the `higantic-html-artifacts` skill for creating and maintaining safe, versioned static HTML reports in HiGantic.
- Included a dependency-free Python CLI for pages, artifacts, revisions, managed assets, private URLs, and explicit opt-in capability sharing.
- Added optimistic concurrency, output redaction, destructive-operation confirmation, static HTML safety guidance, tests, evals, and repository validation.
