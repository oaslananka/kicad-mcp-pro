# Project Reporting Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `project_gate_trend` and `project_design_report` from the oversized Project FastMCP composition root into a FastMCP-independent reporting service plus a thin adapter without changing any public MCP contract or reporting semantics.

**Architecture:** Add `kicad_mcp.project.reporting.ProjectReportingService` with injected history, intent-resolution/rendering, gate-evaluation, and fixer-lookup dependencies. Add `kicad_mcp.tools.project_reporting` as the only FastMCP registration layer, then replace the two nested tools in `tools.project.register()` at their exact legacy location while preserving late binding and a compatibility re-export for `DesignReportPayload`.

**Tech Stack:** Python 3.13, Pydantic, FastMCP, pytest/anyio, Ruff, Mypy, repository architecture/meta/package verification scripts.

**Spec:** `docs/superpowers/specs/2026-08-22-project-reporting-design.md`

## Global Constraints

- Base behavior and public contract are frozen against `main@b73f1cc1c06db49ab84207426b37f8f47c487188`.
- Full `agent_full` tool count and agent-facing descriptor ordering must remain exactly 386/386.
- No new reporting fields, report sections, fallbacks, error translation, or gate/fixer semantics.
- Combined status precedence is exactly `EMPTY > BLOCKED > FAIL > WARN > PASS`.
- `project_gate_trend.last_n` remains clamped by `max(1, min(last_n, 100))`.
- `DesignReportPayload` remains import-compatible from `kicad_mcp.tools.project`.
- Service must not import FastMCP, `kicad_mcp.tools.project`, concrete validation/fixer/history modules, or KiCad IPC/connection code.
- Adapter must not import `kicad_mcp.tools.project`; adapter `register()` must be at most 55 source lines.
- Existing late monkeypatch behavior for `kicad_mcp.tools.validation._evaluate_project_gate` and fixer lookup must remain effective after server construction.
- Strict TDD: production implementation follows a verified failing test for each task.

---

### Task 1: Pure Project Reporting Service

**Files:**
- Create: `tests/unit/test_project_reporting_service.py`
- Create after RED: `src/kicad_mcp/project/reporting.py`

**Interfaces:**
- Consumes: injected `history_for_active_project`, `resolve_design_intent`, `render_design_intent`, `evaluate_project_gate`, and `fixers_for_gate` callables.
- Produces: `DesignReportPayload` and `ProjectReportingService.gate_trend(gate_name: str, last_n: int = 10) -> str`, `ProjectReportingService.design_report() -> DesignReportPayload`.

- [ ] **Step 1: Write service RED tests before the production module exists**

Create tests using local structural stubs (no FastMCP server) that assert:

```python
from dataclasses import dataclass, field

@dataclass
class Outcome:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)

@dataclass
class Fixer:
    tool: str

class History:
    def __init__(self) -> None:
        self.trend_calls: list[tuple[str, int]] = []
    def trend(self, gate_name: str, last_n: int):
        self.trend_calls.append((gate_name, last_n))
        return [{"gate_name": gate_name, "issue_count": 1}]
    def regression_check(self):
        return ["regression"]
```

Cover all of the following independently:
- `last_n=0` becomes 1 and `last_n=101` becomes 100.
- trend JSON equals `json.dumps({...}, indent=2, sort_keys=True)` exactly.
- all-PASS report returns `gate_status="PASS"`, `next_tool="export_manufacturing_package"`, and exact success wording.
- combined status precedence using cases containing WARN, FAIL, BLOCKED, and EMPTY.
- fixer present renders `-> Suggested: <tool>()` and chooses the first fixer tool.
- fixer missing renders/returns `project_quality_gate`.
- first non-PASS outcome remains the source of `next_tool`; do not reorder outcomes.
- only the first eight resolution notes render.
- payload counters equal lengths of `power_rails`, `interfaces`, and `compliance`.
- mechanical constraint is true for any mount hole, connector placement, or non-null max height and false otherwise.
- `intent_source` is copied from the resolution.

- [ ] **Step 2: Run Task 1 tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_reporting_service.py
```

Expected: collection/import failure because `kicad_mcp.project.reporting` does not yet exist. A failure for another reason must be fixed before production code is written.

- [ ] **Step 3: Implement the minimal pure service**

Create `src/kicad_mcp/project/reporting.py` with:

```python
class DesignReportPayload(BaseModel):
    text: str
    gate_status: str
    intent_source: ProjectSpecSource = "none"
    power_rails_count: int = 0
    interfaces_count: int = 0
    compliance_count: int = 0
    has_mechanical_constraint: bool = False
    next_tool: str = ""
