# Explicit first schematic execution, one attempt ID at a time

The reviewed `scripts/run_reference_board_agent.py` provides the actual Claude
phase session. For the **first schematic phase only**, use this fail-closed
operator entry point to connect the already-reviewed preflight to the executor:

```sh
# Non-executing preview. Never reserves an ID or starts a provider session.
uv run --all-extras --frozen python scripts/start_reviewed_reference_attempt.py \
  --board-id esp32-c6-usbc --attempt-number 4

# Only on a trusted machine after reviewing the provider account, token limits,
# project, expected expenses, and a clean preflight result:
uv run --all-extras --frozen python scripts/start_reviewed_reference_attempt.py \
  --board-id esp32-c6-usbc --attempt-number 4 \
  --execute --acknowledge-provider-cost
```

The executing invocation reserves the attempt's private `.dev-tools` directory
**exclusively before** the provider is called and creates a `started` receipt
containing the exact source commit and reviewed input hashes. After the phase,
its sanitized receipt records whether the reviewed runner exited normally and
produced a structurally valid agent event log. A failure or interruption leaves
an auditable private reservation; **no retry with the same attempt ID** is
attempted. The operator must review that state before advancing, publishing an
attempt manifest, or using a different ID. This wrapper never writes an
`attempt.json`, changes a benchmark denominator, certifies ERC/DRC, or
approves manufacturing. A completed *schematic phase* does not mean a PCB task
succeeded.

The wrapper intentionally does **not** chain PCB and manufacturing phases;
the existing reviewed phase-specific runner and independent approvals remain
required. It makes no automatic paid provider calls in CI. A syntactically
valid receipt is not proof of authentic real-host execution; fixtures in tests
are mocks, and native provider/test credentials must remain out of artifacts.
