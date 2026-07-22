# MCP 2026-07-28 Compatibility Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, fail-closed MCP `2026-07-28` stateless Streamable HTTP compatibility lane while preserving the stable `2025-11-25` runtime and registry contract.

**Architecture:** A pure protocol compatibility module validates and adapts candidate envelopes at the ASGI boundary. Configuration keeps the lane non-default, fixtures pin the draft contract, and an independent CI job proves candidate behavior without upgrading the production MCP SDK.

**Tech Stack:** Python 3.13, Pydantic Settings, Starlette ASGI, FastMCP/MCP Python SDK 1.x, pytest, JSON fixtures, GitHub Actions.

## Global Constraints

- Default protocol lane remains `stable` and `MCP_PROTOCOL_VERSION` remains `2025-11-25`.
- Candidate protocol version is exactly `2026-07-28` and config selector is exactly `2026-07-28-rc`.
- Candidate mode supports only stateless Streamable HTTP.
- Candidate mode must reject legacy SSE, stateful sessions, and the legacy Tasks implementation.
- `server.json` must continue advertising only `2025-11-25`.
- Do not upgrade the production `mcp[cli]>=1.27.1,<2.0.0` dependency range.
- Preserve authentication failures before protocol-specific validation.

---

### Task 1: Pin the candidate contract and fail-closed configuration

**Files:**
- Create: `tests/contracts/mcp/2026-07-28/provenance.json`
- Create: `tests/contracts/mcp/2026-07-28/server-discover.request.json`
- Create: `tests/contracts/mcp/2026-07-28/server-discover.response.json`
- Create: `tests/contracts/mcp/2026-07-28/tools-list.request.json`
- Create: `tests/contracts/mcp/2026-07-28/tools-list.response.json`
- Modify: `src/kicad_mcp/config.py`
- Create: `tests/unit/test_mcp_2026_config.py`

**Interfaces:**
- Produces: `KiCadMCPConfig.protocol_lane: Literal["stable", "2026-07-28-rc"]`.

- [ ] Write fixture and config tests requiring exact draft provenance, stable default, environment/config selection, and rejection of candidate mode with stdio, SSE, stateful HTTP, legacy SSE, or legacy Tasks.
- [ ] Run `uv run pytest tests/unit/test_mcp_2026_config.py -q` and confirm the configuration tests fail because `protocol_lane` does not exist.
- [ ] Add the minimal config field, normalization, and after-validator checks.
- [ ] Re-run focused tests and confirm success.
- [ ] Commit with `feat(mcp): gate the 2026 compatibility lane`.

### Task 2: Implement pure candidate protocol contracts

**Files:**
- Create: `src/kicad_mcp/protocol_compat.py`
- Create: `tests/unit/test_protocol_compat.py`

**Interfaces:**
- Produces: `ProtocolValidationError`, `validate_candidate_request(headers, payload)`, `candidate_discover_result(...)`, `stable_sdk_request(payload)`, and `decorate_candidate_response(method, payload, ...)`.

- [ ] Write failing unit tests for protocol/header/meta agreement, required `Mcp-Method`/`Mcp-Name`, session rejection, discovery output, stable-envelope translation, server identity, `resultType`, `ttlMs`, `cacheScope`, and error codes `-32020`, `-32021`, `-32022`.
- [ ] Run the focused tests and confirm failure because the module is absent.
- [ ] Implement pure functions with no FastMCP or ASGI dependency.
- [ ] Re-run focused tests and confirm success.
- [ ] Commit with `feat(mcp): define 2026 stateless protocol contracts`.

### Task 3: Bridge candidate Streamable HTTP requests

**Files:**
- Modify: `src/kicad_mcp/server.py`
- Create: `tests/unit/test_mcp_protocol_2026_contract.py`
- Modify: `tests/unit/test_mcp_protocol_contract.py` only for explicit stable non-regression assertions.

**Interfaces:**
- Consumes: pure contract functions from Task 2.
- Produces: live candidate `server/discover`, `tools/list`, and `tools/call` behavior over Streamable HTTP.

- [ ] Write failing ASGI tests for direct discovery/list/call without initialize, candidate metadata, missing/mismatched headers, rejected sessions/initialize, auth preservation, and stable-lane non-regression.
- [ ] Confirm the tests fail against the current middleware.
- [ ] Add a candidate-only middleware branch that buffers and rewrites request/response bodies while preserving the stable path.
- [ ] Re-run stable and candidate protocol suites.
- [ ] Commit with `feat(mcp): bridge 2026 requests at the HTTP boundary`.

### Task 4: Add independent CI and registry guards

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/unit/test_mcp_manifest.py`
- Modify: `tests/unit/test_release_hardening.py`

**Interfaces:**
- Produces: required CI job `mcp-2026-compat` independent from the stable matrix.

- [ ] Add failing policy tests requiring the candidate job and proving `server.json` advertises only `2025-11-25`.
- [ ] Implement the SHA-policy-compliant CI job and include it in `required-pr-gate` dependencies/status checks.
- [ ] Run workflow policy, actionlint, Zizmor, manifest tests, and the candidate lane.
- [ ] Commit with `ci(mcp): verify the 2026 compatibility lane`.

### Task 5: Document migration, rollout, and rollback

**Files:**
- Create: `docs/adr/0006-mcp-2026-stateless-compatibility-lane.md`
- Modify: `docs/mcp/transport.md`
- Modify: `docs/mcp/api-reference.md`
- Modify: `mkdocs.yml` if explicit navigation requires it.
- Modify: `tests/unit/test_release_hardening.py`.

**Interfaces:**
- Documents configuration, component state inventory, unsupported candidate features, host rollout, release gates, and rollback to stable.

- [ ] Add a failing documentation contract test requiring the selector, warnings, component inventory, release-decision gates, and rollback command.
- [ ] Write the ADR and operator-facing docs without describing the candidate lane as generally available.
- [ ] Run strict docs build and link checks.
- [ ] Commit with `docs(mcp): document the 2026 migration lane`.

### Task 6: Verification, PR, and bot review

**Files:** All files changed in Tasks 1–5.

- [ ] Run candidate config, pure contract, live candidate, and stable MCP suites.
- [ ] Run metadata, formatting, lint, type, security, workflow policy, protocol schemas, unit tests, and strict docs build.
- [ ] Confirm the production dependency remains `<2.0.0` and public metadata remains `2025-11-25`.
- [ ] Push the branch and open a professional English PR closing #410.
- [ ] Inspect every bot/agent comment, review, inline thread, Codecov report, CodeQL result, dependency review, Semgrep result, Socket report, and required check.
- [ ] Address all actionable findings and rerun affected checks.
- [ ] Squash merge only when the final HEAD is green and review-thread gate reports zero blockers.