```

Define minimal `Protocol` types only for attributes actually read: gate outcome (`name/status/summary/details`), fixer (`tool`), history (`trend/regression_check`), resolved intent/mechanical data, and resolution (`source/resolved/notes`). Implement a private `_combined_status()` that evaluates a set of statuses with exact precedence `EMPTY`, `BLOCKED`, `FAIL`, `WARN`, then `PASS`.

Implement `ProjectReportingService.gate_trend()` exactly as:

```python
history = self.history_for_active_project()
payload = {
    "gate_name": gate_name,
    "history": history.trend(gate_name, max(1, min(last_n, 100))),
    "regressions": history.regression_check(),
}
return json.dumps(payload, indent=2, sort_keys=True)
```

Implement `design_report()` by preserving the current line construction, failing-outcome iteration order, first-fixer selection, 8-note truncation, payload counters, and `next_tool` semantics from the spec. Do not catch dependency exceptions.

- [ ] **Step 4: Run Task 1 tests and static checks until GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_reporting_service.py
.venv/bin/python -m ruff check src/kicad_mcp/project/reporting.py tests/unit/test_project_reporting_service.py
.venv/bin/python -m ruff format --check src/kicad_mcp/project/reporting.py tests/unit/test_project_reporting_service.py
.venv/bin/python -m mypy src/kicad_mcp/project/reporting.py tests/unit/test_project_reporting_service.py
```

Expected: all exit 0.

- [ ] **Step 5: Commit Task 1**

Commit only the service and service tests with message:

```text
refactor(project): add reporting service
```

---

### Task 2: Thin FastMCP Reporting Adapter

**Files:**
- Create: `tests/unit/test_project_reporting_registration.py`
- Create after RED: `src/kicad_mcp/tools/project_reporting.py`

**Interfaces:**
- Consumes: any service implementing `gate_trend(str, int) -> str` and `design_report() -> DesignReportPayload`.
- Produces: exact public tools `project_gate_trend` and `project_design_report` in that local order.

- [ ] **Step 1: Capture the base bare-registration contract before adapter implementation**

Using a detached/base worktree or `git show`-based helper against `b73f1cc1...`, record the two tools' public fields:
- names and relative order;
- parameter schemas/defaults;
- descriptions;
- annotations/headless metadata;
- `project_design_report` output schema.

Keep the capture under `/tmp`; do not commit generated snapshots.

- [ ] **Step 2: Write adapter RED tests before the production adapter exists**

Create a stub service that records calls and returns fixed values. Tests must assert:

```python
project_gate_trend("Placement", 7)
```

delegates exactly `("Placement", 7)`, and `project_design_report()` delegates with no arguments. Compare registered tool metadata against the base capture, not hand-rewritten approximations. Confirm local order is trend then report.

- [ ] **Step 3: Run Task 2 tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_reporting_registration.py
```

Expected: import/collection failure because `kicad_mcp.tools.project_reporting` does not exist.

- [ ] **Step 4: Implement the minimal adapter**

Create `src/kicad_mcp/tools/project_reporting.py` with a small service `Protocol`, frozen dependency dataclass, and `register()` containing only the two decorated functions. Copy the exact legacy signatures and docstrings from `tools.project`:

```python
@mcp.tool()
@headless_compatible
def project_gate_trend(gate_name: str, last_n: int = 10) -> str:
    """Return persisted quality-gate trend history for one gate."""
    return service.gate_trend(gate_name, last_n)

@mcp.tool()
@headless_compatible
def project_design_report() -> DesignReportPayload:
    """Generate a comprehensive design-status report.

    Combines intent summary, v2 spec richness, project gate evaluation, and
    a prioritised list of next steps into a single structured report.
    This is the recommended first call after opening a project to understand
    its current state.
    """
    return service.design_report()
```

- [ ] **Step 5: Run Task 2 tests and static checks until GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_reporting_registration.py tests/unit/test_project_reporting_service.py
.venv/bin/python -m ruff check src/kicad_mcp/tools/project_reporting.py tests/unit/test_project_reporting_registration.py
.venv/bin/python -m ruff format --check src/kicad_mcp/tools/project_reporting.py tests/unit/test_project_reporting_registration.py
.venv/bin/python -m mypy src/kicad_mcp/tools/project_reporting.py tests/unit/test_project_reporting_registration.py
```

