# Public Listings

This file is the public listing source of truth for submission status, manual
action items, approval URLs, and post-approval operations.

Before submitting to a public directory, run:

```bash
pnpm run submission:check
```

For final production screenshots, also run:

```bash
SUBMISSION_MODE=1 pnpm run submission:check
```

## Current Release Readiness Snapshot

Version numbers are intentionally omitted here so this living document does not
drift out of date. The authoritative version lives in `pyproject.toml` /
`src/kicad_mcp/__init__.py`; each release captures a version-pinned evidence
snapshot in a dated `release-readiness-<date>.md` document.

| Item | Status | Evidence |
|---|---|---|
| Release line | Validated per release | Latest dated [`release-readiness-*.md`](.) snapshot |
| PyPI package | Verified | `kicad-mcp-pro` current release present in PyPI JSON metadata |
| npm wrapper | Verified | `kicad-mcp-pro` current release present in npm registry metadata |
| GHCR image | Verified | `ghcr.io/oaslananka/kicad-mcp-pro:<version>` returns a multi-arch OCI index |
| Public screenshots | Verified | `docs/assets/screenshots/` contains six 1920x1080 public-listing images, including the fixture-only ChatGPT App dashboard |
| ChatGPT App E2E | Verified | Real MCP SDK connection, exact read-only tool catalog, widgets, restart, and reconnection pass in `npm run test:smoke` |
| Demo media | Required before each external form | `docs/assets/demo.cast` and `docs/assets/demo.gif` are checked by submission preflight |
| Privacy URL | Required before each external form | `https://oaslananka.github.io/kicad-mcp-pro/privacy/` |
| Support URL | Required before each external form | `https://github.com/oaslananka/kicad-mcp-pro/issues` |

## Submission Log

| Target | Status | Submitted UTC | Approved UTC | Listing URL | Notes |
|---|---|---:|---:|---|---|
| Anthropic Connector Directory | Not submitted | — | — | — | Run the full checklist in `docs/submission/anthropic-directory.md` first. |
| ChatGPT Apps | Not submitted | — | — | — | Requires platform domain verification before final form submission. |
| OpenAI/MCP Registry | Not submitted | — | — | — | Run registry dry-run and final submission checks first. |

## Manual Controls

- Record external submission status only in this file.
- Do not copy private reviewer messages into public issues.
- Do not submit screenshots or logs containing secrets, private board files,
  local auth state, or private absolute paths.
- Open a GitHub issue for any required repository change from a reviewer and
  close it only after this source-of-truth file is updated.
