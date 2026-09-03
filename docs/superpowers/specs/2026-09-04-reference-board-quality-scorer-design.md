# Reference-board quality scorer design

## Purpose

Issue #730 requires automated board-specific scoring in addition to the existing `pcb-task-outcome.v1` aggregate KPIs. The scorer must objectively verify each published reference-board attempt without introducing a second outcome taxonomy or relying on screenshots.

The existing `AttemptRecord`, reference-bundle validator, schematic IR parser, and PCB file inspection code remain authoritative. The scorer adds a small, deterministic quality-rule layer and one sanitized machine-readable report per attempt.

## Approaches considered

1. **Data-driven quality contract (selected).** Add a versioned `quality-gates.json` beside each board benchmark and evaluate it with shared code. This keeps board expectations reviewable and avoids hard-coded Python logic per board.
2. Hard-code one Python scorer per board. This is strongly typed but makes benchmark changes code changes and encourages copy/paste drift.
3. Extend `benchmark.json` with board-specific rules. Rejected because it would overload the canonical task-outcome schema with product-specific electrical/layout details.

## Contract boundary

Each board revision adds `quality-gates.json` with schema id `pcb-reference-board-quality.v1`. It binds to `board_id` and `benchmark_version` and contains only deterministic required rules. Unknown rule types or fields fail closed.
Supported initial rule types are deliberately small:

- `schematic_component`: require a reference plus reviewed identity constraints such as exact/allowed library id, value, and footprint.
- `schematic_net`: require a named net and optional required component references on that net.
- `pcb_footprint`: require a reference and reviewed footprint identity.
- `pcb_net`: require a named PCB net and optional required footprint references attached to it.
- `board_outline`: require a real `Edge.Cuts` outline and optional bounded dimensions.
- `attempt_validation`: require an existing canonical ERC/DRC validation record to be attempted, completed, consumed, and pass according to the benchmark contract.
- `artifact`: require a named publication artifact to be a regular non-empty file or a non-empty directory.

No arbitrary code, shell command, user-supplied regex execution, provider text parsing, or screenshot similarity is part of the rule language.

## Data flow

`score_reference_board_attempt(bundle_root, attempt_id)` loads the existing benchmark, quality contract, and `AttemptRecord`. It verifies board/version identity first. A schematic adapter calls the existing semantic `parse_schematic()` path. A PCB adapter reuses the established board-file parser by exposing only the existing footprint/net/outline facts needed by eval code; it does not create a second KiCad parser.

Each rule produces a stable id, `pass`/`fail`, and a bounded reason code. Raw schematic/PCB text, absolute private paths, provider messages, and tool outputs never enter the report.

The CLI writes `board-quality-score.json`. The report contains schema version, board/benchmark/attempt ids, source revision, required-rule counts, `quality_score_percent`, overall pass state, and ordered rule results. Overall pass requires every required rule to pass; the percentage is descriptive and cannot turn a failed required rule into success.
## Failure and publication semantics

The scorer never rewrites `AttemptRecord.classification`. A provider/tool failure remains a failed attempt even if no design files exist. Missing design evidence therefore yields a failed quality report when scoring is requested; it is not silently excluded.

For a claimed autonomous success, the reference-bundle validator will require the quality report to exist, match the attempt identity, and report overall pass. Manual repair remains governed by the existing attempt contract and cannot be converted to autonomous success by the scorer.

`board-quality-score.json` is included in the attempt evidence digest and manifest denominator once real runs begin. Regeneration after publication changes the digest and therefore fails stale evidence validation until the manifest is deliberately rebuilt.

## Board-specific v1 rules

The first three contracts will encode only requirements already present in their written specifications. ESP32-C6 covers the module, USB-C/power/protection path, named USB nets, PCB footprint transfer, outline, ERC/DRC, BOM and manufacturing artifacts. STM32F072 additionally checks SWD, RS-485 and I2C identities/nets. RP2350 additionally checks RP2350, external flash, USB/debug and expansion requirements.

The rule files must not invent sign-off-grade SI/PI/EMC claims. Layout checks are limited to facts the maintained parser and validation stack can objectively prove.

## Testing

TDD fixtures will cover strict schema parsing, unknown-rule rejection, schematic component/net pass and fail cases, PCB footprint/net/outline checks, validation/artifact checks, deterministic ordering/scoring, sanitized output, identity mismatch, missing evidence, and CLI exit codes.

Integration tests will score synthetic KiCad fixtures through the same parser paths. The three real board `quality-gates.json` files will be schema-validated before any real agent attempt starts. Existing reference-corpus and task-outcome suites remain unchanged and must stay green.

## Scope exclusions

This change does not run the agent, create PCB designs, change model/provider policy, add new electrical solvers, or alter the canonical KPI taxonomy. Real attempts begin only after both the harness and scorer contracts are reviewed and merged.
