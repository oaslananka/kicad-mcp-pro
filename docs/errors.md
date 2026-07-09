# Error Code Catalog

Every error KiCad MCP Pro surfaces to a client carries a stable machine-readable
payload (`code`, `message`, `hint`, `retryable`, `transient_class`, `retry_after_ms`).
This page is the authoritative catalog of those codes. It is kept in sync with
`src/kicad_mcp/errors.py` by `tests/unit/test_error_catalog.py`.

## How to read this catalog

- **retryable** — whether retrying the *same* call can succeed.
- **transient_class** — *why* it is retryable and how to retry:
  - `network` / `timeout` / `lock` — a transient fault; back off `retry_after_ms` (or a
    short delay) and retry, but only if the tool is idempotent (`idempotentHint: true`).
  - `state` — a precondition is unmet; reconcile first (e.g. open a board), then retry.
  - `none` — not transient; fix the request or configuration.
- **retry_after_ms** — suggested backoff before retrying a transient error.

See the `error_recovery` workflow prompt for the agent retry rule, and
[`ARCHITECTURE.md`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/ARCHITECTURE.md)
for where errors are defined.

## Codes

| Code | Retryable | Transient class | Backoff (ms) | Meaning |
| --- | :---: | --- | ---: | --- |
| `KICAD_MCP_ERROR` | no | none | — | Generic domain error; inspect the request, project config, and diagnostics. |
| `KICAD_NOT_RUNNING` | yes | network | 1000 | KiCad IPC is not reachable. Start KiCad and enable the IPC API server, or run `doctor`. |
| `KICAD_CONNECTION_TIMEOUT` | yes | timeout | 2000 | KiCad IPC connection timed out. Increase `KICAD_MCP_TIMEOUT_MS` or verify the IPC API responds. |
| `IPC_DISCONNECTED` | yes | network | 1000 | The IPC connection was lost and reconnection failed. Re-open KiCad / enable the IPC API server. |
| `KICAD_BOARD_NOT_OPEN` | yes | state | — | KiCad is reachable but no board is open. Open a `.kicad_pcb` or set the active project, then retry. |
| `KICAD_VERSION_MISMATCH` | no | none | — | The detected KiCad version is unsupported. Install a supported version (see the compatibility matrix). |
| `KICAD_PROJECT_NOT_FOUND` | no | none | — | The configured project cannot be found. Set `KICAD_MCP_PROJECT_DIR` or call `kicad_set_project()`. |
| `UNSAFE_PATH` | no | none | — | A requested path escapes the workspace. Use a relative path inside `KICAD_MCP_WORKSPACE_ROOT` or the project. |
| `TOOL_VALIDATION_ERROR` | no | none | — | The request was invalid before touching external state. Correct the tool arguments and retry. |
| `EXTERNAL_TOOL_UNAVAILABLE` | no | none | — | A required external executable is unavailable. Install it or configure its path explicitly. |
| `SERVER_INITIALIZING` | yes | timeout | 2000 | Tool registration is still in progress (deferred startup). Retry in a moment. |
| `SCHEMATIC_WRITE_UNSAFE` | no | none | — | A schematic write would have dropped structure (e.g. a global label); the original was restored and the write refused rather than silently corrupting the file. |
| `MANUAL_STEP_REQUIRED` | yes | state | — | A workflow needs a one-time KiCad GUI step (e.g. applying a routed Specctra SES). Perform the described step, then retry. |
| `INTERNAL_ERROR` | no | none | — | An unexpected, non-domain exception was masked to a stable shape. Run `doctor` and retry with corrected configuration. |
| `CONFIGURATION_ERROR` | no | none | — | Malformed KiCad MCP configuration (raised by CLI/diagnostic commands). Fix the configuration and retry. |

## Recovery patterns

- **Transient (`network` / `timeout`)** — only auto-retry idempotent tools (read-only
  tools and converging writes such as `set_*`, `save`, `refill`, `export_*`, `*_upgrade`).
  For non-idempotent writes, read current state first (reconcile-then-retry).
- **`state` (board-not-open, manual-step)** — do the reconciling action (open the board,
  perform the GUI step); retrying without it will not help.
- **`none`** — the request or environment is wrong; use `hint` and fix it before retrying.
