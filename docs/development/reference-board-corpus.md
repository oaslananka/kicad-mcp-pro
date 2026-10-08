# Reference-board corpus publication contract

Issue #730 requires realistic PCB projects created from written specifications with complete
attempt accounting. This page documents the publication contract used by those future
reference-board runs. The validator described here is infrastructure for that evidence; it
does **not** by itself satisfy the requirement to publish at least three serious reference
boards.

## Canonical bundle layout

Each maintained board is published as one self-contained directory:

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

`benchmark.json` uses the existing `pcb-task-outcome.v1` benchmark contract. Each
`attempt.json` uses the existing `AttemptRecord` contract, so real-board publication does not
create a second success/failure taxonomy or KPI schema.

## Complete attempt denominator

`attempt-manifest.json` is the publication ledger for one board. Its
`pcb-reference-board.v1` records a `reference_inputs_digest` for the specification, original
prompt, and benchmark, plus canonical `attempts/<attempt-id>` directories and a
`sha256:<64 lowercase hex>` evidence digest per attempt. The validator requires exact equality between
manifest entries and direct attempt directories on disk. It then recomputes a deterministic
digest over sorted POSIX relative paths and each file SHA-256. An undisclosed failed attempt
or any post-manifest file addition, removal, or byte change therefore fails validation instead
of silently dropping out of the denominator or reusing stale residual output.

Provider and tool failures remain normal valid attempts and stay in the product-success
denominator. Only an existing `infrastructure_invalid` record that satisfies the reviewed
pre-task contract is separated from that denominator. The bundle validator cross-checks that
assertion against **both** the immutable attempt record and the sanitized agent log:
a supposedly pre-task-invalid run cannot contain `tool_call`, `tool_result`,
`validation`, or `recovery` log events; attempted mutations or validations,
completed/failed task stages, or started manufacturing-generation evidence
also prohibit exclusion. This cross-check runs even when the manifest digests have
been refreshed, so self-consistent hashes alone cannot launder an executed
but failed attempt out of the published denominator. A successful attempt with
`manual_repair=true` is not publishable as autonomous success. A record declared as `success`
must also be counted as successful by the canonical `aggregate_task_outcomes` quality gates;
failed required stages, validation, recovery/integrity, or manufacturing requirements therefore
make the publication bundle invalid instead of silently relabeling the result.

## Attempt evidence

Every attempt, including failed attempts, must contain `attempt.json` and an ordered
`agent-log.jsonl`. If ERC or DRC is required by the referenced task contract, the attempt must
carry explicit validation evidence recording whether execution was attempted, completed, and
consumed.

A successful attempt additionally requires the final schematic, board, BOM,
manufacturing report, required `ERC.txt`/`DRC.txt`, and a non-empty `Gerbers/` directory. The
validator rejects symlinked bundle, attempt, log, final-design, and manufacturing evidence so
publication cannot silently resolve to unrelated local state.

## Sanitized action history

`agent-log.jsonl` is a reconstruction log, not a raw conversation transcript. Each line is a
strict `pcb-reference-agent-log.v1` event whose `attempt_id` must match `attempt.json`, with a
contiguous sequence starting at 1, a
timezone-aware nondecreasing timestamp, a bounded event name, event/status enums, and optional
scalar-only details.

Events pass the shared evaluation-evidence sanitization guard. The specification, original
prompt, and required successful text artifacts use the same secret/private-path guard. Do not
publish raw provider responses, environment dumps, credentials, secret-bearing strings,
unrelated absolute user paths, or arbitrary nested provider/debug payloads.

## Benchmark manufacturing reproducibility boundary

Reference-board benchmarks do **not** turn autonomous evidence generation into a production
manufacturing release. The production `export_manufacturing_package()` path remains human-gated
and is not exposed to the benchmark manufacturing agent. The benchmark instead launches the
opt-in `kicad_mcp.evals.reference_mcp_server` over stdio with an exact discovery **and execution**
allowlist. Hidden production tools cannot be invoked by name through that server.

The benchmark surface exposes validation/inspection tools plus two fixed orchestration tools:
`reference_generate_manufacturing_snapshot()` and
`reference_compare_manufacturing_snapshots()`. Each generation starts from a fresh fixed output
location and produces a non-empty BOM plus Gerber and drill files through the same KiCad CLI export
services used by the product. Export failures, missing required outputs, symlinks, stale manifests,
or post-generation byte changes fail closed. Direct low-level export tools are not exposed to the
agent, so evidence cannot be written outside the two reviewed generation roots.

The comparator always preserves the SHA-256 manifest digest for each raw generation. If raw bytes
match, the result is `byte_identical`. KiCad CLI embeds wall-clock creation timestamps in otherwise
stable Gerber, drill, and Gerber-job outputs, so rule set `kicad-cli-timestamps-v1` may classify two
raw-different generations as `normalized_equivalent` only when the files identify KiCad as the
generator and all differences disappear after replacing those exact creation-time metadata fields.
BOM data and manufacturing geometry/coordinates are never normalized. Any other byte difference
remains `divergent`. Raw artifacts are never modified by comparison.

The earlier state-bound `reference-manufacturing-approval.json` contract remains a valid hardening
mechanism for human-gated production release workflows, but it is not required by this autonomous
benchmark evidence phase because #730 measures artifact generation/reproducibility rather than
production release authorization.

## Validate before publication

Run the validator from a clean checkout with the repository's pinned environment:

```bash
uv run --frozen python scripts/validate_reference_board_bundle.py \
  --bundle docs/evidence/reference-boards/<board-id>/<benchmark-version>
```

Success prints only stable public identity and attempt counters. Validation failures are
fail-closed and do not dump the agent log or provider content.

The tree digest is an integrity/freshness binding, not independent proof that an
intentionally re-hashed design was authored by the claimed agent. The returned aggregate is
generated by the existing `aggregate_task_outcomes` path. Board publication must still include
board-specific quality scoring, clean-start/source identity, reproducible manufacturing
outputs, independent reruns, and the physical/reference projects required by #730 before the
corpus can be treated as representative product evidence.
