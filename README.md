# KiCad MCP Pro Server

[![PyPI](https://img.shields.io/pypi/v/kicad-mcp-pro.svg)](https://pypi.org/project/kicad-mcp-pro/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Smithery](https://img.shields.io/badge/Smithery-ready-blue)](https://smithery.ai/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![KiCad 9+](https://img.shields.io/badge/KiCad-9%2B-success.svg)](https://www.kicad.org/download/)
[![MCP 1.6+](https://img.shields.io/badge/MCP-1.6%2B-purple.svg)](https://modelcontextprotocol.io/)

> AI-powered PCB and schematic design with KiCad. Works with Claude, Cursor, VS Code, Claude Code, and any MCP-compatible client.

Primary CI/CD and release automation runs in Azure DevOps. GitHub Actions in this repository are manual fallback workflows only.

## Features

- Project-first workflow with `kicad_set_project()`, recent project discovery, and safe path handling.
- KiCad 10.x-first runtime with best-effort 9.x support and cross-platform CLI/library discovery.
- PCB tools for board inspection, tracks, vias, footprints, text, shapes, outline editing, and zone refill.
- Schematic tools for symbols, wires, labels, buses, no-connect markers, property updates, annotation, netlist-aware auto-layout, and IPC reload.
- Library tools for symbol search, footprint search, datasheet lookup, footprint assignment, and custom symbol generation.
- Validation tools for DRC, ERC, DFM, courtyard issues, silk overlaps, and schematic-versus-PCB footprint checks.
- Export tools for Gerber, drill, BOM, PDF, netlist, STEP, render, pick-and-place, IPC-2581, SVG, and DXF.
- MCP resources for live board/project state and prompts for first-board, schematic-to-PCB, and manufacturing workflows.
- Server profiles (`full`, `minimal`, `pcb`, `schematic`, `manufacturing`) to reduce tool surface for clients.

## Quick Start

### Installation

Option 1: `uvx` (recommended)

```bash
uvx kicad-mcp-pro
```

Option 2: `pip`

```bash
pip install kicad-mcp-pro
kicad-mcp-pro
```

Option 3: `uv`

```bash
uv tool install kicad-mcp-pro
```

### VS Code Configuration

Add this to `.vscode/mcp.json`:

```json
{
  "servers": {
    "kicad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/absolute/path/to/your/kicad-project",
        "KICAD_MCP_PROFILE": "pcb"
      }
    }
  }
}
```

Note: `${workspaceFolder}` may not be expanded in some VS Code MCP setups. Use an
absolute path for `KICAD_MCP_PROJECT_DIR` to avoid startup errors.

### Codex Configuration

Add this to `~/.codex/config.toml` (or project-scoped `.codex/config.toml`):

```toml
[mcp_servers.kicad]
command = "uvx"
args = ["kicad-mcp-pro"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.kicad.env]
KICAD_MCP_PROJECT_DIR = "/absolute/path/to/your/kicad-project"
KICAD_MCP_PROFILE = "pcb"
```

### Claude Desktop Configuration

Add this to your Claude Desktop config:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "/path/to/your/project"
      }
    }
  }
}
```

### VS Code / Cline

Use `.vscode/mcp.json` with the same server shape shown above, and keep
`KICAD_MCP_PROJECT_DIR` as an absolute path.

### Cursor

Add a custom MCP server using `uvx` as the command and `kicad-mcp-pro` as the only argument. For remote-style usage, run `kicad-mcp-pro --transport http` and connect to `http://127.0.0.1:3334/mcp`.

### Claude Code

Launch the server with `uvx kicad-mcp-pro`, then attach it from your MCP config. The `minimal` profile is a good default when you mainly want read/export workflows.

### More Clients

Copy-ready configuration examples for VS Code, GitHub Copilot in VS Code, Codex,
Claude Desktop, Claude Code, Cursor, Gemini CLI, Antigravity-compatible clients, and
HTTP transports are available in [Client Configuration](docs/client-configuration.md).

## Prerequisites

- KiCad 9.0 or 10.0+ installed.
- Python 3.12+.
- For live IPC tools, KiCad must be running with the IPC API available.
- For HTTP transport, install the `http` extra: `pip install "kicad-mcp-pro[http]"`.

