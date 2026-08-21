# Project Validation Loops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `project_auto_fix_loop` and `project_full_validation_loop` from the project monolith into a pure project service and thin FastMCP adapter without changing their public MCP contracts or behavior.

**Architecture:** `kicad_mcp.project.validation_loops` owns payload models and loop orchestration using structural protocols plus injected gate/fixer/resolver callbacks. `kicad_mcp.tools.project_validation_loops` owns dynamic import resolution and FastMCP `Context` bridges for sampling/progress. `tools.project` becomes composition-only for these two tools.

**Tech Stack:** Python 3.13, Pydantic v2, FastMCP, pytest/pytest-anyio, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-08-21-project-validation-loops-design.md`

## Global Constraints

- Preserve tool names/order, schemas, descriptions, annotations, payload fields, text rendering, sampling prompt, and progress messages exactly.
- Keep validation status precedence exactly `EMPTY > BLOCKED > FAIL > WARN > PASS`.
- Keep `max_iterations` clamped to `1..20`.
- Keep `project.validation_loops` FastMCP-free and independent of `kicad_mcp.tools.project`.
- Keep adapter `register()` at or below 55 lines and forbid adapter import of the project monolith.
- Preserve `agent_full` descriptor parity at 386/386 byte-identical entries.
- Do not modify gate rules, fixer registry contents/order, design-report/trend tools, or progressive-disclosure policy.

---

### Task 1: Pure validation-loop service and payload models

**Files:**
- Create: `src/kicad_mcp/project/validation_loops.py`
- Create: `tests/unit/test_project_validation_loop_service.py`

**Interfaces:**
- Consumes: injected `evaluate_project_gate()`, `fixers_for_gate(name)`, and `resolve_callable(import_str)` callbacks.
- Produces: `GateOutcomeLike`, `FixerActionLike`, `AutoFixAction`, `AutoFixLoopPayload`, `ProjectValidationLoopService.auto_fix_loop()`, and `ProjectValidationLoopService.full_validation_loop()`.

- [ ] **Step 1: Write failing service tests**

Create tests using small fake outcome/fixer dataclasses. Cover these exact behaviors:

```python
@pytest.mark.anyio
async def test_auto_fix_loop_applies_fixer_re_evaluates_and_reports_progress() -> None:
    outcomes = iter([
        [Outcome("Schematic", "FAIL", "unannotated")],
        [Outcome("Placement", "WARN", "review placement")],
    ])
    calls: list[str] = []
    progress: list[tuple[float, float, str]] = []
    service = ProjectValidationLoopService(
        evaluate_project_gate=lambda: next(outcomes),
        fixers_for_gate=lambda name: [
            Fixer("sch_annotate", "annotate", True, "tools.schematic:run_auto_annotate")
        ] if name == "Schematic" else [
            Fixer("pcb_place_decoupling_caps", "move caps", False, "")
        ],
        resolve_callable=lambda _path: lambda: calls.append("fixed") or "annotated",
    )
    result = await service.auto_fix_loop(
        max_iterations=3,
        sample_guidance=lambda _outcome: _async_value("guidance"),
        report_progress=lambda current, total, message: _record_progress(
            progress, current, total, message
        ),
    )
    assert calls == ["fixed"]
    assert result.gate_status == "WARN"
    assert result.remaining_issues == 1
    assert result.actions[0].agent_tool == "pcb_place_decoupling_caps"
    assert result.actions[0].sampling_guidance == "guidance"
    assert progress[0] == (0, 100, "Project quality gate is being evaluated...")
    assert progress[-1] == (100, 100, "Project auto-fix loop completed.")
```

Also add tests for:
- resolver returning `None` skips mutation;
- fixer exceptions preserve the current log text and continue action planning;
- max iterations clamps to 1 and 20;
- status precedence includes EMPTY/BLOCKED/FAIL/WARN/PASS;
- `full_validation_loop(auto_only)` applies the first auto-fixer and re-evaluates;
- `full_validation_loop(suggest)` never resolves/invokes a fixer;
- `full_validation_loop` resolver miss and fixer exception stop the loop with current text/action semantics.

- [ ] **Step 2: Run the new service test file and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_project_validation_loop_service.py
```

Expected: collection/import failure because `kicad_mcp.project.validation_loops` does not exist.

- [ ] **Step 3: Implement the minimal domain module**

Create `validation_loops.py` with:

```python
class GateOutcomeLike(Protocol):
    name: str
    status: str
    summary: str
    details: list[str]

class FixerActionLike(Protocol):
    tool: str
    description: str
    auto_applicable: bool
    callable_import: str

class AutoFixAction(BaseModel):
    gate: str
    status: str
    auto_fixed: bool = False
    auto_fix_description: str = ""
    agent_tool: str = ""
    agent_description: str = ""
    sampling_guidance: str = ""

class AutoFixLoopPayload(BaseModel):
    text: str
    gate_status: str
    iterations_used: int = 0
    actions: list[AutoFixAction] = Field(default_factory=list)
    remaining_issues: int = 0
    ready_for_release: bool = False
```

