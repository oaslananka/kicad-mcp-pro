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

- [x] Write direct tests that assert exact missing-template, absent-PyYAML, parse-error, defaults/overrides, prefix trimming, symbol numbering, net rendering, search substitution, empty-search fallback, placement-hint, and final Markdown behavior.
- [x] Run `PYTHONPATH="$PWD/src" <python> -m pytest -q tests/unit/test_schematic_template_instantiation_service.py`; expect collection failure because the service module is absent.
- [x] Implement the minimal injected service by moving the existing behavior without altering output text.
- [x] Re-run the service tests; expect all pass.
- [x] Run Ruff, mypy, and scoped Pyright for the new service and test.
- [x] Commit with `refactor(schematic): extract template instantiation service`.

### Task 2: Add the thin adapter and composition wiring

**Files:**
- Create: `src/kicad_mcp/tools/schematic_template_instantiation.py`
- Create: `tests/unit/test_schematic_template_instantiation_registration.py`
- Modify: `src/kicad_mcp/tools/schematic.py`

**Interfaces:**
- Consumes: `SchematicTemplateInstantiationService`
- Produces: `SchematicTemplateInstantiationDependencies(service: SchematicTemplateInstantiationService)`
- Produces: `register(mcp: FastMCP, dependencies: SchematicTemplateInstantiationDependencies) -> None`

- [x] Write adapter tests for the exact name `sch_instantiate_template`, unchanged docstring/description, schema and required fields, headless metadata, default arguments, argument forwarding, and service delegation.
- [x] Run the adapter test; expect collection failure because the adapter module is absent.
- [x] Implement the adapter, add service construction and registration to the composition root, and remove the nested legacy tool function.
- [x] Run service, adapter, focused integration, schematic-authoring surface, and bundled-template tests; expect all pass.
- [x] Commit with `refactor(schematic): delegate template instantiation registration`.

### Task 3: Enforce architecture and public-contract stability

**Files:**
- Modify: `scripts/check_architecture_boundaries.py`
- Create: `tests/unit/test_schematic_template_instantiation_architecture.py`

**Interfaces:**
- Consumes: architecture policy maps `DOMAIN_MODULES`, `PURE_HELPERS`, `FORBIDDEN_IMPORTS`, and `REGISTER_LINE_LIMITS`
- Produces: service purity, adapter isolation, and a 300-line registration limit for the new modules

- [x] Write failing architecture tests requiring the service and adapter to be tracked, forbidding adapter imports from the monolith, and enforcing the 300-line limit.
- [x] Run the architecture test; expect failure because policy entries are absent.
- [x] Add the new modules to the architecture checker and re-run the focused architecture test plus `scripts/check_architecture_boundaries.py`.
- [x] Run the committed tool-surface snapshot and compare the focused tool metadata against `main`; expect exact equality.
- [x] Commit with `test(architecture): guard template instantiation boundaries`.

### Task 4: Record evidence and run repository gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-23-schematic-template-instantiation-service.md`

- [x] Run focused coverage for the service and adapter and require at least 83%.
- [x] Run formatting, Ruff, mypy, scoped Pyright, architecture, generated-doc checks, tool-surface snapshot, focused integration, and the full unit suite.
- [x] Record exact metadata equality, focused/full test counts, coverage, register spans, and gate outcomes in this plan.
- [x] Commit with `docs(architecture): record template instantiation evidence`.

## Verification Evidence

- Exact full-server metadata for `sch_instantiate_template` matches `main`: name, description, input schema, required fields, defaults, output schema, annotations, headless metadata, and argument ordering are identical.
- The committed tool-surface snapshot passes without regeneration.
- The main schematic `register()` span decreased from 1,843 to 1,745 lines; the template-instantiation adapter `register()` spans 31 lines.
- Direct service and adapter tests passed with 100% focused line coverage across 70 statements.
- Focused service, registration, architecture, bundled-template integration, authoring-surface, and tool-surface verification passed across 16 tests.
- The full unit suite passed with 1,724 selected tests, six expected skips, the existing KiCad CLI availability warnings, and the existing Windows-daemon async-mock warning.
- Metadata synchronization, MCP manifest, Docker metadata, generated tool docs, capability parity, toolsets, progressive-disclosure profiles, adapter matrix, tool contracts, architecture, compatibility matrix, runtime policy, formatting, Ruff, mypy, scoped strict Pyright, strict MkDocs, and the latency benchmark all pass.
- Bandit reported no medium/high findings across 59,888 lines, pip-audit reported no known vulnerabilities, GitHub Actions policy passed for 24 workflows, actionlint parsed/linted all 24 workflows, and zizmor reported no high-severity findings.
- Source and wheel builds plus package metadata validation pass.
- The repository bootstrap hit an exec-agent filesystem `EPERM` while packaging `actionlint-py`; the remaining 184 dependencies installed from the frozen lock, and the downloaded checksum-backed actionlint binary was used to complete the workflow lint gate.
- No runtime dependency, template schema, public tool contract, lazy PyYAML behavior, fallback ordering, parameter resolution, reference numbering, search substitution, error message, or Markdown result changed.

### Task 5: Open, review, and merge the pull request

- [ ] Push the branch and open a professional English PR referencing #434.
- [ ] Inspect CI, bot comments, reviews, and review threads.
- [ ] Address every actionable finding and rerun affected checks.
- [ ] Merge only after required checks pass and the merge state is clean.
- [ ] Update `main` and remove the worktree and local/remote topic branch.