## Docker Limitations

- The published container image does not bundle a KiCad installation.
- `kicad-cli`-backed export and validation tools require a KiCad installation inside the
  container, typically mounted at `/usr/bin/kicad-cli`, or `KICAD_MCP_KICAD_CLI` pointed to a
  valid binary.
- Live IPC tools still require a reachable KiCad session with the IPC API enabled.

## Configuration

| Variable                              | Description                                  | Default            |
| ------------------------------------- | -------------------------------------------- | ------------------ |
| `KICAD_MCP_KICAD_CLI`                 | Path to `kicad-cli`                          | Auto-detected      |
| `KICAD_MCP_KICAD_SOCKET_PATH`         | Optional KiCad IPC socket path               | Unset              |
| `KICAD_MCP_KICAD_TOKEN`               | Optional KiCad IPC token                     | Unset              |
| `KICAD_MCP_PROJECT_DIR`               | Active project directory                     | Unset              |
| `KICAD_MCP_PROJECT_FILE`              | Explicit `.kicad_pro` file                   | Auto-detected      |
| `KICAD_MCP_PCB_FILE`                  | Explicit `.kicad_pcb` file                   | Auto-detected      |
| `KICAD_MCP_SCH_FILE`                  | Explicit `.kicad_sch` file                   | Auto-detected      |
| `KICAD_MCP_OUTPUT_DIR`                | Export output directory                      | `<project>/output` |
| `KICAD_MCP_SYMBOL_LIBRARY_DIR`        | KiCad symbol library root                    | Auto-detected      |
| `KICAD_MCP_FOOTPRINT_LIBRARY_DIR`     | KiCad footprint library root                 | Auto-detected      |
| `KICAD_MCP_TRANSPORT`                 | `stdio`, `http`, `sse`, or `streamable-http` | `stdio`            |
| `KICAD_MCP_HOST`                      | HTTP bind host                               | `127.0.0.1`        |
| `KICAD_MCP_PORT`                      | HTTP bind port                               | `3334`             |
| `KICAD_MCP_MOUNT_PATH`                | MCP HTTP mount path                          | `/mcp`             |
| `KICAD_MCP_PROFILE`                   | Tool profile                                 | `full`             |
| `KICAD_MCP_LOG_LEVEL`                 | Log level                                    | `INFO`             |
| `KICAD_MCP_LOG_FORMAT`                | `console` or `json`                          | `console`          |
| `KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS` | Enable unstable helpers                      | `false`            |
| `KICAD_MCP_IPC_CONNECTION_TIMEOUT`    | KiCad IPC timeout in seconds                 | `10.0`             |
| `KICAD_MCP_CLI_TIMEOUT`               | `kicad-cli` timeout in seconds               | `120.0`            |
| `KICAD_MCP_MAX_ITEMS_PER_RESPONSE`    | Max list items returned                      | `200`              |
| `KICAD_MCP_MAX_TEXT_RESPONSE_CHARS`   | Max text payload length                      | `50000`            |

## Tool Reference

### Project Management

- `kicad_set_project`
- `kicad_get_project_info`
- `kicad_list_recent_projects`
- `kicad_scan_directory`
- `kicad_create_new_project`
- `kicad_get_version`
- `kicad_list_tool_categories`
- `kicad_get_tools_in_category`
- `kicad_help`

### PCB

- `pcb_get_board_summary`
- `pcb_get_tracks`
- `pcb_get_vias`
- `pcb_get_footprints`
- `pcb_get_nets`
- `pcb_get_zones`
- `pcb_get_shapes`
- `pcb_get_pads`
- `pcb_get_layers`
- `pcb_get_stackup`
- `pcb_get_selection`
- `pcb_get_board_as_string`
- `pcb_get_ratsnest`
- `pcb_get_design_rules`
- `pcb_add_track`
- `pcb_add_tracks_bulk`
- `pcb_add_via`
- `pcb_add_segment`
- `pcb_add_circle`
- `pcb_add_rectangle`
- `pcb_add_text`
- `pcb_set_board_outline`
- `pcb_delete_items`
- `pcb_save`
- `pcb_refill_zones`
- `pcb_highlight_net`
- `pcb_set_net_class`
- `pcb_move_footprint`
- `pcb_set_footprint_layer`
- `pcb_sync_from_schematic`

