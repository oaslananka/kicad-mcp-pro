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

## Windows Path Issues

Use absolute paths and avoid relying on client-side expansion such as `${workspaceFolder}` unless your MCP client documents support for it.

## Manufacturing Export Is Blocked

`export_manufacturing_package()` is intentionally gated. Run:

```text
project_quality_gate_report()
```

Then resolve the blocking gate and rerun the export. The project fix queue resource also lists the next suggested action.

## HTTP Transport Does Not Connect

Check `KICAD_MCP_HOST`, `KICAD_MCP_PORT`, `KICAD_MCP_AUTH_TOKEN`, and `KICAD_MCP_CORS_ORIGINS`. For local-only Studio bridge deployments, port `27185` is a good convention; the default server port is `3334`.
