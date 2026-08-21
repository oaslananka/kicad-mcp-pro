# Project Reporting Extraction Design

## Context

Issue #577 tracks incremental decomposition of oversized FastMCP composition roots. After #739, `src/kicad_mcp/tools/project.py` still owns two adjacent read-only reporting tools inside `register()`:

- `project_gate_trend(gate_name: str, last_n: int = 10) -> str`
- `project_design_report() -> DesignReportPayload`

Both tools summarize existing project-quality state rather than mutate KiCad state. Their current implementation reaches into gate history, project-gate evaluation, fixer lookup, design-intent resolution, and intent rendering directly from the FastMCP composition root. The public contracts are stable and must not change.

This tranche extracts that ownership without adding features, changing response semantics, or changing MCP registration order.

## Goals

1. Move the two read-only reporting behaviors out of `tools.project.register()` into one focused FastMCP-independent project reporting service.
2. Keep FastMCP decorators, public signatures, descriptions, metadata, and registration order in a thin adapter.
3. Preserve the legacy `kicad_mcp.tools.project.DesignReportPayload` import surface through an explicit compatibility re-export.
4. Preserve late-bound runtime seams used by integration tests and monkeypatching.
5. Add architecture guards that prevent the new service/adapter from regressing into the project monolith.
6. Reduce direct nested MCP tool ownership in `tools.project.register()` from 10 to 8.

## Non-goals

- No new reporting fields or report sections.
- No change to gate severity precedence.
- No change to gate-history persistence or schema.
- No change to fixer registry semantics.
- No change to design-intent resolution or rendering behavior.
- No change to `project_quality_gate`, validation loops, design-spec editing, auto-fix behavior, or project help.
- No public MCP name, schema, description, annotation, default, ordering, or response-shape change.
- No migration of `GateHistory`, `GateOutcome`, fixer registry, or design-intent models into new packages.

## Architecture

### Domain service

Create `src/kicad_mcp/project/reporting.py`.

It will contain:

- `DesignReportPayload`, moved from `tools.project`.
- Structural protocols for the minimal gate outcome, fixer action, design-intent resolution, and gate-history capabilities consumed by reporting.
- `ProjectReportingService`, a frozen/slotted dataclass whose dependencies are injected callables.
- Pure orchestration for `gate_trend()` and `design_report()`.

The module must not import FastMCP, `kicad_mcp.tools.project`, KiCad IPC/connection code, or concrete gate-history/fixer/validation modules. It may depend on Pydantic and stable project design-intent types needed by the response payload.

Expected dependency shape:

```python
@dataclass(frozen=True, slots=True)
class ProjectReportingService:
    history_for_active_project: Callable[[], GateHistoryLike]
    resolve_design_intent: Callable[[], ProjectSpecResolutionLike]
    render_design_intent: Callable[[ProjectDesignIntentLike], str]
    evaluate_project_gate: Callable[[], Sequence[GateOutcomeLike]]
    fixers_for_gate: Callable[[str], Sequence[FixerActionLike]]

    def gate_trend(self, gate_name: str, last_n: int = 10) -> str: ...
    def design_report(self) -> DesignReportPayload: ...
```

Protocols should expose only the attributes actually read by the service. The service must remain testable with simple stubs and no FastMCP server.

### Thin FastMCP adapter

Create `src/kicad_mcp/tools/project_reporting.py`.

The adapter will expose:

```python
@dataclass(frozen=True)
class ProjectReportingDependencies:
    service: ProjectReportingServiceLike


def register(mcp: FastMCP, dependencies: ProjectReportingDependencies) -> None:
    ...
```

`register()` owns only:

- `@mcp.tool()` decoration,
- `@headless_compatible`,
- the exact legacy function signatures,
- the exact legacy docstrings/descriptions,
- delegation to the service.

The adapter must not import `kicad_mcp.tools.project` and should remain at or below the existing 55-line reviewed adapter limit.

### Composition-root wiring

