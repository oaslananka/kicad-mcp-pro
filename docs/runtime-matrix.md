# KiCad MCP Pro Runtime Compatibility Matrix

This document records which capabilities are tested against which KiCad versions,
operating systems, and execution modes.

## Support Tiers

| Tier | Meaning |
|---|---|
| Tested | Tested and passing in CI |
| Caveat | Works with known caveats |
| Best effort | Not covered in the CI matrix |
| Unsupported | Not supported |

## KiCad Version and Feature Matrix

| Capability | KiCad 9.x | KiCad 10.0.x | Notes |
|---|---|---|---|
| Project management | Tested | Tested | |
| Schematic read (IPC) | Caveat | Tested | IPC API is still evolving in KiCad. |
| Schematic write (IPC) | Best effort | Caveat | Round-trip parsing validation required. |
| PCB inspection (IPC) | Caveat | Tested | |
| PCB editing (IPC) | Best effort | Caveat | Retryable errors are environment-dependent. |
| DRC/ERC (CLI) | Tested | Tested | CLI-backed; most stable path. |
| BOM export (CLI) | Tested | Tested | Multi-sheet behavior needs explicit fixture verification. |
| Gerber export (CLI) | Tested | Tested | |
| STEP export (CLI) | Tested | Tested | |
| FreeRouting | Best effort | Best effort | External binary; Specctra flow is install-dependent. |
| ngspice simulation | Best effort | Best effort | External binary; smoke-level only. |
| KiCad 10 Design Blocks | Unsupported | Tested | New in KiCad 10. |
| KiCad 10 Time-Domain | Unsupported | Tested | New in KiCad 10. |

## Operating System Matrix

| OS | Tested | Notes |
|---|---|---|
| Ubuntu latest | Tested | Primary CI runner. |
| macOS latest | Tested | CI runner; IPC socket path differs. |
| Windows latest | Caveat | CI runner; path separators differ. |

## Execution Mode Matrix

| Mode | KiCad Required | GUI Required | Notes |
|---|---|---|---|
| stdio default | Optional | No | Most tools degrade gracefully. |
| Streamable HTTP | Optional | No | Requires the `http` extra. |
| With KiCad open (IPC) | Yes | Yes | Full edit capability. |
| CLI-only headless | Optional | No | Export and validation only. |
| Docker | No, external mount | No | KiCad must be mounted or configured externally. |

## Known Limitations

1. IPC calls fail if KiCad is open and blocked by a modal dialog. Callers should back off
   and retry retryable errors.
2. On KiCad 9.x, BOM export through IPC may reflect only the root sheet. Use `kicad-cli`
   BOM export for more reliable multi-sheet behavior.
3. FreeRouting requires the FreeRouting JAR or container path to be configured explicitly.
4. The Docker image does not include KiCad. Mount a host KiCad installation and set
   `KICAD_CLI_PATH` explicitly.
