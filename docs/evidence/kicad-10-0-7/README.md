# KiCad 10.0.7 — Linux and Windows native CLI qualification evidence

Issue: [#1181](https://github.com/oaslananka/kicad-mcp-pro/issues/1181).
Linux source checkout: `c93559e47fc9dba2e0bdc11f64467f1ad1d0d6c1`.
Windows source checkout: `f5a498c71b9cb45cc52302e5ee98da39104b5c09`.
Recorded on 2026-10-10; OS/architecture: Linux x86_64. This folder records
the **native CLI/fixture scope only** (Linux and Windows), not a GUI/IPC
or autonomous real-board qualification.

The paired Linux machine-readable evidence file
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

The Linux evidence file records **download/integrity comparison evidence**,
not independent signature verification *at that time*. A later detached
AppImage minisign verification was documented separately in issue #1181.
The Linux-only snapshot did not qualify Windows. The independent Windows
10.0.7 native CLI qualification below is a later, separately source-bound
test; neither result qualifies GUI/IPC or complete agent-authored reference
boards.

## Windows 10.0.7 — signed installer and native CLI

The separate permanent
[`2026-10-10-windows-native-canary.json`](2026-10-10-windows-native-canary.json)
records the hosted Windows 2025 runner's exact
[successful manual workflow run #38022313667](https://github.com/oaslananka/kicad-mcp-pro/actions/runs/38022313667)
from protected main at `f5a498c71b9cb45cc52302e5ee98da39104b5c09`.
This is a **different source revision** than the Linux pair above.

| Measured Windows CLI gate | Result |
| --- | --- |
| Official 10.0.7 x64 installer Authenticode | Valid — KICAD SERVICES CORPORATION |
| Isolated Windows install + native CLI version | Passed — exact 10.0.7 |
| Native canary expected step statuses | 32/32 |
| Explicit capability/platform skips | 2 |
| Failing fixture identities | 0 |
| Native/custom semantic differentials | 5/5 matched |
| False PASS / false FAIL / divergence / infrastructure invalid | 0 / 0 / 0 / 0 |
| Temporary installer/install/config cleanup | Passed |

The two documented skipped steps were the unsupported Allegro import
capability and the read-only-output negative probe on Windows. Passing
negative DRC/ERC test steps can have intentional nonzero native exit codes.
The remaining differential projections cover connectivity, geometry, clean
and deliberately failing DRC, and manufacturing export inventory.

The JSON record preserves the exact installer SHA-256, signer certificate
subject/issuer, run and artifact IDs, original report SHA-256 digests,
the 32 result identities/statuses/exit codes, and both semantic result
hashes for all five comparisons. Paths are restricted to relative artifact
outputs; free-form logs and host paths are intentionally excluded. The
GitHub run artifact retains the complete original reports for **7 days**;
this committed summary remains after that retention window expires.

To reproduce on a disposable, separate Windows runner, manually dispatch
`.github/workflows/kicad-10-0-7-windows-qualification.yml` at the exact
recorded source revision. The workflow verifies the KiCad Authenticode
signature, installs into a temporary directory, checks native exit/version,
requires the bundled `share/kicad/symbols/Device.kicad_sym` library, and
binds the same isolated CLI and symbol libraries into the locked canary
runtime. Then inspect `summary.json` and
`differential/summary.json` for all required acceptance conditions.

**Qualification boundary:** Windows 10.0.7 native **CLI** compatibility
is demonstrated by this single source-bound canary, not Windows GUI/IPC,
native-editor interoperability, physical manufacturing, or autonomous
reference-board production. The currently tested Ubuntu stable CI lane
remains on KiCad 10.0.6. Do **not** promote
`compatibility.yaml`'s `kicad.latestVerified: 10.0.6` or issue a release
based solely on this Windows CLI evidence.
