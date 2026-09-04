# Reference-board quality scorer implementation plan

## Goal

Implement issue #730 board-specific deterministic scoring without changing `pcb-task-outcome.v1` or introducing a second KiCad parser. The scorer consumes reviewed `quality-gates.json`, one existing `AttemptRecord`, and attempt artifacts; it emits sanitized `board-quality-score.json`.

## Task 1 — strict quality contract and report models

**Files**
- Create `src/kicad_mcp/evals/reference_board_quality.py`
- Create `tests/unit/test_reference_board_quality.py`

**Steps**
1. RED: parse a minimal `pcb-reference-board-quality.v1` contract and reject unknown fields/rule types.
2. GREEN: add strict Pydantic models for the seven reviewed rule types.
3. Add deterministic `BoardQualityScore` / rule-result rendering with bounded reason codes.
4. Verify output through `validate_sanitized_evidence()` and stable ordering.

## Task 2 — existing-parser fact adapters and rule evaluation

**Steps**
1. RED: synthetic schematic fixture exercises component identity and named-net membership rules.
2. GREEN: use `ir.from_kicad.parse_schematic()`; do not parse schematic text in scorer code.
3. RED: synthetic PCB fixture exercises footprint, pad-net membership, and outline bounds.
4. GREEN: reuse `_parse_board_footprint_blocks()` and `_outline_bounds_mm()` from maintained board/DFM parsing paths.
5. Add validation and artifact rules from canonical `AttemptRecord` and regular-file/directory checks.

## Task 3 — attempt scorer and CLI

**Files**
- Modify `src/kicad_mcp/evals/reference_board_quality.py`
- Create `scripts/score_reference_board_attempt.py`
- Extend `tests/unit/test_reference_board_quality.py`

**Steps**
1. RED: identity mismatch, missing attempt evidence, and failed required rule all produce overall fail.
2. GREEN: implement `score_reference_board_attempt(bundle_root, attempt_id)` with canonical path derivation only.
3. Score percentage is descriptive; `overall_pass` requires every required rule to pass.
4. CLI writes only canonical `attempts/<id>/board-quality-score.json` and returns nonzero on failed quality.

## Task 4 — publication integration and three v1 contracts

**Files**
- Modify `src/kicad_mcp/evals/reference_corpus.py`
- Modify `tests/unit/test_reference_corpus.py`
- Create `quality-gates.json` for ESP32-C6, STM32F072, and RP2350 v1 inputs.

**Steps**
1. RED: autonomous-success attempt without a matching passing quality report fails bundle validation.
2. GREEN: include quality report in attempt evidence digest/manifest validation without changing attempt classification.
3. Encode only requirements already present in each written specification; no SI/PI/EMC claims.
4. Run schema validation on all three contracts before any real attempt begins.

## Final verification

Run focused scorer/corpus/task-outcome tests, Ruff, strict mypy, architecture boundary checks, `git diff --check`, sensitive-data scan, and the three quality-contract validation tests. Open a dedicated PR against `main`; real attempts start only after it merges.