Modify `src/kicad_mcp/tools/project.py` to:

1. Re-export `DesignReportPayload` from `kicad_mcp.project.reporting` for compatibility.
2. Define module-level late-binding wrappers for dependencies whose implementations are expected to remain monkeypatchable after server construction, especially project-gate evaluation and fixer lookup.
3. Construct `ProjectReportingService` inside `register()`.
4. Invoke `project_reporting.register(...)` exactly where the two legacy nested tools were registered: after validation-loop registration and before discovery registration.
5. Remove the two nested tool definitions from `register()`.

Late-binding wrappers are required because existing integration tests monkeypatch `kicad_mcp.tools.validation._evaluate_project_gate` after the server is built. Capturing that function object at server-construction time would silently change behavior.

## Data and behavior preservation

### `project_gate_trend`

The extracted service must preserve all current behavior:

- Construct history through the injected active-project history factory on every call.
- Clamp `last_n` to `max(1, min(last_n, 100))`.
- Return JSON with exactly these keys:
  - `gate_name`
  - `history`
  - `regressions`
- Render via `json.dumps(payload, indent=2, sort_keys=True)`.
- Do not swallow history/storage exceptions that currently propagate.

### `project_design_report`

The extracted service must preserve all current behavior:

1. Resolve design intent and use `resolution.resolved` as the reported intent.
2. Evaluate project gates using the late-bound injected evaluator.
3. Compute the combined status in a pure reporting helper with the exact existing precedence: `EMPTY > BLOCKED > FAIL > WARN > PASS`. This avoids importing or injecting the concrete tool-layer `GateOutcome` implementation.
4. Treat every outcome whose status is not `PASS` as failing/reportable.
5. Render the report text exactly as today:
   - `# Project Design Report`
   - blank line
   - `## Design Intent`
   - current intent rendering
   - blank line
   - `## Gate Status: <status>`
   - failing gate count and per-gate suggested fixer when any gate is non-PASS
   - otherwise `All gates PASS — ready for export_manufacturing_package().`
   - blank line
   - `## Resolution Notes`
   - at most the first 8 resolution notes, each prefixed by `- `
6. For each failing gate, use the first fixer tool when available; otherwise use `project_quality_gate`.
7. Preserve suggested-tool text formatting with `()` in the rendered report lines.
8. Preserve `next_tool` semantics:
   - first failing gate's first fixer tool when one exists,
   - `project_quality_gate` when the first failing gate has no fixer,
   - `export_manufacturing_package` when every gate passes.
9. Preserve payload counters:
   - `power_rails_count = len(intent.power_rails)`
   - `interfaces_count = len(intent.interfaces)`
   - `compliance_count = len(intent.compliance)`
10. Preserve `has_mechanical_constraint` as true when any mount hole exists, any connector placement exists, or `max_height_mm` is non-null.
11. Preserve `intent_source = resolution.source`.

No error translation or new fallback behavior is introduced in this tranche.

## Public compatibility contract

The following must remain byte/structure compatible with `main@b73f1cc1c06db49ab84207426b37f8f47c487188`:

- Full `agent_full` tool count: 386.
- Tool names and registration order.
- `project_gate_trend` parameters, defaults, schema, description, annotations, and metadata.
- `project_design_report` empty input schema, output schema, description, annotations, and metadata.
- `DesignReportPayload` field names, types, defaults, and Pydantic serialization.
- Existing `from kicad_mcp.tools.project import DesignReportPayload` compatibility.
- Existing router/profile inclusion and generated tool-surface snapshots.

The final branch must produce an explicit public descriptor snapshot equal to the base descriptor snapshot for all 386 tools.

## Architecture enforcement

Update `scripts/check_architecture_boundaries.py` to track:

- `kicad_mcp.project.reporting` as a project service module.
- `kicad_mcp.tools.project_reporting` as an adapter module.
- Adapter forbidden-import prefix: `kicad_mcp.tools.project`.
- Adapter `register()` maximum: 55 lines.

