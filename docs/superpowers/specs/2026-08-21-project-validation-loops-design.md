# Project Validation Loops Extraction Design

## Context

Issue #577 is decomposing `src/kicad_mcp/tools/project.py` into focused domain services and thin FastMCP adapters without changing the public MCP surface. After #738, the largest adjacent responsibilities still owned directly by `project.register()` are `project_auto_fix_loop` (195 lines) and `project_full_validation_loop` (112 lines). Both implement the same project-gate/fixer orchestration concern and should move together so the shared behavior has one owner.

## Goal

Extract both validation-loop tools into a FastMCP-independent project service plus a thin FastMCP adapter while preserving tool names, order, schemas, descriptions, annotations, structured payloads, progress/sampling behavior, fixer invocation semantics, and rendered text exactly.

## Non-goals

- Do not change gate evaluation rules, fixer registry contents, or fixer ordering.
- Do not change the public tool catalog or progressive-disclosure profiles.
- Do not redesign sampling prompts or progress messages.
- Do not change validation status precedence or release-readiness semantics.
- Do not combine this tranche with `project_gate_trend`, `project_design_report`, design-intent tools, or `kicad_help`.

## Architecture

### Domain service: `src/kicad_mcp/project/validation_loops.py`

Create a FastMCP-free module that owns:

- `GateOutcomeLike` protocol with `name`, `status`, `summary`, and `details`.
- `FixerActionLike` protocol with `tool`, `description`, `auto_applicable`, and `callable_import`.
- `AutoFixAction` Pydantic model.
- `AutoFixLoopPayload` Pydantic model.
- `ProjectValidationLoopService` dataclass.

The service receives all environment-specific behavior by injection:

```python
@dataclass(frozen=True, slots=True)
class ProjectValidationLoopService:
    evaluate_project_gate: Callable[[], Sequence[GateOutcomeLike]]
    fixers_for_gate: Callable[[str], Sequence[FixerActionLike]]
    resolve_callable: Callable[[str], Callable[[], object] | None]
```

The service exposes:

```python
async def auto_fix_loop(
    self,
    *,
    max_iterations: int = 5,
    sample_guidance: Callable[[GateOutcomeLike], Awaitable[str]],
    report_progress: Callable[[float, float, str], Awaitable[None]],
) -> AutoFixLoopPayload

def full_validation_loop(
    self,
    *,
    max_iterations: int = 5,
    fix_tier: Literal["auto_only", "suggest"] = "auto_only",
) -> AutoFixLoopPayload
```

The module owns a private structural combined-status helper with the exact existing precedence:

1. `EMPTY`
2. `BLOCKED`
3. `FAIL`
4. `WARN`
5. `PASS`

That removes the need for the domain service to import `tools.gates` merely to convert structurally identical outcomes.

### Adapter: `src/kicad_mcp/tools/project_validation_loops.py`

Create a thin adapter that owns infrastructure-only behavior:

- `resolve_fixer_callable(import_str)` uses `importlib` to resolve `kicad_mcp.<module>:<callable>` and returns `None` on malformed/missing imports, matching current behavior.
- `_sample_guidance(ctx, outcome, prompt_builder)` performs `Context.sample`, returns empty guidance when sampling is unavailable/fails, and preserves `max_tokens=256` plus the current system prompt.
- `_report_progress(ctx, current, total, message)` calls `ctx.report_progress` and ignores `ValueError`, matching current behavior.
- `register()` registers `project_auto_fix_loop` first and `project_full_validation_loop` second at their current public positions.

`register()` delegates business behavior to `ProjectValidationLoopService`; it must stay within the architecture checker line limit and must not import `kicad_mcp.tools.project`.

### Composition root: `src/kicad_mcp/tools/project.py`

- Remove the local `AutoFixAction` and `AutoFixLoopPayload` definitions and import/re-export them from `project.validation_loops` so existing internal import paths continue to resolve.
- Remove both nested validation-loop implementations from `register()`.
- Instantiate `ProjectValidationLoopService` with the existing `_evaluate_project_gate`, `fixers_for_gate`, and adapter resolver.
- Register the new adapter exactly where the old tools appeared: after `project_get_next_action` and before `project_gate_trend`.
- Keep `sampling_prompt_for_gate` wired into the adapter; do not change prompt generation.

## Behavior Preservation

### `project_auto_fix_loop`

- Clamp `max_iterations` to `1..20`.
- Report progress at `0/100` before gate evaluation, at the existing intermediate percentage after each applied-fix iteration, and `100/100` on completion.
- Evaluate gates once before looping and once after each iteration that applied at least one auto-fixer.
- For each non-PASS outcome, use the first auto-applicable fixer.
- Resolver failure skips that fixer exactly as today.
- Fixer exceptions append the existing log text and do not abort processing of later gate outcomes in that iteration.
- Sampling is requested only for remaining non-PASS actions and failures yield empty guidance.
- Preserve exact payload fields and rendered text, including the final instruction to call `project_auto_fix_loop()` again.

### `project_full_validation_loop`

- Clamp `max_iterations` to `1..20` and count the initial evaluation as iteration 1.
- In `suggest` mode, never invoke an auto-fixer.
- In `auto_only` mode, repeatedly target the first non-PASS blocker and use its first auto-applicable fixer.
- Resolver failure or fixer exception stops the loop exactly as today.
- Preserve action selection preference: first non-auto agent fixer, otherwise auto-fixer, otherwise `project_quality_gate`.
- Preserve exact rendered text and readiness/remaining counts.

## Public Compatibility Contract

The tranche is complete only if all of the following remain unchanged against `main`:

- Tool names and order in the `agent_full` descriptor list.
- `project_auto_fix_loop` input schema, description, annotations, and output model shape.
- `project_full_validation_loop` input schema, description, annotations, and output model shape.
- Existing progressive-disclosure inclusion/exclusion behavior.
- Integration behavior in `tests/integration/test_project_validation_loop.py`.

The target descriptor parity is 386/386 byte-identical entries.

## Architecture Guardrails

Update `scripts/check_architecture_boundaries.py` to track:

- `kicad_mcp.project.validation_loops` as a domain/pure helper module.
- `kicad_mcp.tools.project_validation_loops` as a tracked adapter.
- A forbidden adapter dependency on `kicad_mcp.tools.project`.
- A bounded `register()` line span (target <=55 lines).

Add a root-ownership assertion proving `project.register()` no longer directly defines either validation-loop tool.

## Test Strategy

Use TDD and preserve the existing integration tests.

1. Domain service tests cover:
   - auto-fixer application and re-evaluation;
   - remaining agent action selection;
   - sampling guidance propagation;
   - progress callback sequence;
   - fixer exception logging;
   - resolver-miss behavior;
   - full-validation `auto_only` mutation;
   - full-validation `suggest` non-mutation;
   - status precedence and max-iteration clamping.
2. Adapter registration tests assert exact tool names/order, schemas, descriptions, delegation, and Context bridges.
3. Architecture tests assert module tracking, adapter independence, bounded registration, and root ownership removal.
4. Existing integration validation-loop tests must pass unchanged.
5. Public-surface snapshot/profile tests and a generated `agent_full` descriptor comparison must remain exact.
6. Final gates: Ruff format/check, Mypy, architecture checker, `check:meta`, package build, focused tests, benchmark-excluded full unit suite, and PR CI matrix.

## Expected Architecture Delta

Removing the two nested tools should reduce direct nested MCP tools in `project.register()` from 12 to 10 and remove roughly 300 lines of orchestration from the project monolith, replacing them with a focused service and a small adapter.
