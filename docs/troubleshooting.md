# Troubleshooting

## KiCad CLI Not Found

Set `KICAD_MCP_KICAD_CLI` to the absolute path of `kicad-cli`.

Common paths:

- Windows: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`
- macOS: `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`
- Linux: `/usr/bin/kicad-cli`

Run:

```bash
kicad-cli --version
```

## IPC Connection Fails

Open KiCad and enable the IPC API server:

`KiCad -> Preferences -> Scripting -> Enable IPC API Server`

If you use a custom socket or token, set:

```bash
KICAD_MCP_KICAD_SOCKET_PATH=/path/to/socket
KICAD_MCP_KICAD_TOKEN=token
```

## Project Files Are Not Detected

Set the project directory explicitly:

```bash
KICAD_MCP_PROJECT_DIR=/absolute/path/to/project
```

The directory should contain a `.kicad_pro` file and usually matching `.kicad_sch` and `.kicad_pcb` files.

When a directory contains both `<directory>.kicad_pro` and sync-conflict duplicates such as `<directory> 2.kicad_pro`, the server prefers the canonical basename match and ignores numbered duplicates during automatic discovery. `kicad_set_project()` echoes the resolved project file in its response.

## KiCad Reports Busy

Some KiCad IPC and CLI operations can fail while the GUI is modal, saving, or actively editing. The server retries transient busy responses, then returns an actionable message if KiCad still cannot respond. Close modal dialogs, finish the current drag/edit operation, save the file, and retry the tool.

## Flat Multi-Sheet Projects

Imported Eagle projects often contain several top-level `.kicad_sch` files without hierarchical sheet links. `export_bom()` and `validate_footprints_vs_schematic()` consolidate non-duplicate schematic siblings in the project directory so they do not compare only the active sheet against the whole PCB.

## Live LCSC/JLCPCB Lookups

`lib_get_bom_with_pricing()` resolves only explicit LCSC fields. It does not infer purchasable parts from a generic value such as `10k` or `20kB`, because value-only matches can return the wrong category. Add an `LCSC` or `LCSC Part` property before using pricing output for manufacturing review.

## Windows Path Issues

Use absolute paths and avoid relying on client-side expansion such as `${workspaceFolder}` unless your MCP client documents support for it.

## Manufacturing Export Is Blocked

`export_manufacturing_package()` is intentionally gated. Run:

```text
project_quality_gate_report()
```

Then resolve the blocking gate and rerun the export. The project fix queue resource also lists the next suggested action.

## HTTP Transport Does Not Connect

Check `KICAD_MCP_HOST`, `KICAD_MCP_PORT`, `KICAD_MCP_AUTH_TOKEN`, `KICAD_MCP_HTTP_BOUNDARY`, `KICAD_MCP_PUBLIC_BASE_URL`, and `KICAD_MCP_CORS_ORIGINS`. Non-loopback binds fail closed unless the boundary is direct TLS, `loopback-proxy`, or `tls-proxy`. For local-only Studio bridge deployments, port `27185` is a good convention; the default server port is `3334`.
