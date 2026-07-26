# Changelog

## Unreleased

- Hardened API destination validation and redirect handling for bearer credentials.
- Reject unsafe or recursively encoded resource path segments before any API request.
- Kept maintainer-only tests and evals outside the installable skill payload.
- Narrowed skill activation to explicit HiGantic destinations and management requests.

## Initial public release — 2026-07-26

- Added the `higantic-html-artifacts` skill for creating and maintaining safe, versioned static HTML reports in HiGantic.
- Included a dependency-free Python CLI for pages, artifacts, revisions, managed assets, private URLs, and explicit opt-in capability sharing.
- Added optimistic concurrency, output redaction, destructive-operation confirmation, static HTML safety guidance, tests, evals, and repository validation.
