# KiCad 10.0.7 — Linux native CLI qualification evidence

Issue: [#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).
Source checkout: `c93559e47fc9dba2e0bdc11f64467f1ad1d0d6c1`.
Recorded on 2026-10-10; OS/architecture: Linux x86_64. This folder records
the **CLI/fixture scope only**, not a Windows/GUI/IPC or autonomous real-board
qualification.

The paired machine-readable evidence file
[`2026-10-10-linux-native-canary.json`](2026-10-10-linux-native-canary.json)
preserves all 32 native canary step identities, expected-negative results and
return codes, skip state, output inventory, and five semantic differential
results for both versions. Native and custom hashes are included for every
differential. Machine-specific output paths and free-form command logs are
intentionally excluded; the underlying canary produces full local diagnostics
for independent reruns.

| Measured gate | 10.0.6 | 10.0.7 |
| --- | ---: | ---: |
| Canary steps with `ok=true` | 32/32 | 32/32 |
| Explicit skips | 1 | 1 |
| Failing fixture identities | 0 | 0 |
| Native/custom differential matches | 5/5 | 5/5 |
| False PASS, false FAIL, divergence | 0 | 0 |

The one explicit skip is the known unsupported Allegro CLI import. A canary
step with `ok=true` means that its expected semantics held; a negative test
can pass while its native process deliberately returns a nonzero status. The
DRC differential comparison uses *finding type/bucket/severity* rather than
human-readable short-net descriptions, which changed to `<no net>` in a
previous fixture comparison. Neither version passes clean-board electrical
design claims just because their native DRC failure buckets agree.

## Reproduce

Use this exact source revision, the project's locked uv 0.12.19 and Python
3.13.12 environment, and the official KiCad stable 10.0.7 Linux lite AppImage
archive listed with its SHA-256 in the JSON report. Independently verify
the downloaded archive/AppImage digests and extract the AppImage to an isolated
temporary location; do not overwrite the host KiCad installation.

For each version run the same native suite, selecting the appropriate
`kicad-cli` via `KICAD_CANARY_KICAD_CLI`:

```sh
uv sync --all-extras --frozen
KICAD_CANARY_KICAD_CLI=/path/to/version-specific/kicad-cli \
  uv run --all-extras python scripts/kicad_canary.py run \
  --artifacts artifacts/kicad-native-version \
  --kicad-range 10.0.x
```

Check `summary.json`, `failing-fixtures.txt` and
`differential/summary.json` in each run directory before comparing the
documented measurements.

The matched SHA-256 values are **download/integrity comparison evidence**,
not a verified upstream signature; no independent minisign verification
was performed. Windows stable package/CLI, GUI/IPC capability, cross-platform
native regressions and complete agent-authored reference-board outcomes
remain unqualified. **Do not** promote `compatibility.yaml`'s
`kicad.latestVerified: 10.0.6` from this Linux canary alone.
