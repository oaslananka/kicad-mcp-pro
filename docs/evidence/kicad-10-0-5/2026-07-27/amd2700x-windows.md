# KiCad 10.0.5 Physical Windows Evidence

- Generated: `2026-07-26T23:59:13Z`
- Source release: `mcp-server-v3.29.0`
- Source commit: `6d1242efbf484dce26675412bf283c009564e557`
- Host: physical `AMD2700X` workstation
- CPU: AMD Ryzen 7 2700X Eight-Core Processor
- OS: Microsoft Windows 11 Pro `10.0.26200`, 64-bit
- Interactive desktop session: active console session `1`
- KiCad desktop and CLI: `10.0.5`
- KiCad IPC API version: `10.0.1`
- Python: `3.13.12`
- `kicad-python`: `0.7.1`
- `pynng`: `0.9.0`

## Stable Canary

The released 3.29.0 source was checked out on the physical Windows host and the
stable canary was run against the installed final KiCad 10.0.5 CLI.

Result: **PASS**

- Canary plan entries: 31
- Successful entries: 31
- Failing fixtures: none
- Generated artifact bytes: 1,063,722
- Summary SHA-256: `09ff8254905634c7a4ebeed5bf35cd87d65eccc3bb6f7eaa9552393a6efd9005`
- Expected optional skips:
  - `allegro-import-capability`: KiCad 10.0.5 did not advertise the optional
    Allegro importer token.
  - `read-only-output-failure`: directory permission semantics remain covered by
    the Linux canary lane.

Command:

```powershell
$env:KICAD_CANARY_KICAD_CLI = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
C:\srv\tools\uv-0.10.8\Scripts\uv.exe run --no-project --with pyyaml `
  python scripts\kicad_canary.py run `
  --artifacts C:\srv\evidence\kicad-mcp-pro\3.29.0\amd2700x-2026-07-27 `
  --kicad-range 10.0.x
```

## GUI and IPC Session

KiCad PCB Editor was launched in the active interactive Windows session with
`clean-led-kicad10.kicad_pcb` open. The product's default IPC discovery was then
probed without a socket or token override.

Result: **PASS**

- Endpoint source: `default`
- IPC reachable: `true`
- Reported KiCad version: `10.0.5`
- Live PCB context: `true`
- Live PCB reads and writes: available
- Available live PCB tools:
  - `pcb_add_zone`
  - `pcb_delete_object`
  - `pcb_move_component`
  - `pcb_place_component`
  - `pcb_route_trace`
  - `pcb_set_design_rules`
- IPC evidence SHA-256: `3ab9bbdf6a9650c377ad9309cf0c4d42db0454bec29eff0d0deef02db9995a5c`

The official `kicad-mcp-pro doctor --json` command also reported:

- `kicad_cli`: `ok`
- `kicad_cli_version`: `10.0.5`
- `kicad_ipc`: `ok` — KiCad IPC is reachable and a board is open.
- Capability mode: `gui-connected`

A redacted diagnostic bundle was generated on the host:

- Bundle bytes: 5,247
- Bundle SHA-256: `403a9e9e5fb54c942d0bf735d280370e987bf7cb93769403a1bcd3ba8896746c`

Development-tool version warnings from the host-global PATH were not runtime
failures. The canary used the repository-compatible uv 0.10.8 environment, and
both the released CLI surface and live KiCad IPC checks passed.
