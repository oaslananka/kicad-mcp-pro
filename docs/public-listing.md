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

| Item | Status | Evidence |
|---|---|---|
| Release line | Ready for 3.17.1 validation | [`release-readiness-2026-07-03.md`](release-readiness-2026-07-03.md) |
| PyPI package | Verified | `kicad-mcp-pro` 3.17.1 present in PyPI JSON metadata |
| npm wrapper | Verified | `kicad-mcp-pro` 3.17.1 present in npm registry metadata |
| GHCR image | Verified | `ghcr.io/oaslananka/kicad-mcp-pro:3.17.1` returns a multi-arch OCI index |
| Public screenshots | Ready for automated final-check mode | `docs/assets/screenshots/` contains five 1920x1080 public-listing images |
| Demo media | Required before each external form | `docs/assets/demo.cast` and `docs/assets/demo.gif` are checked by submission preflight |
| Privacy URL | Required before each external form | `https://oaslananka.github.io/kicad-mcp/privacy/` |
| Support URL | Required before each external form | `https://github.com/oaslananka/kicad-mcp/issues` |

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
