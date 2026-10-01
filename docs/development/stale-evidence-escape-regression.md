# Stale-evidence escape regression corpus

This #942 criterion-8 corpus exercises the production evidence-freshness and release-evidence policy path against a maintained USB reference fixture.

## What is measured

Each case starts from the same seeded Engineering Graph:

- `USB_DP` net;
- `PCB_STACKUP` constraint;
- unrelated `U8` component;
- release-blocking `INTENT-USB-SI` contract; and
- exact-hash USB impedance evidence.

The evaluator applies a bounded mutation or uncertainty condition, calls the production `assess_evidence_freshness()` implementation, then passes those assessments to the production `evaluate_release_evidence()` gate.

A **stale-evidence escape** occurs when a corpus case marked `must_block` is nevertheless release-approved. The maintained target is exactly **0 escapes / 0.0 rate**.

The corpus also carries two positive controls:

- an unrelated U8 edit must preserve the USB proof as `still_valid`; and
- an explicit reviewed waiver is allowed only while its own exact-revision evidence remains `still_valid`.

A stale waiver is a must-block case.

## Maintained artifacts

- Corpus: `evals/evidence_freshness/stale_escape_cases.json`
- Evaluator: `src/kicad_mcp/evals/stale_evidence_escape.py`
- Generator/checker: `scripts/stale_evidence_escape_report.py`
- Machine-readable report: `docs/evidence/stale-evidence-escape-report.json`
- Regression tests: `tests/unit/test_stale_evidence_escape.py`

Regenerate the report with:

```bash
uv run python scripts/stale_evidence_escape_report.py
```

Verify that the committed report is current and the zero-escape target still holds with:

```bash
uv run python scripts/stale_evidence_escape_report.py --check
```

The unit test suite also regenerates the report in memory and requires exact equality with the committed JSON, so corpus/report drift fails CI.

The checker intentionally does **not** accept arbitrary corpus or output paths. Both maintained artifact paths are fixed by the repository so agent/LLM-supplied CLI arguments cannot redirect reads or writes outside the criterion-8 corpus/report boundary.

## Current v1 coverage

The v1 corpus includes 12 cases, including 10 must-block stale or unresolved release-proof cases:

- unrelated component edit (positive control);
- relevant USB geometry change;
- stackup change;
- release-blocking contract entity change;
- exact input-hash mismatch;
- unknown mutation scope;
- missing current input hash;
- missing freshness assessment at the release gate;
- dependency-edge deletion;
- tampered persisted evidence payload;
- fresh explicit reviewed waiver (positive exception); and
- stale explicit waiver.

The committed report is deterministic: it contains no wall-clock timestamp. It records the canonical corpus SHA-256, per-case expected/actual freshness and release state, release reason codes, aggregate stale-case count, escape count/rate, and target status.

## Boundary

This corpus does not replace native KiCad, solver, or measurement authority. It measures whether already-recorded release-blocking evidence can incorrectly escape the dependency-aware freshness and release-policy gate. It does not invent current native hashes, authenticate waiver actors, or model the separate #943 native differential-canary work.