Add an architecture regression test that proves:

- the service does not import FastMCP or `tools.project`;
- the adapter does not import `tools.project`;
- `tools.project.register()` no longer defines `project_gate_trend` or `project_design_report` as nested functions;
- the checker tracks and enforces the new modules.

## Testing strategy

Use strict TDD.

### RED 1 — service behavior

Add service tests before creating the production module. Cover:

- trend `last_n` lower and upper clamping;
- exact sorted/indented JSON shape;
- PASS report path;
- WARN/FAIL/BLOCKED/EMPTY combined-status behavior;
- fixer-present and fixer-missing suggestion paths;
- first-failing-gate `next_tool` semantics;
- resolution-note truncation at 8;
- design-intent counters and mechanical-constraint calculation.

Expected RED reason: reporting module/service does not exist.

### RED 2 — adapter contract/delegation

Add registration tests before creating the adapter. Cover:

- exact tool names and local ordering;
- exact signatures/defaults/descriptions/headless metadata;
- delegation arguments and return values;
- `DesignReportPayload` output schema.

Expected RED reason: adapter module does not exist.

### RED 3 — architecture/composition ownership

Add architecture tests before rewiring `project.py`. Cover the enforcement points listed above.

Expected RED reasons: checker does not track the new modules and the two tools remain nested in the monolith.

### Regression and acceptance gates

After GREEN and refactor, run on the final source tree:

1. New service/adapter/architecture tests.
2. Existing `tests/integration/test_project_validation_loop.py` reporting integration test.
3. Tool surface/profile/startup/metadata regressions.
4. Exact `format:check` and Ruff.
5. Full Mypy.
6. Architecture checker.
7. `check:meta` including capability parity, tool contracts, compatibility, and runtime policy.
8. sdist/wheel build and package metadata; assert the new production modules are present in both artifacts.
9. Explicit 386/386 agent-facing descriptor parity against base `main@b73f1cc1...`.
10. Benchmark-excluded full unit suite on the exact final tree.
11. `git diff --check` and clean worktree after commit.

GitHub PR CI remains authoritative for platform matrix, coverage, Required PR Gate, CodeQL, Semgrep, dependency/security checks, Live Model Release Policy, Codecov, and Sonar.

## Expected architecture delta

Starting point after #739:

- `src/kicad_mcp/tools/project.py`: 1657 lines.
- `project.register()` span: approximately 469 lines.
- direct nested MCP tools: 10.

Expected after this tranche:

- direct nested MCP tools: 8.
- `project.register()` reduced by roughly the current 87-line reporting block plus wiring overhead.
- one pure reporting service and one thin adapter added.

Exact post-change measurements will be recorded from AST/source after implementation rather than treated as contractual targets.

## Risks and mitigations

### Late-binding regression

Risk: capturing `_evaluate_project_gate` or fixer registry functions at server creation would break existing monkeypatch/runtime behavior.

Mitigation: composition-root wrappers resolve those concrete functions at call time; integration tests monkeypatch after server construction and must still pass.

### Public tool-order drift

Risk: registering the new adapter at a convenient location rather than the legacy location would change agent-visible order.

Mitigation: register the adapter at the exact legacy block location and require 386/386 descriptor parity.

### Type coupling to tool-layer models

Risk: importing concrete validation/fixer implementations into the service would recreate the architecture problem under a new filename.

Mitigation: minimal structural protocols and injected callables only; architecture checker prevents back-imports.

### Accidental reporting behavior cleanup

Risk: changing ordering of failing gates, error handling, text wording, or note/fixer selection while extracting.

Mitigation: no semantic cleanup in this tranche; exact behavior tests and base-vs-branch payload/descriptor comparisons are acceptance gates.

## Rollback

The change is structural and has no data migration. A rollback is a normal revert of the tranche merge commit. `GateHistory` data, project spec files, and public MCP state require no migration or repair.
