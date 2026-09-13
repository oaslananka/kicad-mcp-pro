# Reference Gerber Matcher Maintainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the two Sonar S8786 Gerber/drill `Created by` regex findings with behavior-preserving bounded byte matchers.

**Architecture:** Keep timestamp normalization orchestration unchanged. Replace only the Gerber and drill `Created by` whole-line regex predicates with deterministic byte helpers, while preserving fail-closed behavior for malformed lines and leaving drill/GBRJOB paths untouched.

**Tech Stack:** Python 3.13, pytest, Ruff, SonarQube Cloud.

**Spec:** `docs/superpowers/specs/2026-09-13-reference-gerber-matcher-maintainability-design.md`

## Global Constraints

- No public/MCP tool-surface change.
- No normalization rules-version change.
- No suppression of Sonar findings.
- Preserve non-matching bytes exactly.

---

### Task 1: Replace risky Gerber/drill created-by regex predicates

**Files:**
- Modify: `src/kicad_mcp/evals/reference_mcp_server.py`
- Modify: `tests/unit/test_reference_mcp_server.py`
- Modify: `tests/unit/test_reference_mcp_server_maintainability.py`

**Interfaces:**
- Consumes: `_normalize_kicad_generated_line(body: bytes, *, is_kicad_gerber: bool, is_kicad_drill: bool) -> bytes`
- Produces: bounded private Gerber/drill created-by line predicates used only by reference manufacturing timestamp normalization.

- [x] **Step 1: Write behavior characterization tests** for valid Gerber/drill created-by lines and malformed near-misses containing wrong suffixes, missing delimiters, or embedded CR/LF; assert malformed inputs are returned byte-for-byte unchanged.

- [x] **Step 2: Write the maintainability RED guard** in `test_reference_mcp_server_maintainability.py` asserting `_GERBER_CREATED_BY_RE` and `_DRILL_CREATED_BY_RE` are absent from production assignments.

- [x] **Step 3: Run focused tests and verify RED**. Existing behavior tests should pass; the maintainability guard must fail because the risky regex constants still exist.

- [x] **Step 4: Implement minimal bounded matchers** with byte prefix/suffix/delimiter/newline checks and replace only the two Gerber regex calls.

- [x] **Step 5: Run focused GREEN verification**: `pytest tests/unit/test_reference_mcp_server.py tests/unit/test_reference_mcp_server_maintainability.py -q`, Ruff, C901, and `git diff --check`.

- [x] **Step 6: Run broader reference-board regression suite** covering agent runner, corpus, quality scoring, task outcomes, and reference manufacturing.

- [ ] **Step 7: Run repo pre-push gate on the committed diff**, publish the exact tested tree to a feature branch, open a PR, and require exact-head Required PR Gate, CodeQL/security, Codecov, and Sonar Quality Gate with 0 new issues before merge.
