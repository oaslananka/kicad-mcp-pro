# MCP Tasks 2026-07-28 — isolated requester interoperability evidence

**Date:** 2026-11-16. **Scope:** research-only synthetic ERC/DRC; no production
Tasks advertisement, background scheduler, hosted relay, KiCad command, board
read/write, or manufacturing operation. Related to #1221, #1258 and #1535.

## Frozen independent references

| Artifact | Verified immutable identification |
| --- | --- |
| Extension | `io.modelcontextprotocol/tasks`, 2026-07-28 |
| Official JSON Schema | `modelcontextprotocol/ext-tasks@cc9aaac1047a9440b07486e38f37060bbebeef4c`, `schema/2026-07-28/schema.json` |
| Schema SHA-256 | `bf30afb7ac251e3e22c037b7a685f60ef6603031b5484c0d08b1fa0bbe86d460` |
| Independent requester | `@modelcontextprotocol/ext-tasks@0.2.3` |
| npm package integrity | `sha512-MZKxyGKXDyZuc54GlnvzYBecBAlKNlYI/WgrTuIXLKV6h3ebDZU2sTpQpe7kKgKLJz0TTDIxmnM7HAmXL0GOcA==` |
| Requester SDK peer | `@modelcontextprotocol/client@2.2.0` |
| Existing Python synchronous SDK | `mcp==2.2.0` (does **not** provide the Tasks extension) |

The fixture's stored provenance is
`tests/contracts/mcp/tasks-2026-07-28/provenance.json`; dependency locks are
in `pnpm-lock.yaml`. The immutable upstream schema was independently fetched,
SHA-256 verified, and **11 generated synthetic response examples** validated
against its 2020-12 JSON Schema with `jsonschema`. The entire 99 KB upstream
schema and the temporary offline audit script were deliberately not added to
this repository.

## Real HTTP requester evidence

The version-pinned **independently maintained** requester runs in a fresh Node
process and exchanges actual HTTP JSON-RPC with the Python synthetic fixture
on ephemeral `127.0.0.1` loopback:

- `tests/research/mcp_tasks_client_2026.mjs` calls the upstream
  `withTasks` requester, not a handwritten task-state implementation.
- `tests/research/mcp_tasks_http_probe.py` only adapts HTTP framing and
  out-of-band, short-lived caller identity to the *existing* `TaskFixture`.
- `tests/integration/test_mcp_tasks_2026_client.py` runs six real-client
  lifecycle scenarios: completed read-only task, tool-level `isError`, an
  `input_required`/update exchange, cancelled task, extension-free synchronous
  fallback, and expired task. It additionally checks different caller
  principals, missing authentication, wrong task routing header, 4096-byte
  request budget and concurrent capacity (8 retained / 4 rejected).
- `Mcp-Method` and `Mcp-Name` are verified on each task request. Ephemeral
  test credentials are passed to the child **only through its environment**,
  never command arguments or committed evidence; arbitrary request payloads
  are not logged.
- The existing direct fixture tests also cover deadline (15 s), TTL (60 s),
  polling hint (1000 ms), duplicate polls, malformed JSON, restart invalidation
  and legacy `tasks/list` rejection.

**Local observation:** 88 focused Python tests PASS (including eight real HTTP
integration cases); Ruff and Node `--check` PASS. Node.js 26.13.1 on Windows
was used for this local run; the repository's pinned Node 24 lane is checked
independently by its hosted GitHub Actions job. Host UI/native-agent
interoperability is **NOT VERIFIED** and must not be claimed as proven.

### Repeatable acceptance commands

Use the repository-pinned `uv` and Node versions; from a clean checkout:

```sh
corepack enable
corepack pnpm install --frozen-lockfile --ignore-scripts
uv sync --all-extras --frozen
MCP_TASKS_REAL_CLIENT_REQUIRED=1 uv run pytest -q \
  tests/unit/test_mcp_tasks_2026_schema_contract.py \
  tests/unit/test_mcp_tasks_draft_fixture.py \
  tests/integration/test_mcp_tasks_2026_client.py
uv run pytest -q tests/integration/test_task_protocol.py \
  tests/unit/test_mcp_protocol_2026_contract.py
```

The existing `MCP 2026 Compatibility` job invokes the mandatory real-client
probe on its own fixed-version Node environment. Python-only suites may skip
real-client cases when the test-only Node package is unavailable; they must not
count such skips as evidence.

## Bounded resource and safety disposition

One local, **synthetic-only** deterministic profiling sample retained exactly
8 tasks and made 1,000 duplicate status polls with no worker progress:
0.167441 s total, approximately 0.167 ms per poll, and 233.93 KiB peak
`tracemalloc`-tracked Python allocations. This is **not** a prediction of
actual ERC/DRC CPU use, HTTP throughput, full-process RSS, or production queue
cost. It introduces no long-running process, persistent storage, external
provider, credentials, or new paid service.

### Scope and stop rule

This work establishes the *research extension interoperability* boundary.
Cross-platform hosted CI and exact-head required checks remain authoritative.
If any frozen schema, client, isolation or CI gate fails, mark that evidence
`FAIL` / `NOT VERIFIED` and keep #1221 open. No future live Tasks pilot,
stateful service, KiCad report job or manufacturing/write permission is
authorized by this evidence alone; those require separate explicit opt-in
security review and a subsequent implementation scope.
