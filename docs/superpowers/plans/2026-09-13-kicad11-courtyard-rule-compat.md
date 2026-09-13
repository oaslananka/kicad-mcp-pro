# KiCad 11 Preview Courtyard Rule Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the KiCad 11 preview canary by removing a nightly-incompatible, redundant footprint predicate from the maintained courtyard-rule fixtures while preserving stable KiCad 10 behavior.

**Architecture:** This is a fixture-contract repair, not a product-code workaround. A corpus-level regression test protects the shared `.kicad_dru` inputs, then the seven affected checked-in fixture rules are minimally updated. The stale fixture-maintenance documentation is corrected to the validation commands that actually exist in this repository.

**Tech Stack:** Python 3.13 / pytest, KiCad `.kicad_dru` fixture files, pnpm fixture package checks, GitHub Actions KiCad Live E2E.

**Spec:** `docs/superpowers/specs/2026-09-13-kicad11-courtyard-rule-compat-design.md`

## Global Constraints

- Do not change MCP product behavior or public tool contracts.
- Do not weaken the KiCad 11 preview smoke or convert real failures into skips.
- Preserve the `courtyard_clearance (min 0.25mm)` fixture intent.
- Preserve stable KiCad 10.0.6 DRC expectations.
- Do not invent a replacement fixture generator in this bounded compatibility fix.
- Final merge remains gated by repository-required CI and live KiCad canaries.

---

### Task 1: Add the fixture compatibility regression

**Files:**
- Modify: `tests/unit/test_kicad_canary.py`

**Interfaces:**
- Consumes: `kicad_canary.FIXTURE_ROOT`, the checked-in shared fixture corpus.
- Produces: a regression guard rejecting the removed `A.Footprint` / `B.Footprint` custom-rule property.

- [ ] **Step 1: Write the failing test**

Append a focused test that recursively reads `.kicad_dru` files and reports every fixture still using the removed property:

```python
def test_shared_dru_fixtures_avoid_removed_kicad_10_99_footprint_property() -> None:
    offenders = []
    for path in sorted(kicad_canary.FIXTURE_ROOT.rglob("*.kicad_dru")):
        raw = path.read_text(encoding="utf-8")
        if "A.Footprint" in raw or "B.Footprint" in raw:
            offenders.append(path.relative_to(kicad_canary.FIXTURE_ROOT).as_posix())

    assert offenders == []
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_kicad_canary.py::test_shared_dru_fixtures_avoid_removed_kicad_10_99_footprint_property -q
```

Expected: FAIL listing the seven maintained `.kicad_dru` fixtures that contain the predicate.

- [ ] **Step 3: Record the RED evidence and do not change the test**

Confirm the failure is caused by the exact `A.Footprint` / `B.Footprint` content, not a path or test-environment error.

### Task 2: Repair the maintained fixture rules

**Files:**
- Modify: `packages/kicad-fixtures/fixtures/clean-led-kicad10/clean-led-kicad10.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/drc-courtyard-error/drc-courtyard-error.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/kicad-10-0-3-regressions/kicad-10-0-3-regressions.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/stale-diagnostics-kicad10/stale-diagnostics-kicad10.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/large-board/large-board.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/paths-with-spaces/path case.kicad_dru`
- Modify: `packages/kicad-fixtures/fixtures/unicode-path-çöğü/unicode-çöğü.kicad_dru`

**Interfaces:**
- Consumes: the existing `(constraint courtyard_clearance (min 0.25mm))` rule in each fixture.
- Produces: the same courtyard-clearance rule without the nightly-invalid redundant condition.

- [ ] **Step 1: Make the minimal data change**

In each affected courtyard rule, keep:

```text
(constraint courtyard_clearance (min 0.25mm))
```

and remove only:

```text
(condition "A.Footprint != '' && B.Footprint != ''")
```

Do not change rule names, minimum values, or unrelated rules.

- [ ] **Step 2: Run the focused regression to verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_kicad_canary.py::test_shared_dru_fixtures_avoid_removed_kicad_10_99_footprint_property -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete canary unit module**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_kicad_canary.py -q
```

Expected: all tests pass.

### Task 3: Correct fixture maintenance documentation

**Files:**
- Modify: `packages/kicad-fixtures/README.md`

**Interfaces:**
- Consumes: current `packages/kicad-fixtures/package.json` scripts and root `package.json` verification entry points.
- Produces: maintenance instructions that can actually be executed in the current repository.

- [ ] **Step 1: Replace the stale regeneration section**

Remove claims that `scripts/generate-kicad-fixture-corpus.mjs`, `fixtures:kicad:generate`, and `test:fixtures` exist. Document that fixture source files and expected outputs are checked in and changes must be reviewed explicitly.

Use the current focused validation command:

```bash
uv run --all-extras python -m pytest tests/unit/test_kicad_canary.py -q
```

State that the historical generator/root fixture scripts are absent from the migrated repository, and that live KiCad compatibility is authoritative in the repository KiCad canary workflows.

- [ ] **Step 2: Validate the documented command**

Run:

```bash
uv run --all-extras python -m pytest tests/unit/test_kicad_canary.py -q
```

Expected: PASS.

### Task 4: Run repository change-scoped verification

**Files:**
- Verify all files changed in Tasks 1–3 plus this spec/plan.

**Interfaces:**
- Consumes: final working tree.
- Produces: review-ready branch evidence.

- [ ] **Step 1: Run formatting/lint checks for the Python test**

Run:

```bash
.venv/bin/ruff check tests/unit/test_kicad_canary.py
.venv/bin/ruff format --check tests/unit/test_kicad_canary.py
```

Expected: PASS.

- [ ] **Step 2: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 3: Run the repository pre-push mapper after publishing/committing the final tree**

Run:

```bash
.venv/bin/python scripts/hook_pre_push.py
```

Expected: all change-scoped checks pass.

- [ ] **Step 4: Open a dedicated PR against `main`**

Use a non-release Conventional Commit category such as `test(fixtures): restore KiCad 11 courtyard rule compatibility` so this fixture-only repair does not create an unintended package version bump.

- [ ] **Step 5: Require live KiCad evidence before merge**

Confirm on the exact PR head:

```text
KiCad 10.0.6 canary: success
KiCad 11 preview smoke: success
Required PR Gate: success
```

Do not merge if the preview lane fails for a new reason; diagnose it independently.

- [ ] **Step 6: Merge the fixture PR, then refresh release PR #892**

After the fixture PR merges to `main`, ensure release PR #892 includes the updated base and reruns the live KiCad checks before merging/releasing v3.34.6.
### Task 5: Ensure shared fixture changes trigger live KiCad CI

**Files:**
- Modify: `.github/workflows/kicad-live-e2e.yml`
- Modify: `tests/unit/test_kicad11_adapter_workflow.py`

**Interfaces:**
- Consumes: the checked-in shared corpus at `packages/kicad-fixtures/fixtures/**`.
- Produces: pull-request and main-push triggers for the live KiCad workflow when shared fixture inputs change.

- [x] **Step 1: Add a failing workflow-contract test**

Require `packages/kicad-fixtures/fixtures/**` to appear in both the pull-request and push path-filter lists. The test must fail on the pre-fix workflow with a count of 0.

- [x] **Step 2: Add the shared corpus path to both filters**

Keep the existing `tests/fixtures/**` filters and add `packages/kicad-fixtures/fixtures/**` alongside them.

- [ ] **Step 3: Verify workflow syntax, policy, and the focused tests**

Run the workflow contract tests, actionlint, repository workflow policy, and workflow security checks before publishing the updated PR head.