### Schematic

- `sch_get_symbols`
- `sch_get_wires`
- `sch_get_labels`
- `sch_get_net_names`
- `sch_add_symbol`
- `sch_add_wire`
- `sch_add_label`
- `sch_add_power_symbol`
- `sch_add_bus`
- `sch_add_bus_wire_entry`
- `sch_add_no_connect`
- `sch_update_properties`
- `sch_build_circuit`
- `sch_get_pin_positions`
- `sch_check_power_flags`
- `sch_annotate`
- `sch_reload`

`sch_build_circuit` can accept `auto_layout=true` for a readable grid placement. When a
`nets` list is also provided, it performs a lightweight connection-aware layout, creates
missing power symbols or labels for named nets, and generates Manhattan wire segments
from symbol pins. This is a deterministic helper, not a full KiCad-quality autorouter.
Multi-unit symbols such as dual op-amps can be placed and inspected with `unit=<n>`.
The MCP now validates requested units against the KiCad library and reports available
units instead of silently falling back to unit 1.

`pcb_sync_from_schematic` closes the first-board gap by reading schematic footprint
assignments and writing missing footprint instances into the `.kicad_pcb` file. It is
intended for initial board bring-up and footprint sync, not for full autorouting.
It preserves existing footprints by default, can replace wrong footprint names in place
with `replace_mismatched=true`, and performs a lightweight overlap-avoidance pass for
newly added footprints.

### Library

- `lib_list_libraries`
- `lib_search_symbols`
- `lib_get_symbol_info`
- `lib_search_footprints`
- `lib_list_footprints`
- `lib_rebuild_index`
- `lib_get_footprint_info`
- `lib_get_footprint_3d_model`
- `lib_assign_footprint`
- `lib_create_custom_symbol`
- `lib_search_components`
- `lib_get_component_details`
- `lib_assign_lcsc_to_symbol`
- `lib_get_bom_with_pricing`
- `lib_check_stock_availability`
- `lib_find_alternative_parts`
- `lib_get_datasheet_url`

Live component search now defaults to the zero-auth `jlcsearch` source. `nexar`
and `digikey` remain available as authenticated source options for deployments
that provide the required credentials.

### Export And Validation

- `run_drc`
- `run_erc`
- `validate_design`
- `check_design_for_manufacture`
- `get_unconnected_nets`
- `get_courtyard_violations`
- `get_silk_to_pad_violations`
- `validate_footprints_vs_schematic`
- `export_gerber`
- `export_drill`
- `export_bom`
- `export_netlist`
- `export_spice_netlist`
- `export_pcb_pdf`
- `export_sch_pdf`
- `export_3d_step`
- `export_step`
- `export_3d_render`
- `export_pick_and_place`
- `export_ipc2581`
- `export_svg`
- `export_dxf`
- `get_board_stats`
- `export_manufacturing_package`

### Routing

- `route_single_track`
- `route_from_pad_to_pad`
- `route_export_dsn`
- `route_import_ses`
- `route_autoroute_freerouting`
- `route_set_net_class_rules`
- `route_differential_pair`
- `route_tune_length`
- `tune_track_length` (deprecated alias)
- `tune_diff_pair_length`

Routing helpers now cover three layers:

- direct IPC routing for simple single-track and pad-to-pad paths
- rule-file authoring for net class, differential pair, and length-tuning constraints
- FreeRouting orchestration around Specctra `.dsn` / `.ses` files

Important limitation: KiCad 10 still does not expose a stable headless Specctra
export/import flow through `kicad-cli` on all installations. `route_export_dsn`
and `route_import_ses` therefore support staging existing `.dsn` / `.ses` files
and explain the remaining manual KiCad PCB Editor step when needed.

## Workflows

- [First PCB](docs/workflows/first-pcb.md)
- [Schematic to PCB](docs/workflows/schematic-to-pcb.md)
- [Manufacturing Package Export](docs/workflows/manufacturing-export.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the development docs in [docs/development](docs/development).

## License

Released under the [MIT License](LICENSE).