Implement `_combined_status()` structurally with the exact precedence from the spec. Implement `ProjectValidationLoopService` and copy the existing loop semantics exactly, replacing direct FastMCP sampling/progress calls with injected async callbacks.

- [ ] **Step 4: Run service tests and verify GREEN**

```bash
.venv/bin/pytest -q tests/unit/test_project_validation_loop_service.py
```

Expected: all service tests pass.

- [ ] **Step 5: Run Ruff and Mypy on the new domain module**

```bash
.venv/bin/ruff check src/kicad_mcp/project/validation_loops.py tests/unit/test_project_validation_loop_service.py
.venv/bin/ruff format --check src/kicad_mcp/project/validation_loops.py tests/unit/test_project_validation_loop_service.py
.venv/bin/mypy src/kicad_mcp/project/validation_loops.py
```

Expected: exit 0 for all three commands.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/kicad_mcp/project/validation_loops.py tests/unit/test_project_validation_loop_service.py
git commit -m "refactor(project): extract validation loop service"
```

---

### Task 2: Thin FastMCP adapter and Context bridges

**Files:**
- Create: `src/kicad_mcp/tools/project_validation_loops.py`
- Create: `tests/unit/test_project_validation_loop_registration.py`

**Interfaces:**
- Consumes: `ProjectValidationLoopService`, `sampling_prompt_for_gate`, FastMCP `Context`.
- Produces: `resolve_fixer_callable()`, bounded `register()`, `project_auto_fix_loop`, and `project_full_validation_loop` registrations.

- [ ] **Step 1: Write failing adapter tests**

Use a fake service recording method arguments. Assert:

```python
assert [tool.name for tool in mcp._tool_manager.list_tools()] == [
    "project_auto_fix_loop",
    "project_full_validation_loop",
]
```

Assert exact descriptions and parameter defaults/types from the current tools. For `project_auto_fix_loop`, invoke the registered function with a fake Context that records `report_progress` and `sample`; make the fake service call both injected callbacks and assert the bridge preserves:

```python
max_tokens == 256
system_prompt == "You are a KiCad expert. Reply briefly and directly."
```

Add tests that unavailable sampling returns `""`, sampling exceptions return `""`, progress `ValueError` is swallowed, and `resolve_fixer_callable` returns `None` for malformed/missing callables.

- [ ] **Step 2: Run adapter tests and verify RED**

```bash
.venv/bin/pytest -q tests/unit/test_project_validation_loop_registration.py
```

Expected: import failure because `kicad_mcp.tools.project_validation_loops` does not exist.

- [ ] **Step 3: Implement the adapter**

Create top-level infrastructure helpers:

```python
def resolve_fixer_callable(import_str: str) -> Callable[[], object] | None: ...

async def _sample_guidance(
    ctx: Context[Any, Any, Any] | None,
    outcome: GateOutcomeLike,
    prompt_builder: Callable[[str, str, list[str] | None], str],
) -> str: ...

async def _report_progress(
    ctx: Context[Any, Any, Any] | None,
    current: float,
    total: float,
    message: str,
) -> None: ...
```

Define dependencies:

```python
@dataclass(frozen=True)
class ProjectValidationLoopDependencies:
    service: ProjectValidationLoopService
    sampling_prompt_for_gate: Callable[[str, str, list[str] | None], str]
```

Keep `register()` bounded by delegating sampling/progress to the top-level helpers. Register auto-fix first, full-validation second, preserving current signatures/docstrings.

- [ ] **Step 4: Run adapter tests and verify GREEN**

```bash
.venv/bin/pytest -q tests/unit/test_project_validation_loop_registration.py
```

Expected: all adapter tests pass.

- [ ] **Step 5: Run Ruff/Mypy for Task 2**

```bash
.venv/bin/ruff check src/kicad_mcp/tools/project_validation_loops.py tests/unit/test_project_validation_loop_registration.py
.venv/bin/ruff format --check src/kicad_mcp/tools/project_validation_loops.py tests/unit/test_project_validation_loop_registration.py
.venv/bin/mypy src/kicad_mcp/tools/project_validation_loops.py
```

Expected: exit 0.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/kicad_mcp/tools/project_validation_loops.py tests/unit/test_project_validation_loop_registration.py
git commit -m "refactor(project): add validation loop adapter"
```

---

### Task 3: Composition-root extraction, architecture guards, and compatibility proof