Expected: all exit 0 and base metadata comparison exact.

- [ ] **Step 6: Commit Task 2**

Commit adapter and registration tests with message:

```text
refactor(project): add reporting adapter
```

---

### Task 3: Composition Root, Compatibility, and Architecture Ownership

**Files:**
- Create: `tests/unit/test_project_reporting_architecture.py`
- Modify after RED: `src/kicad_mcp/tools/project.py`
- Modify after RED: `scripts/check_architecture_boundaries.py`

**Interfaces:**
- Consumes: `ProjectReportingService`, `ProjectReportingDependencies`, concrete legacy dependency providers.
- Produces: exact legacy registration position, late-bound behavior, `DesignReportPayload` compatibility import, architecture enforcement.

- [ ] **Step 1: Write architecture/composition RED tests before rewiring**

Use AST/import inspection to assert:
- `kicad_mcp.project.reporting` does not import FastMCP, `kicad_mcp.tools.project`, concrete `tools.validation`, `tools.fixers`, or `resources.gate_history`.
- `kicad_mcp.tools.project_reporting` does not import `kicad_mcp.tools.project`.
- `tools.project.register()` has no nested function named `project_gate_trend` or `project_design_report`.
- architecture checker constants/maps contain the reporting service and adapter.
- adapter forbidden import prefix equals `("kicad_mcp.tools.project",)`.
- adapter `REGISTER_LINE_LIMITS` entry equals 55.
- `from kicad_mcp.tools.project import DesignReportPayload` resolves to the new domain payload class.

- [ ] **Step 2: Run architecture tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_project_reporting_architecture.py
```

Expected failures: checker tracking is absent and both tools are still nested in `tools.project.register()`.

- [ ] **Step 3: Rewire `tools.project` with late-bound dependency wrappers**

Add imports/re-exports:

```python
from ..project.reporting import DesignReportPayload as DesignReportPayload
from ..project.reporting import ProjectReportingService
from . import project_reporting
```

Create module-level wrappers that import the concrete implementations inside the wrapper body, for example:

```python
def _evaluate_project_gate_for_reporting():
    from .validation import _evaluate_project_gate
    return _evaluate_project_gate()


def _fixers_for_gate_for_reporting(gate_name: str):
    from .fixers import fixers_for_gate
    return fixers_for_gate(gate_name)


def _history_for_active_project_for_reporting():
    from ..resources.gate_history import GateHistory
    return GateHistory.for_active_project()
```

Use existing `resolve_design_intent` and `_render_design_intent` through call-time wrappers where needed so monkeypatch/runtime behavior is not captured early.

At the exact old reporting block location, construct:

```python
reporting_service = ProjectReportingService(
    history_for_active_project=_history_for_active_project_for_reporting,
    resolve_design_intent=_resolve_design_intent_for_reporting,
    render_design_intent=_render_design_intent_for_reporting,
    evaluate_project_gate=_evaluate_project_gate_for_reporting,
    fixers_for_gate=_fixers_for_gate_for_reporting,
)
project_reporting.register(
    mcp,
    project_reporting.ProjectReportingDependencies(service=reporting_service),
)
```

Then delete the two legacy nested function bodies and the old local imports they made unnecessary.

- [ ] **Step 4: Extend the architecture checker**

Add project reporting module constants/paths to the same maps used by existing project extraction modules. Mark the service as a pure project/domain helper where appropriate. Add:

```python
_PROJECT_REPORTING_ADAPTER: (_PROJECT_ROOT_MODULE,)
```

to adapter forbidden prefixes and:

```python
_PROJECT_REPORTING_ADAPTER: 55
```

to register line limits.

- [ ] **Step 5: Run Task 3 focused GREEN and existing integration regressions**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_project_reporting_service.py \
  tests/unit/test_project_reporting_registration.py \
  tests/unit/test_project_reporting_architecture.py \
  tests/integration/test_project_validation_loop.py
.venv/bin/python scripts/check_architecture_boundaries.py
```

Expected: all pass; specifically the existing test that monkeypatches `kicad_mcp.tools.validation._evaluate_project_gate` after `build_server()` must still produce WARN in `project_design_report`.

