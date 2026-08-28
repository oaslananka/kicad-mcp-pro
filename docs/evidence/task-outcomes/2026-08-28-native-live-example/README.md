# Native-live task-outcome example evidence

This directory is a deterministic **schema and reporting example**, not a claim that the
product KPI targets are attained. It demonstrates that native-live PCB mutation evidence can
flow into the canonical `pcb-task-outcome.v1` contract without a parallel KPI schema.

- Source revision recorded by the example: `434d49327a6e488880eb2cdf05d58a65628083c7`
- KiCad contract: `10.0.5`
- `kicad-python` contract: `0.7.1`
- Benchmark: `native-live-transaction-example` `v1`
- Attempts committed here: `1`
- Mutations represented: `2`
- Recovery-required mutations: `1`
- Duplicate-application incidents: `0`
- State-divergence incidents after recovery: `0`
- File-corruption incidents: `0`

The benchmark sufficiency floor deliberately requires at least two valid attempts, two
recovery-required mutations, two DRC-required tasks, and two manufacturing-release tasks.
Therefore every headline target in `summary.json` / `summary.txt` is reported as
`insufficient_evidence`, even where the one example attempt has a nominal 100% rate.
Representative-corpus qualification remains tracked separately by issue #730.

Files:

- `contract.json` — versioned benchmark/task and evidence-sufficiency contract.
- `attempt.json` — one complete sanitized attempt containing canonical mutation evidence.
- `summary.json` — deterministic machine-readable aggregate.
- `summary.txt` — deterministic human-readable headline report.

Regenerate the summaries with:

```bash
uv run python scripts/generate_task_outcome_report.py \
  --contract docs/evidence/task-outcomes/2026-08-28-native-live-example/contract.json \
  --attempt docs/evidence/task-outcomes/2026-08-28-native-live-example/attempt.json \
  --json-output docs/evidence/task-outcomes/2026-08-28-native-live-example/summary.json \
  --text-output docs/evidence/task-outcomes/2026-08-28-native-live-example/summary.txt
```
