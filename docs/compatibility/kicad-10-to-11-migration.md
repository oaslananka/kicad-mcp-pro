# KiCad 10 to 11 Migration

This guide keeps KiCad Studio and KiCad MCP Pro ready for the KiCad 11 line
without changing the current supported baseline. KiCad 10.0.x remains the
primary release-blocking target until a KiCad 11 stable or release-candidate
canary has passed and the support matrix is updated in `compatibility.yaml`.

## Compatibility Boundary

| Surface                        | KiCad 10.0.x              | KiCad 11 readiness                          |
| ------------------------------ | ------------------------- | ------------------------------------------- |
| Primary support                | Required release gate     | Not primary yet                             |
| Direct `pcbnew` / SWIG imports | Forbidden in production   | Forbidden in production                     |
| Project discovery              | MCP and file-backed paths | Must remain IPC or CLI backed               |
| Schematic and PCB reads        | MCP tests plus CLI canary | Same tool contracts, no SWIG fallback       |
| DRC and ERC                    | `kicad-cli` contract      | Same command contract against nightly or RC |
| Manufacturing exports          | `kicad-cli` contract      | Same command contract against nightly or RC |

The executable contract lives in `compatibility.yaml` under
`kicadIpcReadiness`. It records the direct `pcbnew` import policy, the minimal
allowlist, the manual nightly/RC canary commands, and the IPC feature-parity
matrix that maps user-facing MCP tools to tests and canary probes.

The generated [KiCad adapter matrix](kicad-adapter-matrix.generated.md) maps every routed tool
category to its KiCad 10 GUI IPC, KiCad 11 headless IPC, CLI, guarded file, or external-engine
adapter. Runtime selection is observable through `kicad_get_server_info` and fails closed when a
declared runtime is unavailable. The governing decision is
[ADR-0007](../adr/0007-kicad-adapter-selection-and-swig-retirement.md).

## Direct `pcbnew` Policy

Production code must not import or call the legacy SWIG Python `pcbnew` module.
The only repository allowlist entries are:

- `scripts/check_no_pcbnew.py`, because it names the
  forbidden API while enforcing the guard.
- `tests/**`, because tests may construct examples that
  prove the guard fails.

Run the guard locally:

```bash
uv run --all-extras python scripts/check_no_pcbnew.py
```

```powershell
uv run --all-extras python scripts/check_no_pcbnew.py
```

## Manual KiCad 11 Smoke Path

KiCad nightly builds use the development branch version before a release
candidate and switch to the next major version during the RC window. As of
2026-05-26, KiCad 10.0.x is the stable line, so the next-major readiness smoke
has two manual paths:

```bash
KICAD_CANARY_KICAD_CLI=/absolute/path/to/kicad-cli \
  corepack pnpm run test:kicad-cli-contract:nightly
```

```powershell
$Env:KICAD_CANARY_KICAD_CLI = "C:\Program Files\KiCad Nightly\bin\kicad-cli.exe"
corepack pnpm run test:kicad-cli-contract:nightly
```

Use the RC command once the installed prerelease reports `11.0.x`:

```bash
KICAD_CANARY_KICAD_CLI=/absolute/path/to/kicad-cli \
  corepack pnpm run test:kicad-cli-contract:future
```

```powershell
$Env:KICAD_CANARY_KICAD_CLI = "C:\Program Files\KiCad\11.0\bin\kicad-cli.exe"
corepack pnpm run test:kicad-cli-contract:future
```

The CLI canary writes logs, reports, manufacturing outputs, `summary.json`, and
`failing-fixtures.txt` under `artifacts/kicad-cli-contract/`. The scheduled preview workflow also
publishes independent `read`, `write`, and `export` reports under `artifacts/kicad-11-preview/`.
A blocked report is retained when the nightly package or compatible headless SDK surface is not yet
available; it must not be interpreted as KiCad 11 support.

For runtime routing, `KICAD_MCP_HEADLESS=1` is an explicit assertion that the configured IPC
endpoint belongs to `kicad-cli api-server`. It does not launch KiCad. Leave it disabled for GUI
sessions; KiCad 11 plus a reachable socket is not, by itself, evidence of headless operation.
As of July 22, 2026, stable `kicad-python` 0.7.1 still documents connection to a running KiCad
session, while automatic headless launch remains on the development branch.

## IPC Feature-Parity Matrix

| Area              | Representative tools                                                                            | Required probes and tests                                                  |
| ----------------- | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Project discovery | `kicad_get_project_info`, `kicad_set_project`                                                   | Version, paths-with-spaces, Unicode paths, project-library tests           |
| PCB read          | `pcb_get_board_summary`, `pcb_get_tracks`, `pcb_get_footprints`, `pcb_get_nets`                 | Board statistics probes, PCB integration tests, GUI smoke                  |
| Schematic read    | `sch_get_symbols`, `sch_get_sheet_info`, `sch_get_net_names`                                    | ERC, schematic PDF, BOM, netlist, schematic integration tests              |
| DRC               | `run_drc`, `validate_design`, `check_design_for_manufacture`                                    | Clean, dirty, and KiCad 10.0.4 status/elapsed report probes                |
| ERC               | `run_erc`, `validate_design`, `schematic_quality_gate`                                          | Clean, dirty, and KiCad 10.0.4 sheet-shape probes                          |
| Export            | `export_gerber`, `export_drill`, `export_manufacturing_package`, `export_bom`, `export_netlist` | PDF, property-popup suppression, SVG, DXF, Gerber, drill, STEP probes      |
| Diagnostics       | `kicad_get_version`, `kicad_get_server_info`, `kicad_help`                                      | Version and read-only-output probes, server-info and CLI diagnostics tests |

The repository gate checks that every listed tool exists in the generated MCP
tool reference and that every evidence path exists:

```bash
corepack pnpm run compat:check
```

```powershell
corepack pnpm run compat:check
```

## Promotion Checklist

- Update `compatibility.yaml` only after the KiCad 11 RC or stable canary passes.
- Keep KiCad 10.0.x primary support unchanged until the support matrix and
  product changelogs intentionally move the primary line.
- Update [`../status/runtime-policy-matrix.md`](../status/runtime-policy-matrix.md) and
  [`../development/contributing.md`](../development/contributing.md) with the new line state.
- Attach the canary artifact summary to the tracking issue or PR.
- Keep production code on IPC, `kicad-cli`, or file-backed adapters.

## Source Verification

Checked on 2026-07-22:

- [KiCad PCB Python bindings](https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/)
  for the SWIG `pcbnew` deprecation and KiCad 11 removal plan.
- [KiCad API Python bindings](https://gitlab.com/kicad/code/kicad-python) and the
  [stable package](https://pypi.org/project/kicad-python/) for the current headless-launch boundary.
- [KiCad command-line interface](https://docs.kicad.org/master/en/cli/cli.html)
  for the `api-server`, DRC, ERC, and export command surfaces.
- [KiCad nightly builds and release candidates](https://www.kicad.org/help/nightlies-and-rcs/)
  for nightly/RC version behavior and data-safety guidance.
