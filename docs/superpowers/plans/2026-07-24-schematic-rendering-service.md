# Schematic Rendering Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Extract `sch_live_preview`, `sch_render_png`, and `sch_render_visual_diff` from the monolithic schematic FastMCP registry into a directly testable service and thin adapter without changing their public contracts or compatibility seams.

**Architecture:** Add one FastMCP-free rendering service with an internal response data object and explicit injected dependencies, plus one thin registration adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root and inject lazy wrappers around existing helper functions so post-registration monkeypatch behavior remains intact.

**Tech Stack:** Python 3.13, FastMCP, pytest, Ruff, mypy, Pyright, existing schematic rendering and architecture tooling.

## Global Constraints

- Preserve exact public names, signatures, descriptions, schemas, annotations, validation messages, metadata, state transitions, artifact paths, image/text response selection, and observable behavior.
- Do not change renderer algorithms, live-preview contracts, mutation snapshots, target resolution, or runtime dependencies.
- Keep the adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `kicad_mcp.tools.schematic`.
- Keep the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free rendering service

**Files:**
- Create: `src/kicad_mcp/schematic/rendering.py`
- Create: `tests/unit/test_schematic_rendering_service.py`

**Interfaces:**
- Produces: `SchematicRenderingResponse`
- Produces: `SchematicRenderingService.live_preview(...)`
- Produces: `SchematicRenderingService.render_png(...)`
- Produces: `SchematicRenderingService.render_visual_diff(...)`

- [x] Write direct tests for argument validation, empty and successful PNG rendering, output/render failures, visual-diff snapshot states and success, live-preview initialization/no-change/debounce/forced/render/reload paths, state writes, and image selection.
- [x] Run the service test; expect collection failure because the module is absent.
- [x] Implement structural protocols, response data object, and minimal injected service while preserving legacy output byte-for-byte.
- [x] Re-run service tests; expect all pass.
- [x] Run Ruff, mypy, and scoped Pyright.
- [x] Commit with `refactor(schematic): extract rendering service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_rendering.py`
- Create: `tests/unit/test_schematic_rendering_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicRenderingService`
- Produces: `SchematicRenderingDependencies(service: SchematicRenderingService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicRenderingDependencies) -> None`

- [x] Write adapter tests for exact names, descriptions, schemas, headless annotations, delegation, and text/image response conversion.
- [x] Run the adapter test; expect collection failure because the adapter module is absent.
- [x] Implement the adapter, wire lazy compatibility dependencies in the composition root, and remove the three nested legacy tool functions.
- [x] Run service, adapter, focused integration, live-preview fallback, protocol-contract, and tool-surface tests.
- [x] Commit with `refactor(schematic): delegate rendering registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_rendering_architecture.py`

- [x] Write failing architecture tests requiring the service and adapter to be tracked, forbidding monolith imports, and enforcing the 300-line limit.
- [x] Run the architecture test; expect failure because policy entries are absent.
- [x] Add the new modules to the architecture checker and rerun focused architecture plus the checker.
- [x] Compare exact full-server metadata for all three tools against `main` and run the committed tool-surface snapshot.
- [x] Commit with `test(architecture): guard rendering boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-24-schematic-rendering-service.md`

- [x] Run focused service/adapter coverage and require at least 83%.
- [x] Run formatting, Ruff, mypy, scoped Pyright, architecture, metadata/generated-doc checks, tool-surface snapshot, strict docs, latency, security, workflow, package, focused integration, and full unit gates.
- [x] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes.
- [x] Commit with `docs(architecture): record rendering evidence`.

## Verification Evidence

- TDD red/green evidence was observed for the absent rendering service, absent adapter, and missing architecture-policy entries before implementation.
- Direct service and adapter suite: 13 tests passed; architecture suite: 3 tests passed; focused integration, fallback, protocol-contract, and tool-surface suite: 15 tests passed.
- Focused coverage: 193 statements, 98% total (`rendering.py` 165 statements at 99%; `schematic_rendering.py` 28 statements at 96%), exceeding the 83% requirement.
- Exact full-server metadata matches `main` for all three tools: names, descriptions, input schemas, output schemas, annotations, MCP metadata, and headless/KiCad-running metadata.
- Committed tool-surface snapshot passed unchanged.
- Main schematic `register()` span decreased from 1,657 lines on `main` to 1,368 lines; the new adapter `register()` is 93 lines.
- Full selected unit gate passed: 1,749 tests collected, 5 skipped, no failures.
- Focused schematic PNG render, visual diff, live-preview debounce/child-sheet/bounds, renderer-fallback, protocol-contract, and snapshot tests passed.
- Formatting, Ruff, mypy, scoped Pyright, architecture, metadata, generated references, parity, profile, tool-contract, compatibility, runtime-policy, strict MkDocs, latency benchmark, Bandit, dependency audit, GitHub Actions policy, zizmor, actionlint workflow checks, package build, and package metadata checks all passed.
- The repository bootstrap reproduced the known `actionlint-py` wheel-install `EPERM` on the exec-agent filesystem. Verification used the locked environment with `uv sync --all-extras --frozen --no-install-package actionlint-py` and the exact cached actionlint binary; no source or lockfile changes were required.

### Task 5: Open, review, and merge the pull request

- [ ] Push and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