- [ ] **Step 6: Verify exact public descriptor parity before committing**

Serialize only agent-facing tool fields for `build_server("full")` on base `b73f1cc1...` and the current branch. Compare tool count, order, names, descriptions, parameters, output schemas, annotations, and metadata. Expected: 386/386 exact and identical SHA-256 for the normalized JSON.

- [ ] **Step 7: Run Task 3 static checks**

Run:

```bash
.venv/bin/python -m ruff format --check src/kicad_mcp/project/reporting.py src/kicad_mcp/tools/project_reporting.py src/kicad_mcp/tools/project.py tests/unit/test_project_reporting_*.py scripts/check_architecture_boundaries.py
.venv/bin/python -m ruff check src/kicad_mcp/project/reporting.py src/kicad_mcp/tools/project_reporting.py src/kicad_mcp/tools/project.py tests/unit/test_project_reporting_*.py scripts/check_architecture_boundaries.py
.venv/bin/python -m mypy src/kicad_mcp tests/unit/test_project_reporting_*.py
git diff --check
```

Expected: all exit 0.

- [ ] **Step 8: Measure architecture delta and commit Task 3**

Use AST/source inspection to record final `tools.project` line count, `register()` span, direct nested MCP tool count, and reporting adapter `register()` span. Expected direct nested tools: 8. Commit root/checker/architecture test changes with message:

```text
refactor(project): wire reporting extraction
```

---

### Task 4: Final Acceptance, Packaging, and Publish-Ready Tree

**Files:**
- No new production behavior.
- Modify only test/formatting code if a verification gate exposes a real tranche defect; any such modification requires rerunning affected final gates.

**Interfaces:**
- Produces: one clean, verified branch ready for remote publication and PR CI.

- [ ] **Step 1: Run the complete reporting/public regression set on the final tree**

Run the reporting tests plus tool-surface/profile/startup/metadata regressions used by prior Project tranches. At minimum include:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_project_reporting_service.py \
  tests/unit/test_project_reporting_registration.py \
  tests/unit/test_project_reporting_architecture.py \
  tests/integration/test_project_validation_loop.py \
  tests/integration/test_progressive_tool_profiles.py \
  tests/integration/test_tool_surface_snapshot.py
```

If exact file names differ, use repository search to select the current equivalents; do not skip the surface/profile checks.

- [ ] **Step 2: Run repository canonical style/type/meta gates**

Use the repository-pinned Node/pnpm/uv PATH and run:

```bash
pnpm run format:check
pnpm run lint
pnpm run typecheck
pnpm run check:meta
```

Expected: all exit 0. Record Mypy source-file count and capability-parity percentage.

- [ ] **Step 3: Build and inspect package artifacts**

Run:

```bash
pnpm run package:check
```

Then inspect the produced sdist and wheel and assert both contain:

```text
kicad_mcp/project/reporting.py
kicad_mcp/tools/project_reporting.py
```

- [ ] **Step 4: Re-run explicit 386/386 descriptor parity on the exact final tree**

Compare against base `b73f1cc1...`. Expected normalized snapshots and SHA-256 are identical.

- [ ] **Step 5: Run benchmark-excluded full unit suite on the exact final tree**

Run:

```bash
.venv/bin/python scripts/run_pytest.py unit
```

Expected: exit 0, only known existing skips/warnings. Do not claim completion from a still-running job.

- [ ] **Step 6: Final verification before completion**

Run:

```bash
git diff --check
git status --short
```

Commit any final verification-only fixes only after their tests are rerun. The final worktree must be clean. Record final commit SHA and tree SHA.

- [ ] **Step 7: Publish and PR only the verified tree**

Publish `refactor/project-reporting` without touching the old dirty runtime worktree. Verify remote tree SHA equals the locally verified tree before opening the PR. PR body must reference #577, record architecture delta, TDD evidence, exact descriptor parity, full-unit/meta/package results, and state that behavior/public contracts are unchanged.

- [ ] **Step 8: Treat GitHub CI as the merge authority**

Before squash merge, require current-head success for required OS server/npm matrix, protocol schemas, scan, dependency review, CodeQL Python/JS, Live Model Release Policy, coverage, and `Required PR Gate`. Inspect Sonar/Codecov/security bot results and fix any tranche issue rather than bypassing it. After merge, verify the exact `main` merge SHA and post a #577 checkpoint.
