# Reference-board Agent Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible, MCP-only Claude execution harness and three reviewed reference-board benchmark inputs for Issue #730 without publishing unverified attempt results.

**Architecture:** A pure eval module parses Claude stream-json into existing sanitized `ReferenceAgentLogEvent` records and validates benchmark session metadata. A thin CLI builds isolated Claude/KiCad MCP phase configs and runs the agent. The existing reference-corpus validator and `AttemptRecord` schema remain unchanged.

**Tech Stack:** Python 3.13, Pydantic, subprocess, Claude Code CLI, KiCad MCP stdio, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-03-reference-board-agent-runner-design.md`

## Global Constraints

- Do not retain raw Claude prompts, reasoning, tool arguments, tool results, provider text, or credentials in publication evidence.
- Only `ToolSearch` and the selected KiCad MCP profile catalog may be visible; actual KiCad execution must stay inside the phase-specific exact allowlist.
- Preserve `pcb-reference-board.v1`, `pcb-reference-agent-log.v1`, and `pcb-task-outcome.v1` as the canonical schemas.
- Every real attempt after the harness lands must remain in the denominator, including provider and tool failures.
- KiCad CLI is pinned by explicit path; PCB live-edit evidence requires verified KiCad 10 IPC.

---

### Task 1: Sanitize Claude stream evidence

**Files:**
- Create: `src/kicad_mcp/evals/reference_agent_runner.py`
- Create: `tests/unit/test_reference_agent_runner.py`

**Interfaces:**
- Produces: `ReferenceAgentRunSummary` and `parse_claude_stream(lines, attempt_id)`.
- Consumes: `ReferenceAgentLogEvent` from `reference_corpus.py`.
- [ ] **Step 1: Write the failing parser tests**

Create fixture stream records with one KiCad MCP tool call/result, one `ToolSearch`, and a successful result. Assert that only the KiCad call/result become publication events, sequence numbers are contiguous, timestamps are preserved, primary/auxiliary model identifiers are scalar metadata, and raw prompt/input/output strings are absent from rendered evidence.

- [ ] **Step 2: Run RED**

Run: `uv run --all-extras --frozen pytest -q tests/unit/test_reference_agent_runner.py`
Expected: import/function failure because the runner module does not exist.

- [ ] **Step 3: Implement minimal parser**

Implement strict JSON-line parsing, `mcp__kicad__` name normalization, tool-use-id correlation, fail-closed malformed stream handling, and a frozen summary dataclass. Ignore `ToolSearch` as internal discovery; reject any other non-KiCad executed tool. Require exactly one connected `kicad` MCP server and preserve sanitized workflow start/terminal events so parseable failed sessions remain publishable attempt evidence.

- [ ] **Step 4: Run GREEN**

Run the same pytest command; expected PASS.

### Task 2: Build isolated Claude/KiCad phase commands

**Files:**
- Modify: `src/kicad_mcp/evals/reference_agent_runner.py`
- Test: `tests/unit/test_reference_agent_runner.py`
- Create: `scripts/run_reference_board_agent.py`

**Interfaces:**
- Produces: `ReferenceAgentPhase` and `build_claude_command(...)`.
- Phase contract: schematic=`schematic_authoring/write`, pcb=`pcb_layout/write`, manufacturing=`release/manufacturing`; execution ceilings are 35/38/24 tools.
- [ ] **Step 1: Write failing command-builder tests**

Assert the command includes `-p`, `--setting-sources project`, explicit empty settings, `--strict-mcp-config`, one generated MCP config, `--tools ToolSearch`, a sorted exact `--allowedTools` phase list, `--output-format stream-json`, and `--verbose`. Assert no Bash/Read/Write/Edit/Web tools are named.

- [ ] **Step 2: Run RED**

Run the focused runner tests; expected missing phase/command builder failures.

- [ ] **Step 3: Implement command/config builder and CLI**

Generate an ephemeral MCP JSON that runs the reviewed checkout with pinned `uv`, explicit project directory, phase profile/mode, and explicit `KICAD_MCP_KICAD_CLI`. Execute Claude with `shell=False`, bounded timeout, captured UTF-8 stdout/stderr, and a caller-provided prompt file. Store raw stream only in a caller-provided scratch path outside the publication bundle.

- [ ] **Step 4: Run GREEN**

Run runner tests plus Ruff/mypy on the new module/script.

### Task 3: Publish three reviewed benchmark inputs

**Files:**
- Create: `docs/evidence/reference-boards/esp32-c6-usbc/v1/{specification.md,original-prompt.md,benchmark.json}`
- Create: `docs/evidence/reference-boards/stm32f072-usbc/v1/{specification.md,original-prompt.md,benchmark.json}`
- Create: `docs/evidence/reference-boards/rp2350-usbc/v1/{specification.md,original-prompt.md,benchmark.json}`
- Test: `tests/unit/test_reference_agent_runner.py`

Each benchmark requires all canonical task stages and at least two valid attempts, two DRC-required tasks, and two manufacturing-release tasks. Inputs must not contain pre-completed KiCad designs.
- [ ] **Step 1: Add input-contract tests**

Load each `benchmark.json` with `parse_benchmark_contract`; assert the matching spec/prompt exist, no attempt directory or final KiCad artifact is pre-populated, and all nine canonical stages are `required`.

- [ ] **Step 2: Copy reviewed inputs and run RED/GREEN as needed**

Use the already reviewed scratch drafts as source text, then validate each benchmark through the existing schema. Do not create `attempt-manifest.json` until a real attempt exists.

### Task 4: Verification and integration

- [ ] Run `ruff format --check`, `ruff check`, strict mypy, runner/reference-corpus unit tests, architecture checks, and `git diff --check`.
- [ ] Review the diff for raw provider data, absolute private paths, credentials, or hidden attempts.
- [ ] Commit harness + inputs without attempt results and open a PR against `main` referencing #730.
- [ ] After that PR lands, create a fresh evidence branch from its merge SHA and begin real attempts; every attempt after that point must be recorded whether successful or failed.