**Files:**
- Modify: `src/kicad_mcp/tools/project.py`
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_project_validation_loop_architecture.py`
- Existing regression: `tests/integration/test_project_validation_loop.py`
- Existing surface regression: `tests/integration/test_tool_surface_snapshot.py`
- Existing profile regression: `tests/unit/test_progressive_disclosure_profiles.py`

**Interfaces:**
- Consumes: service/adapter from Tasks 1-2 and existing `_evaluate_project_gate`, `fixers_for_gate`, `sampling_prompt_for_gate`.
- Produces: unchanged public MCP surface with the project root no longer directly owning either validation-loop tool.

- [ ] **Step 1: Write failing architecture/ownership tests**

Assert:

```python
assert "kicad_mcp.project.validation_loops" in boundaries.DOMAIN_MODULES
assert "kicad_mcp.project.validation_loops" in boundaries.PURE_HELPERS
assert "kicad_mcp.tools.project_validation_loops" in boundaries.DOMAIN_MODULES
assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.project_validation_loops"] == 55
```

Parse `tools/project.py::register` and assert neither `project_auto_fix_loop` nor `project_full_validation_loop` remains a nested function. Assert the adapter does not import `kicad_mcp.tools.project`.

- [ ] **Step 2: Run architecture tests and verify RED**

```bash
.venv/bin/pytest -q tests/unit/test_project_validation_loop_architecture.py
```

Expected: failures because checker entries and root extraction are not yet present.

- [ ] **Step 3: Wire the service/adapter into `tools.project`**

At module imports:

```python
from ..project.validation_loops import AutoFixAction, AutoFixLoopPayload, ProjectValidationLoopService
from . import project_validation_loops
```

Remove local payload model definitions. Inside `register()`, immediately after `project_next_action.register(...)`, import `_evaluate_project_gate`, construct:

```python
validation_loop_service = ProjectValidationLoopService(
    evaluate_project_gate=_evaluate_project_gate,
    fixers_for_gate=fixers_for_gate,
    resolve_callable=project_validation_loops.resolve_fixer_callable,
)
project_validation_loops.register(
    mcp,
    project_validation_loops.ProjectValidationLoopDependencies(
        service=validation_loop_service,
        sampling_prompt_for_gate=sampling_prompt_for_gate,
    ),
)
```

Delete both old nested tool implementations. Leave `project_gate_trend` immediately after the new registration so public ordering is preserved.

- [ ] **Step 4: Update architecture checker**

Add `_PROJECT_VALIDATION_LOOPS_ADAPTER`, track the new domain/adapter files, add the domain module to `PURE_HELPERS`, forbid adapter imports from `_PROJECT_ROOT_MODULE`, and set register limit to 55.

- [ ] **Step 5: Run focused GREEN suite**

```bash
.venv/bin/pytest -q \
  tests/unit/test_project_validation_loop_service.py \
  tests/unit/test_project_validation_loop_registration.py \
  tests/unit/test_project_validation_loop_architecture.py \
  tests/integration/test_project_validation_loop.py
.venv/bin/python scripts/check_architecture_boundaries.py
```

Expected: all tests and architecture checker pass.

- [ ] **Step 6: Prove public-surface compatibility**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_tool_surface_snapshot.py \
  tests/unit/test_progressive_disclosure_profiles.py \
  tests/unit/test_tool_metadata_lint.py \
  tests/unit/test_server_startup.py
```

Then generate the `agent_full` MCP descriptor list on `main` and on the branch with the same script used by prior #577 tranches; compare serialized descriptors and require 386/386 exact equality.

Expected: all tests pass and descriptor diff is empty.

- [ ] **Step 7: Run final static/meta/package gates**

```bash
corepack pnpm run format:check
corepack pnpm run lint
corepack pnpm run typecheck
corepack pnpm run check:meta
corepack pnpm run package:check
git diff --check
```

Use repo-pinned Node/Corepack path if `node` is not on PATH. Expected: exit 0.

- [ ] **Step 8: Run benchmark-excluded full unit suite**

```bash
.venv/bin/python scripts/run_pytest.py unit
```

Expected: 100% progress, exit 0; existing warnings/skips are acceptable if no new failures occur.

- [ ] **Step 9: Measure architecture delta and commit**

Measure `tools.project` line count and direct nested MCP functions in `register()`. Target: nested tools 12 -> 10 and roughly 300 lines removed from the monolith.

```bash
git add src/kicad_mcp/tools/project.py scripts/check_architecture_boundaries.py \
  tests/unit/test_project_validation_loop_architecture.py
git commit -m "refactor(project): wire validation loop service"
```

- [ ] **Step 10: Publish and open PR**

Push the verified branch, create a PR titled `refactor(project): extract validation loops`, reference #577, include exact tree hash and all verification evidence, and merge only after Required PR Gate plus required OS/security/code-quality checks pass.
