# Schematic Template Instantiation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `sch_instantiate_template` from the monolithic schematic FastMCP registry into a directly testable service and thin adapter without changing its public contract.

**Architecture:** Add one FastMCP-free template-instantiation service and one thin registration adapter. Keep `src/kicad_mcp/tools/schematic.py` as the composition root by injecting the bundled template directory and the existing lazy YAML loader factory.

**Tech Stack:** Python 3.13, FastMCP, PyYAML, pytest, Ruff, mypy, Pyright, existing architecture and metadata generators.

## Global Constraints

- Preserve the exact public tool name, signature, description, schema, annotations, argument ordering, lazy PyYAML behavior, error messages, and Markdown output.
- Do not change template schemas or add direct schematic mutation.
- Do not change `sch_list_templates`, `sch_get_template_info`, or semantic IR behavior.
- Keep the adapter `register()` function at or below 300 lines.
- Keep domain code independent of FastMCP and `kicad_mcp.tools.schematic`.
- Keep the committed tool-surface snapshot unchanged.

---

### Task 1: Add the FastMCP-free template instantiation service

**Files:**
- Create: `src/kicad_mcp/schematic/template_instantiation.py`
- Create: `tests/unit/test_schematic_template_instantiation_service.py`

**Interfaces:**
- Consumes: `templates_dir: pathlib.Path` and `yaml_loader_factory: Callable[[], Callable[[TextIO], Any]]`
- Produces: `SchematicTemplateInstantiationService.instantiate(template_name: str, prefix: str = "", params: dict[str, object] | None = None) -> str`

- [ ] Write direct tests that assert exact missing-template, absent-PyYAML, parse-error, defaults/overrides, prefix trimming, symbol numbering, net rendering, search substitution, empty-search fallback, placement-hint, and final Markdown behavior.
- [ ] Run `PYTHONPATH="$PWD/src" <python> -m pytest -q tests/unit/test_schematic_template_instantiation_service.py`; expect collection failure because the service module is absent.
- [ ] Implement the minimal injected service by moving the existing behavior without altering output text.
- [ ] Re-run the service tests; expect all pass.
- [ ] Run Ruff, mypy, and scoped Pyright for the new service and test.
- [ ] Commit with `refactor(schematic): extract template instantiation service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_template_instantiation.py`
- Create: `tests/unit/test_schematic_template_instantiation_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicTemplateInstantiationService`
- Produces: `SchematicTemplateInstantiationDependencies(service: SchematicTemplateInstantiationService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicTemplateInstantiationDependencies) -> None`

- [ ] Write adapter tests for the exact name `sch_instantiate_template`, unchanged docstring/description, schema and required fields, headless metadata, default arguments, argument forwarding, and service delegation.
- [ ] Run the adapter test; expect collection failure because the adapter module is absent.
- [ ] Implement the adapter, add service construction and registration to the composition root, and remove the nested legacy tool function.
- [ ] Run service, adapter, focused integration, schematic-authoring surface, and bundled-template tests; expect all pass.
- [ ] Commit with `refactor(schematic): delegate template instantiation registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_template_instantiation_architecture.py`

**Interfaces:**
- Consumes: architecture policy maps `DOMAIN_MODULES`, `PURE_HELPERS`, `FORBIDDEN_IMPORTS`, and `REGISTER_LINE_LIMITS`
- Produces: service purity, adapter isolation, and a 300-line registration limit for the new modules

- [ ] Write failing architecture tests requiring the service and adapter to be tracked, forbidding adapter imports from the monolith, and enforcing the 300-line limit.
- [ ] Run the architecture test; expect failure because policy entries are absent.
- [ ] Add the new modules to the architecture checker and re-run the focused architecture test plus `scripts/check_architecture_boundaries.py`.
- [ ] Run the committed tool-surface snapshot and compare the focused tool metadata against `main`; expect exact equality.
- [ ] Commit with `test(architecture): guard template instantiation boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-template-instantiation-service.md`

- [ ] Run focused coverage for the service and adapter and require at least 83%.
- [ ] Run formatting, Ruff, mypy, scoped Pyright, architecture, generated-doc checks, tool-surface snapshot, focused integration, and the full unit suite.
- [ ] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes in this plan.
- [ ] Commit with `docs(architecture): record template instantiation evidence`.

### Task 5: Open, review, and merge the pull request

- [ ] Push the branch and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
