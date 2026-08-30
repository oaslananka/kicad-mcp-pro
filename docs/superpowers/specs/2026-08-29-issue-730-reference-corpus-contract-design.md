# Issue 730 Reference Corpus Publication Contract Design

## Context

Issue #730 requires serious real-board benchmark projects with a complete attempt denominator, reproducible artifacts, sanitized action history, and explicit separation of product failures from pre-task infrastructure-invalid runs. The repository already owns the canonical end-to-end evidence model in `pcb-task-outcome.v1`; the golden corpus and live-model runner solve different problems and must not become a historical attempt ledger.

This tranche defines the durable publication boundary that later physical/reference-board runs must satisfy. It does **not** claim that the required 3-5 representative boards already exist.

## Goals

- Reuse `BenchmarkContract`, `AttemptRecord`, and `aggregate_task_outcomes` as the only KPI/attempt semantics.
- Require every on-disk attempt directory to be indexed so failed attempts cannot be silently omitted from the denominator.
- Require sanitized ordered event history sufficient to reconstruct the agent/tool/workflow sequence without raw provider content, credentials, or private paths.
- Reject stale, unsafe, symlinked, identity-mismatched, or incomplete successful bundles before publication.
- Provide one deterministic validator command suitable for a clean runner and CI.

## Non-goals

- Producing or claiming a real ESP32, STM32, RP2350, high-speed, or mixed-signal reference board in this tranche.
- Introducing a second task-outcome or KPI schema.
- Changing task-success thresholds or denominator rules.
- Hand-repairing failures or relabeling provider/infrastructure failures as success.
- Adding a runtime dependency.

## Bundle layout

```text
<board-root>/
  specification.md
  original-prompt.md
  benchmark.json
  attempt-manifest.json
  attempts/
    <attempt-id>/
      attempt.json
      agent-log.jsonl
      schematic.kicad_sch
      board.kicad_pcb
      ERC.txt
      DRC.txt
      BOM.csv
      manufacturing-report.md
      Gerbers/
```

`attempt.json` and `agent-log.jsonl` are required for every listed attempt. Failed attempts may legitimately stop before final design/manufacturing artifacts exist. Successful attempts require schematic, board, BOM, manufacturing report, and a non-empty Gerbers directory. ERC/DRC files are required when their corresponding task stages are required.

## Reference-board manifest

`attempt-manifest.json` uses strict schema `pcb-reference-board.v1` with `board_id`, `benchmark_id`, `benchmark_version`, and ordered attempt entries containing `attempt_id` plus canonical `directory` (`attempts/<attempt-id>`). IDs/directories are unique. Paths must be portable POSIX relative paths: no absolute paths, backslashes, empty components, `.` or `..`.

## Anti-cherry-pick and stale-output rules

The validator cross-checks the manifest and filesystem:

1. Direct child directories under `attempts/` must exactly equal the manifest entries.
2. Every manifest attempt directory must exist inside the bundle root.
3. Attempt directories and required publication artifacts may not be symlinks.
4. `benchmark.json` and each `attempt.json` use the existing strict parsers.
5. Attempt/benchmark/task identities must match manifest and contract.
6. The complete set is passed to `aggregate_task_outcomes`, preserving existing denominator and success semantics.
7. `classification=success` with `manual_repair=true` is rejected for publication.
8. Successful attempts require the canonical final artifact set and a non-empty regular-file Gerbers directory.
9. Required ERC/DRC task stages require corresponding `ValidationEvidence` for every valid attempt, even when execution failed or did not complete.

This makes undisclosed attempt directories and success-only publication fail closed without changing KPI behavior.

## Sanitized agent log contract

Each non-empty `agent-log.jsonl` line is strict `pcb-reference-agent-log.v1` with a positive contiguous `sequence`, timezone-aware nondecreasing `timestamp`, bounded `name`, `event_type` (`agent`, `tool_call`, `tool_result`, `workflow`, `validation`, `recovery`), `status` (`started`, `completed`, `failed`, `observed`), and optional scalar-only `details` mapping. Parsed payloads also pass the shared `validate_sanitized_evidence` guard. Raw prompts/provider responses, environment dumps, credentials, arbitrary nested blobs, and private absolute paths are outside the contract.

## Validation API and CLI

`src/kicad_mcp/evals/reference_corpus.py` owns the publication contract and exposes:

```python
compute_reference_inputs_digest(root: Path) -> str
compute_attempt_evidence_digest(attempt_dir: Path) -> str
validate_reference_board_bundle(root: Path) -> ValidatedReferenceBoardBundle
```

The frozen result carries root, manifest, benchmark contract, parsed attempts, and canonical aggregate summary. Invalid bundles raise public-safe `ReferenceCorpusError`.

`scripts/validate_reference_board_bundle.py --bundle <path>` returns non-zero on invalid evidence and prints only stable board/attempt counts on success; it never dumps agent-log/provider content.

## Documentation and verification

`docs/development/reference-board-corpus.md` documents the contract and explicitly states that this tranche does not satisfy #730 until representative physical boards and independent reruns are published. Tests cover a valid bundle; unindexed attempts; identity mismatch; missing required ERC/DRC evidence; missing successful artifacts; success with manual repair; traversal paths; symlinks; malformed/non-contiguous/unsafe logs; and CLI semantics. Existing task-outcome tests, Ruff, formatting, `py_compile`, `git diff --check`, docs/workflow policy, and normal PR CI/security/quality gates remain mandatory.
