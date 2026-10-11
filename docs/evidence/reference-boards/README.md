# Reference-board outcome readiness

Issues [#729](https://github.com/oaslananka/kicad-mcp-pro/issues/729) and
[#730](https://github.com/oaslananka/kicad-mcp-pro/issues/730) require complete,
non-cherry-picked *agent-authored* board attempts, not just specifications,
existing KiCad fixtures, or successful CLI/GUI regressions.

## Reproduce the publication evidence audit

Use the locked project Python environment, from the repository root:

```sh
uv run --all-extras --frozen python scripts/validate_reference_board_bundle.py \
  --corpus-root docs/evidence/reference-boards --format json
```

The output is deterministic JSON using schema
`reference-corpus-readiness.v1`. Each board version is represented exactly
once, with `status=validated` and its **attempt outcome counts** only after
the entire publication bundle and manifest have been verified. Incomplete
versions are reported as `status=incomplete` with a bounded reason code;
they are never dropped from the board/version inventory.

The program returns **2** when any board version is incomplete, when the
corpus is empty, or when an invalid/symlink entry is present; returns **0**
only when every board version's evidence is valid. Invalid filenames,
private paths, and exception text are not copied into the JSON output.
Legacy human-readable output remains the default when `--format` is omitted.

**Important:** a fully *validated* evidence bundle can still contain
**zero successful attempts**. This command reports evidence readiness,
not PCB design task-success rate. Do not interpret its successful exit
status as a manufacturing release verdict, or compute #729 product KPIs
from this result without the reviewed benchmark denominator and scoring
contract.

### Source-specific observation, 2026-10-11

In the checked-in reference corpus at the time of this audit:

| Benchmark | Evidence publication status | Recorded attempt outcome |
| --- | --- | --- |
| ESP32-C6 USB-C, v1 | Incomplete | No independently validated complete attempt bundle |
| RP2350 USB-C, v1 | Incomplete | No independently validated complete attempt bundle |
| STM32F072 USB-C, v1 | Validated | 3 attempts; 0 successful, 2 failed, 1 infrastructure-invalid |

Overall corpus readiness is **incomplete**: 1 valid evidence version and
2 incomplete versions. This is **not** a result of 1 successful PCB design
out of 3. It is the number of board *versions with validated evidence*, a
different denominator. The STM32 attempts remain failures/invalid
observations, not accepted manufacturing outputs. Repeat the command
against the relevant source revision for a fresh status.

The KiCad 10.0.7 native fixture canaries under
[platform evidence](../kicad-10-0-7/README.md) validate different
interfaces; they do not upgrade these uncompleted reference-board tasks.


## Reproducible phase preflight (reviewed runner, #1214)

Before **any** new reference-board attempt, run the non-mutating preflight in
an exact, clean source checkout with `kicad-cli` 10.x and the reviewed Claude
CLI available. The preflight hashes the original prompt, specification,
benchmark and board-specific gates; records the exact source SHA; refuses an
already-used attempt ID; and returns a bounded JSON report without local paths,
prompts, credentials or agent transcripts:

```sh
uv run --all-extras --frozen python scripts/check_reference_board_attempt_readiness.py \
  --board-id esp32-c6-usbc --attempt-number 4 --phase schematic
```

Exit **0** means this *specific agent phase can be attempted*; exit **2** means
one or more prerequisites are missing. Either exit code is **not a successful
PCB attempt**, a scored design, a completed ERC/DRC, or manufacturing approval.
A missing CLI should block the run, not be marked as a model failure or silently
skip that attempt from the denominator.

For the opt-in, non-retry entry point that joins the preflight to the first
schematic session, see [first schematic attempt](first-schematic-attempt.md).
It requires explicit execution and provider-cost acknowledgement; no
unattended CI jobs can launch agent sessions by default. The preflight itself creates no attempt
artifacts. The actual reviewed executor remains
`scripts/run_reference_board_agent.py`; use its explicit phase, timeout and
approval workflow. Treat `manufacturing` as separately human-authorized, not a
phase to run automatically after a preflight.

This is **preflight scaffolding**, not completion of #1214's benchmark runner:
provider-neutral attempt execution, consistent persisted per-attempt evidence,
full retry/history and score aggregation remain to be implemented and verified.
