# Architecture

This is the **map of the codebase**. Read it first. It explains how KiCad MCP Pro
is layered, where the fragile parts are quarantined, and — concretely — how to add
a new tool without breaking the contract. For the *runtime* model (intent → builder →
critic → gate) and the quality-gate stack, see
[`docs/development/architecture.md`](docs/development/architecture.md).

## What this server is

KiCad MCP Pro is a [Model Context Protocol](https://modelcontextprotocol.io) server
that exposes KiCad EDA workflows to AI agents. It **does not re-implement KiCad**. It
wraps KiCad's own engines — ERC/DRC, `kicad-cli`, the IPC/`kipy` API, and the
S-expression project files — in an agent-friendly, **gated**, and **auditable**
contract. Every behavior either drives a real KiCad engine or operates on real KiCad
files; nothing about a board is invented.

## The five layers

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. TRANSPORT            stdio  ·  Streamable HTTP (/mcp)  ·  CLI/tray  │
│    server.py · cli_init.py · web/ · tray.py · wellknown.py            │
├──────────────────────────────────────────────────────────────────────┤
│ 2. MCP PROTOCOL         tools · resources · prompts (FastMCP)         │
│    server.py:KiCadFastMCP · resources/ · prompts/                     │
├──────────────────────────────────────────────────────────────────────┤
│ 3. ORCHESTRATION        profiles → categories → tool registration,    │
│    tools/router.py · tools/metadata.py · operating_modes.py · gates   │
├──────────────────────────────────────────────────────────────────────┤
│ 4. KiCad ADAPTER SEAM   ← all KiCad fragility is quarantined here →    │
│    kicad/session.py · connection.py · ipc/ · discovery.py             │
├──────────────────────────────────────────────────────────────────────┤
│ 5. PURE DOMAIN          no KiCad import; unit-testable in isolation    │
│    utils/ · models/ · dfm_profiles/ · templates/                     │
└──────────────────────────────────────────────────────────────────────┘
```

### 1. Transport

How a client reaches the server.

- [`src/kicad_mcp/server.py`](src/kicad_mcp/server.py) wires `stdio` and Streamable
  HTTP (served at `/mcp`, movable via `KICAD_MCP_MOUNT_PATH`). HTTP transport security
  (auth token, CORS, stateful-vs-stateless sessions) is validated at build time by
  `cfg._validate_http_transport_security()`.
- [`src/kicad_mcp/cli_init.py`](src/kicad_mcp/cli_init.py) and the `typer` app in
  `server.py` expose the `kicad-mcp-pro` CLI (`init`, `dashboard`, `tray`, `inspect`).
- [`src/kicad_mcp/web/`](src/kicad_mcp/web) serves the Starlette dashboard;
  [`src/kicad_mcp/tray.py`](src/kicad_mcp/tray.py) the system tray;
  [`src/kicad_mcp/wellknown.py`](src/kicad_mcp/wellknown.py) the discovery endpoints.

### 2. MCP protocol

The MCP surface itself.

- `KiCadFastMCP(FastMCP)` in [`server.py`](src/kicad_mcp/server.py) is the server
  object. Tools, resources, and prompts are registered onto it.
- [`src/kicad_mcp/resources/`](src/kicad_mcp/resources) exposes read-only review
  state (`kicad://project/quality_gate`, `kicad://project/fix_queue`, …).
- [`src/kicad_mcp/prompts/`](src/kicad_mcp/prompts) exposes workflow prompts (the
  critic/fixer loop).

### 3. Orchestration

What decides *which* tools exist for a given run, and how they are labeled.

- [`src/kicad_mcp/tools/router.py`](src/kicad_mcp/tools/router.py) is the **registry
  of record**: `TOOL_CATEGORIES` maps each category to its tool names, and
  `PROFILE_CATEGORIES` maps each server profile to a set of categories.
  `categories_for_profile()` resolves the enabled set.
- [`server.py`](src/kicad_mcp/server.py) `build_server(profile)` →
  `_register_profile_components(server, enabled, cfg)` calls each domain module's
  `register(mcp)` **only if its category is enabled** for the active profile. So the
  same code base presents a `minimal`, `pcb_only`, `critic`, `agent_full`, … surface
  depending on profile.
- [`src/kicad_mcp/tools/metadata.py`](src/kicad_mcp/tools/metadata.py) attaches
  discovery metadata/`ToolAnnotations` (read-only, destructive, headless,
  requires-KiCad-running, dependencies). `EXPERIMENTAL_TOOL_NAMES` in `router.py`
  flags experimental tools.
- [`src/kicad_mcp/operating_modes.py`](src/kicad_mcp/operating_modes.py) layers the
  four operating modes (readonly / write / manufacturing / experimental) on top of
  profiles.
- The **quality-gate stack** (`project_quality_gate()` aggregating the sub-gates) and
  the release contract live across [`tools/validation.py`](src/kicad_mcp/tools/validation.py),
  [`tools/gates.py`](src/kicad_mcp/tools/gates.py), and
  [`tools/manufacturing.py`](src/kicad_mcp/tools/manufacturing.py). See
  [`docs/development/architecture.md`](docs/development/architecture.md) for the gate
  details.

### PCB composition root

The PCB registry is intentionally a small composition root rather than a container
for board behavior. The original nested registry concentrated 2,821 lines in one
`register()` function. The current structure separates registration from testable
domain behavior and keeps every composition helper below the 300-line boundary:

```text
before
  tools/pcb.py::register (2,821 lines)
    └─ decorators + orchestration + board behavior + result formatting

after
  tools/pcb.py::register (bounded composition root)
    ├─ thin tools/pcb_* adapters
    │    └─ typed pcb/* domain services
    └─ bounded _register_* composition helpers
         └─ existing public tool implementations grouped by capability
```

`python scripts/check_architecture_boundaries.py` enforces the root and adapter
limits, while contract snapshots prevent public tool names, schemas, annotations,
and profile membership from drifting during extraction. New PCB behavior should
prefer a FastMCP-independent service under `src/kicad_mcp/pcb/` with a thin adapter
under `src/kicad_mcp/tools/`; composition helpers are for registration wiring, not
new domain logic.

### 4. KiCad adapter seam — *the fragility quarantine*

**This is the most important architectural rule: everything that can break when
KiCad changes lives here, and only here.** Domain logic above and below this seam
talks to stable, typed interfaces, not to KiCad internals.

- [`src/kicad_mcp/kicad/session.py`](src/kicad_mcp/kicad/session.py) — `KiCadSession`,
  the central IPC session adapter (connect, board access, lifecycle, TTL caching).
- [`src/kicad_mcp/connection.py`](src/kicad_mcp/connection.py) — thread-safe,
  process-wide connection management over `kipy` (`get_kicad()`, `get_board()`).
- [`src/kicad_mcp/ipc/`](src/kicad_mcp/ipc) — `client.py` (thin stable operations),
  `discovery.py` (endpoint discovery), `capabilities.py` (probe what this KiCad build
  supports), `errors.py`.
- [`src/kicad_mcp/discovery.py`](src/kicad_mcp/discovery.py) — `kicad-cli` and project
  detection; this is where user-influenced paths reach `subprocess`, so it is also a
  primary **security** surface (see
  [`docs/security/threat-model.md`](docs/security/threat-model.md)).

There are exactly **three channels** into KiCad, all crossing this seam:

| Channel | Used for | Entry point |
| --- | --- | --- |
| `kicad-cli` subprocess | exports, ERC/DRC reports, format conversion | `discovery.py`, `tools/export.py` |
| IPC / `kipy` API | live board/schematic inspection & mutation | `connection.py`, `kicad/session.py` |
| S-expression files | direct `.kicad_sch` / `.kicad_pcb` edits | `utils/sexpr.py` |

### 5. Pure domain

Logic with **no KiCad dependency** — pure functions over data. This is where the EE
math and file manipulation live, and it is fully unit-testable without KiCad
installed.

- [`src/kicad_mcp/utils/`](src/kicad_mcp/utils) — `impedance.py`, `placement.py`,
  `sexpr.py`, `freerouting.py`, `footprint_gen.py`, …
- [`src/kicad_mcp/models/`](src/kicad_mcp/models) — Pydantic payload/verdict models.
- [`src/kicad_mcp/dfm_profiles/`](src/kicad_mcp/dfm_profiles),
  [`src/kicad_mcp/templates/`](src/kicad_mcp/templates) — bundled data.

## Cross-cutting contracts

- **Errors** — [`src/kicad_mcp/errors.py`](src/kicad_mcp/errors.py) defines the typed
  exception hierarchy and `ErrorPayload {code, message, hint, retryable}`. Every error
  surfaced to an agent is one of these stable codes (the consolidated catalog lives in
  [`docs/errors.md`](docs/errors.md)).
- **Metadata / annotations** — [`tools/metadata.py`](src/kicad_mcp/tools/metadata.py).
  `server.json` is the canonical package contract and is kept in sync with
  `pyproject.toml` via `pnpm run metadata:check`.
- **Capability parity** — what fraction of KiCad's *programmatic* surface this server
  drives is tracked as a machine-readable matrix
  ([`docs/compatibility/capability-parity-matrix.yaml`](docs/compatibility/capability-parity-matrix.yaml),
  human view: [`capability-parity.generated.md`](docs/compatibility/capability-parity.generated.md))
  and surfaced by the `kicad_capability_parity()` tool. `gap` (we could drive it but
  don't yet) is kept distinct from `gui-only-no-api` (KiCad has no headless surface).

## How to add a new tool

A tool is added in one module + one registry entry. Concretely:

1. **Implement it.** Put deterministic behavior in the matching domain package
   (for example `src/kicad_mcp/pcb/`) and expose it through a thin adapter under
   [`src/kicad_mcp/tools/`](src/kicad_mcp/tools). Register the adapter from the
   bounded composition root. Keep KiCad-touching calls behind the adapter seam
   (layer 4); keep pure math/file logic in [`utils/`](src/kicad_mcp/utils) so it is
   unit-testable. Do not add new business logic directly to a root `register()`.
2. **Register it in the catalog.** Add the tool name to the correct category's `tools`
   list in `TOOL_CATEGORIES` in
   [`tools/router.py`](src/kicad_mcp/tools/router.py). If it should not appear in every
   profile, confirm the category is included in the right `PROFILE_CATEGORIES` entries.
   Mark experimental tools in `EXPERIMENTAL_TOOL_NAMES`.
3. **Annotate it.** Set read-only / destructive / headless / requires-KiCad metadata
   via [`tools/metadata.py`](src/kicad_mcp/tools/metadata.py) conventions so
   annotations and docs are correct.
4. **Regenerate + verify.** Run `pnpm run docs:tools` (refresh
   [`docs/tools-reference.generated.md`](docs/tools-reference.generated.md)) and
   `pnpm run metadata:check`. The registry-consistency test
   (`tests/unit/test_tool_registry_consistency.py`) and the tool-surface snapshot
   (`tests/integration/test_tool_surface_snapshot.py`) will flag any drift.
5. **Test it.** Add a unit test for the pure logic (no KiCad) and, where the tool
   drives KiCad, a test marked to run only in the KiCad-enabled CI job.

Then `task verify` must be green.

## Testing strategy

- **Pure-domain logic** (layer 5) is covered by `tests/unit/` and runs everywhere with
  no KiCad installed.
- **Tool/contract behavior** uses `build_server(profile)` with a mocked KiCad and lives
  in `tests/integration/`.
- **Live KiCad** end-to-end checks are marked and run only in the KiCad-enabled CI job.
- A small benchmark/failure corpus under `tests/fixtures/benchmark_projects/` pins
  release-gating behavior — see the runtime architecture doc.

## Where things live (quick index)

| You want to… | Look at |
| --- | --- |
| Add/route a tool | [`tools/router.py`](src/kicad_mcp/tools/router.py) + a `tools/*.py` module |
| Change KiCad I/O | the adapter seam: [`kicad/`](src/kicad_mcp/kicad), [`connection.py`](src/kicad_mcp/connection.py), [`ipc/`](src/kicad_mcp/ipc), [`discovery.py`](src/kicad_mcp/discovery.py) |
| Add EE math / file logic | [`utils/`](src/kicad_mcp/utils) (keep it KiCad-free) |
| Change the release gate | [`tools/validation.py`](src/kicad_mcp/tools/validation.py), [`tools/gates.py`](src/kicad_mcp/tools/gates.py) |
| Change transports/auth | [`server.py`](src/kicad_mcp/server.py), [`web/`](src/kicad_mcp/web) |
| Understand error codes | [`errors.py`](src/kicad_mcp/errors.py), [`docs/errors.md`](docs/errors.md) |
