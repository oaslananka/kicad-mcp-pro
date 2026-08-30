# Issue 730 Reference Corpus Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict publication validator for #730 reference-board bundles that enforces complete attempt accounting, sanitized ordered event history, and successful-artifact completeness without a second KPI schema.

**Architecture:** Build a small filesystem publication layer on top of existing `BenchmarkContract`, `AttemptRecord`, sanitization, and `aggregate_task_outcomes`. Cross-check manifest/filesystem/attempt identity, then expose the same validator through a thin CLI and maintained development documentation.

**Tech Stack:** Python 3.13, Pydantic v2, standard-library pathlib/json/datetime, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-issue-730-reference-corpus-contract-design.md`

## Global Constraints

- Reuse `pcb-task-outcome.v1`; no parallel attempt/KPI scoring model.
- Do not claim #730's real-board acceptance is complete in this tranche.
- Keep provider failures in the valid denominator and existing reviewed `infrastructure_invalid` semantics unchanged.
- Reject publishable `classification=success` with `manual_repair=true`.
- Require filesystem-to-manifest attempt equality; reject unsafe paths and symlinked evidence.
- Use existing sanitization; persist no raw provider content, credentials, environment dumps, or private paths.
- Add no dependency and weaken no test, coverage, security, or CI gate.

---

### Task 1: Reference manifest and agent-log contract

**Files:**
- Create: `src/kicad_mcp/evals/reference_corpus.py`
- Modify: `src/kicad_mcp/evals/__init__.py`
- Test: `tests/unit/test_reference_corpus.py`

**Interfaces:**
- Consumes: existing benchmark/attempt parsers, scorer, sanitization guard.
- Produces: `ReferenceCorpusError`, manifest/log models, `ValidatedReferenceBoardBundle`, `compute_reference_inputs_digest(root: Path)`, `compute_attempt_evidence_digest(attempt_dir: Path)`, and `validate_reference_board_bundle(root: Path)`.

- [ ] **Step 1: Write RED tests** for traversal paths, duplicate entries, malformed JSONL, non-contiguous sequences, decreasing timestamps, nested details, and unsafe values.
- [ ] **Step 2: Verify RED** with `.venv/bin/pytest tests/unit/test_reference_corpus.py -q`.
- [ ] **Step 3: Implement minimal strict models/parser** using frozen extra-forbid Pydantic models, timezone-aware timestamps, scalar-only details, and shared sanitization.
- [ ] **Step 4: Verify the contract tests GREEN** with the same focused command.

### Task 2: Filesystem anti-cherry-pick and artifact validation

**Files:**
- Modify: `src/kicad_mcp/evals/reference_corpus.py`
- Modify: `tests/unit/test_reference_corpus.py`

**Interfaces:**
- Consumes: Task 1 models plus existing task-outcome parser/scorer.
- Produces: complete `validate_reference_board_bundle` behavior.

- [ ] **Step 1: Add RED tests** for valid bundle, unindexed/missing attempt directory, identity mismatch, required ERC/DRC evidence, success+manual repair, missing final artifact, empty Gerbers, and symlinked evidence.
- [ ] **Step 2: Verify new tests RED**.
- [ ] **Step 3: Implement minimal filesystem validation**: parse contract/attempts, require manifest/filesystem equality, reject symlinks, enforce required validation records/final artifacts, aggregate the entire attempt set.
- [ ] **Step 4: Verify GREEN** with `.venv/bin/pytest tests/unit/test_reference_corpus.py tests/unit/test_task_outcomes.py tests/unit/test_generate_task_outcome_report.py tests/unit/test_task_outcome_scoring_integrity.py -q`.

### Task 3: Validator CLI and maintained documentation

**Files:**
- Create: `scripts/validate_reference_board_bundle.py`
- Modify: `tests/unit/test_reference_corpus.py`
- Create: `docs/development/reference-board-corpus.md`
- Modify: `mkdocs.yml`

**Interfaces:**
- Consumes: `validate_reference_board_bundle`.
- Produces: `python scripts/validate_reference_board_bundle.py --bundle <path>`.

- [ ] **Step 1: Add RED CLI tests** for stable success output and bounded invalid-bundle failure.
- [ ] **Step 2: Implement thin CLI** without printing raw evidence.
- [ ] **Step 3: Document layout, denominator, failure/infra-invalid handling, successful artifacts, log constraints, validator command, and remaining #730 physical work.
- [ ] **Step 4: Run focused tests GREEN**.

### Task 4: Verification and reviewer pass

**Files:** Review all changed files only.

- [ ] **Step 1: Run related tests:** `.venv/bin/pytest tests/unit/test_reference_corpus.py tests/unit/test_task_outcomes.py tests/unit/test_generate_task_outcome_report.py tests/unit/test_task_outcome_scoring_integrity.py tests/unit/test_corpus_eval.py -q`.
- [ ] **Step 2: Run Ruff check/format, `py_compile`, and `git diff --check`** on changed Python files.
- [ ] **Step 3: Run maintained docs/workflow validation commands** available in the current tree and record exact results.
- [ ] **Step 4: Review full diff** for debug/generated artifacts, private paths/secrets, dependency changes, unrelated refactors, weakened assertions, and false #730 completion claims.
- [ ] **Step 5: Push single-purpose PR**, require terminal CI/CodeQL/dependency/security/Sonar/Codecov/Mergify/ruleset evidence, merge only when clean, then verify exact merge-SHA post-merge CI.
