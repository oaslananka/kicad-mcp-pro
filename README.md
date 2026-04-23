# KiCad MCP Pro Server
<!-- mcp-name: io.github.oaslananka/kicad-mcp-pro -->

[![PyPI](https://img.shields.io/pypi/v/kicad-mcp-pro.svg)](https://pypi.org/project/kicad-mcp-pro/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![KiCad 10](https://img.shields.io/badge/KiCad-10-success.svg)](https://www.kicad.org)
[![KiCad Studio](https://img.shields.io/badge/KiCad%20Studio-compatible-blue)](https://github.com/oaslananka/kicad-studio)
[![Downloads](https://img.shields.io/pypi/dm/kicad-mcp-pro.svg)](https://pypi.org/project/kicad-mcp-pro/)
[![MCP 1.6+](https://img.shields.io/badge/MCP-1.6%2B-purple.svg)](https://modelcontextprotocol.io/)

> AI-powered PCB and schematic design with KiCad. Works with Claude, Cursor, VS Code, Claude Code, and any MCP-compatible client.

The personal GitHub repository is the main public source. Automated GitHub CI/CD runs from the `oaslananka-lab` organization mirror; Azure DevOps, GitLab, and personal GitHub workflows stay manually triggered.

## What's New in 2.4

- KiCad 10 parity improved for variants, graphical DRC, time-domain routing, 3D PDF export, and schematic hop-over control.
- High-speed review flow now covers time-domain tuning, via-stub resonance warnings, thermal via sizing, and EMC return-path sweeps.
- MCP surface expanded with new resources, prompt workflows, `agent_full`, HTTP discovery metadata, and opt-in `/metrics`.
- Azure validation now includes dependency auditing and a Windows validation lane, with `Dockerfile.kicad10` available for CI images.

## Features

- Project-first workflow with `kicad_set_project()`, recent project discovery, and safe path handling.
- Project intent helpers with `project_set_design_intent()` and `project_get_design_intent()` for connector, decoupling, power-tree, analog/digital partitioning, sensor clustering, RF, and fab assumptions.
- KiCad 10.x-first runtime with best-effort 9.x support and cross-platform CLI/library discovery.
- PCB tools for board inspection, tracks, vias, footprints, text, shapes, outline editing, and zone refill.
- Schematic tools for symbols, wires, labels, buses, no-connect markers, property updates, annotation, netlist-aware auto-layout, hop-over display control, and IPC reload.
- Library tools for symbol search, footprint search, datasheet lookup, footprint assignment, and custom symbol generation.
- Validation tools for DRC, ERC, DFM, courtyard issues, silk overlaps, and schematic-versus-PCB footprint checks.
- Project quality gates for schematic, schematic connectivity, PCB, placement, PCB transfer, manufacturing, and gated manufacturing handoff via `export_manufacturing_package()`.
- Export tools for Gerber, drill, BOM, PDF, netlist, STEP, render, pick-and-place, IPC-2581, SVG, and DXF.
- Signal integrity tools for impedance synthesis, differential skew checks, stackup planning, via-stub review, and decoupling heuristics.
- Power integrity tools for voltage-drop estimation, copper current checks, plane generation, and thermal via guidance.
- EMC tools for plane coverage, return-path review, via stitching, diff-pair symmetry, and bundled compliance sweeps.
- Simulation tools for SPICE operating-point, AC, transient, DC sweep, and loop-stability checks.
- MCP resources for live board/project state, quality gates, fix queues, connectivity, and placement review.
- Prompt workflows for first-board, schematic-to-PCB, manufacturing release, design review loops, and critic/fixer iterations.
- Server profiles (`full`, `minimal`, `schematic_only`, `pcb_only`, `manufacturing`, `high_speed`, `power`, `simulation`, `analysis`, `agent_full`) to reduce tool surface for clients. Legacy `pcb` and `schematic` aliases remain available.

## KiCad 10 Feature Matrix

| Feature area | KiCad 9.x | KiCad 10.x |
|---|---|---|
| Core PCB + schematic inspection | Yes | Yes |
| Manufacturing exports | Yes | Yes |
| Project-backed variant tools (`variant_*`) | Best effort | Yes |
| Graphical DRC rule editing (`drc_rule_*`) | Best effort | Yes |
| Time-domain routing helpers (`route_tune_time_domain`) | Fallback-to-length | Yes |
| 3D PDF export (`pcb_export_3d_pdf`) | No | Yes |
| Inner-layer footprint graphics | Limited | Yes |
| Design blocks + barcode helpers | Sidecar/file-based | Yes |

## Demo

- First-board walkthrough script: [docs/workflows/first-pcb.md](docs/workflows/first-pcb.md)
- High-speed preflight workflow: [docs/workflows/high-speed-review.md](docs/workflows/high-speed-review.md)
- KiCad Studio bridge setup: [docs/integration/kicad-studio.md](docs/integration/kicad-studio.md)
- HTTP deployment notes: [docs/deployment/http-mode.md](docs/deployment/http-mode.md)

## Comparison

| Capability | kicad-mcp-pro | Generic KiCad scripts | Raw `kicad-cli` |
|---|---|---|---|
| MCP tools/resources/prompts | Yes | No | No |
| Project quality gates | Yes | Rare | No |
| KiCad Studio local bridge | Yes | No | No |
| Variant-aware workflows | Yes | Rare | No |
| Streamable HTTP transport | Yes | Rare | No |
| DRC/DFM/manufacturing bundle | Yes | Partial | Partial |

## KiCad Studio Integration

`kicad-mcp-pro` can run as a local HTTP bridge for the TypeScript-based `kicad-studio` extension. The bridge now supports:

- `studio_push_context()` for active file, DRC errors, selected net/reference, and cursor state.
- `kicad://studio/context` as a resource that agents can read directly.
- `KICAD_MCP_STUDIO_WATCH_DIR` for auto-project detection when `.kicad_pro` files change.
- `/.well-known/mcp-server` discovery plus bearer-token auth and CORS configuration for local-only deployments.

For Studio deployments, `27185` is a good dedicated local bridge port by convention. The server default remains `3334`, so either set `KICAD_MCP_PORT=27185` explicitly or keep the default and point the Studio client at that port.

## CI/CD

Repository ownership is split on purpose:

- Main source repository: `https://github.com/oaslananka/kicad-mcp-pro`
- GitHub CI/CD mirror: `https://github.com/oaslananka-lab/kicad-mcp-pro`

The `ci.yml` and `security.yml` GitHub workflows run automatically only when the repository owner is `oaslananka-lab`. On the personal GitHub repository they remain manual fallback workflows. Azure DevOps and GitLab pipelines are manual fallback/release-support surfaces.

Package publication to TestPyPI or PyPI remains manual and should be queued only after the version, changelog, and artifacts are ready. CI/CD can use Doppler as the central secret store by adding only `DOPPLER_TOKEN` to GitHub org, Azure, or GitLab; `PYPI_TOKEN`, `TEST_PYPI_TOKEN`, `SAFETY_API_KEY`, `NPM_TOKEN`, `OVSX_PAT`, and `VSCE_PAT` are then injected with `doppler run -- ...`. See [Repository and CI/CD Topology](docs/deployment/repository-topology.md) for the full policy.

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
        "KICAD_MCP_PROFILE": "pcb_only"
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
KICAD_MCP_PROFILE = "pcb_only"
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

Add a custom MCP server using `uvx` as the command and `kicad-mcp-pro` as the only argument. For remote-style usage, run `kicad-mcp-pro --transport http` and connect to `http://127.0.0.1:3334/mcp`. If you want Cursor and KiCad Studio to share the same local bridge convention, set `KICAD_MCP_PORT=27185` and connect to `http://127.0.0.1:27185/mcp` instead.

### Claude Code

Launch the server with `uvx kicad-mcp-pro`, then attach it from your MCP config. The `minimal` profile is a good default when you mainly want read/export workflows, while `pcb_only` and `analysis` are good focused options for board-heavy sessions.

### More Clients

Copy-ready configuration examples for VS Code, GitHub Copilot in VS Code, Codex,
Claude Desktop, Claude Code, Cursor, Gemini CLI, Antigravity-compatible clients, and
HTTP transports are available in [Client Configuration](docs/client-configuration.md).

## Prerequisites

- KiCad 9.0 or 10.0+ installed.
- Python 3.12+.
- For live IPC tools, KiCad must be running with the IPC API available.
- For HTTP transport, install the `http` extra: `pip install "kicad-mcp-pro[http]"`.
- For FreeRouting orchestration helpers, install the `freerouting` extra:
  `pip install "kicad-mcp-pro[freerouting]"`.
- For SPICE simulation tools, install the `simulation` extra:
  `pip install "kicad-mcp-pro[simulation]"`.
- For Git checkpoint tools, install the `vcs` extra:
  `pip install "kicad-mcp-pro[vcs]"`.

## Docker Limitations

- The published container image does not bundle a KiCad installation.
- `kicad-cli`-backed export and validation tools require a KiCad installation inside the
  container, typically mounted at `/usr/bin/kicad-cli`, or `KICAD_MCP_KICAD_CLI` pointed to a
  valid binary.
- The default Compose setup mounts the project read-only and writes exports to
  `/tmp/kicad-mcp-output`. For edit/write workflows, change the project volume to `rw`
  intentionally and keep remote HTTP deployments behind trusted authentication and origin checks.
- Live IPC tools still require a reachable KiCad session with the IPC API enabled.

## Configuration

| Variable                              | Description                                  | Default            |
| ------------------------------------- | -------------------------------------------- | ------------------ |
| `KICAD_MCP_KICAD_CLI`                 | Path to `kicad-cli`                          | Auto-detected      |
| `KICAD_MCP_NGSPICE_CLI`               | Path to `ngspice`                            | Auto-detected      |
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
| `KICAD_MCP_CORS_ORIGINS`              | Explicit HTTP/HTTPS origin allowlist         | Empty              |
| `KICAD_MCP_AUTH_TOKEN`                | Optional bearer token for HTTP bridge        | Unset              |
| `KICAD_MCP_LEGACY_SSE`                | Re-enable legacy SSE transport               | `false`            |
| `KICAD_MCP_STATEFUL_HTTP`             | Disable stateless HTTP mode                  | `false`            |
| `KICAD_MCP_ENABLE_METRICS`            | Reserve `/metrics` support for HTTP mode     | `false`            |
| `KICAD_MCP_PROFILE`                   | Tool profile                                 | `full`             |
| `KICAD_MCP_LOG_LEVEL`                 | Log level                                    | `INFO`             |
| `KICAD_MCP_LOG_FORMAT`                | `console` or `json`                          | `console`          |
| `KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS` | Enable unstable helpers                      | `false`            |
| `KICAD_MCP_IPC_CONNECTION_TIMEOUT`    | KiCad IPC timeout in seconds                 | `10.0`             |
| `KICAD_MCP_CLI_TIMEOUT`               | `kicad-cli` timeout in seconds               | `120.0`            |
| `KICAD_MCP_MAX_ITEMS_PER_RESPONSE`    | Max list items returned                      | `200`              |
| `KICAD_MCP_MAX_TEXT_RESPONSE_CHARS`   | Max text payload length                      | `50000`            |

Preferred profile names are `full`, `minimal`, `schematic_only`, `pcb_only`,
`manufacturing`, `high_speed`, `power`, `simulation`, `analysis`, and
`agent_full`. Legacy aliases `pcb` and `schematic` still work for older clients.

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
- `project_set_design_intent`
- `project_get_design_intent`

### PCB

- `pcb_get_board_summary`
- `pcb_get_tracks` (`page`, `page_size`, `filter_layer`, `filter_net`)
- `pcb_get_vias`
- `pcb_get_footprints` (`page`, `page_size`, `filter_layer`)
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
- `pcb_get_impedance_for_trace`
- `pcb_check_creepage_clearance`
- `pcb_add_track`
- `pcb_add_tracks_bulk`
- `pcb_add_via`
- `pcb_add_segment`
- `pcb_add_circle`
- `pcb_add_rectangle`
- `pcb_add_text`
- `pcb_set_board_outline`
- `pcb_set_stackup`
- `pcb_add_blind_via`
- `pcb_add_microvia`
- `pcb_auto_place_by_schematic`
- `pcb_place_decoupling_caps`
- `pcb_group_by_function`
- `pcb_align_footprints`
- `pcb_set_keepout_zone`
- `pcb_add_mounting_holes`
- `pcb_add_fiducial_marks`
- `pcb_add_teardrops`
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
- `sch_create_sheet`
- `sch_list_sheets`
- `sch_get_sheet_info`
- `sch_add_symbol`
- `sch_add_wire`
- `sch_add_label`
- `sch_add_global_label`
- `sch_add_hierarchical_label`
- `sch_add_power_symbol`
- `sch_add_bus`
- `sch_add_bus_wire_entry`
- `sch_add_no_connect`
- `sch_update_properties`
- `sch_build_circuit`
- `sch_get_pin_positions`
- `sch_route_wire_between_pins`
- `sch_get_connectivity_graph`
- `sch_trace_net`
- `sch_auto_place_symbols`
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

v2 also adds board bring-up helpers on top of that sync path. `pcb_auto_place_by_schematic`
can lay out the first board in `cluster`, `linear`, or `star` mode, while
`pcb_group_by_function`, `pcb_align_footprints`, and `pcb_place_decoupling_caps`
help refine the initial placement without opening the PCB editor. `pcb_add_mounting_holes`
and `pcb_add_fiducial_marks` append simple manufacturing footprints, `pcb_set_keepout_zone`
creates a real rule-area keepout on the active board, and `pcb_add_teardrops` adds
small copper helper zones at basic pad-to-track junctions when the board is open over IPC.
For multilayer bring-up, `pcb_set_stackup` stores a file-backed stackup profile and updates
the board setup block so later tools can reuse the same dielectric assumptions.
`pcb_get_impedance_for_trace` reads that active stackup and estimates impedance for a given
trace width on a selected copper layer, while `pcb_check_creepage_clearance` performs a
heuristic pad-to-pad creepage review against voltage, pollution degree, and material group.
`pcb_add_blind_via` and `pcb_add_microvia` use KiCad IPC to create layer-pair vias with
explicit start and end copper layers.

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
- `schematic_quality_gate`
- `schematic_connectivity_gate`
- `validate_design`
- `pcb_quality_gate`
- `pcb_placement_quality_gate`
- `pcb_score_placement`
- `manufacturing_quality_gate`
- `project_quality_gate`
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

`export_manufacturing_package` is now a release-only helper. It first runs the full
`project_quality_gate()` and hard-blocks the package when the design is still `FAIL`
or `BLOCKED`. `pcb_transfer_quality_gate()` is part of that release contract, so
schematic pad nets must transfer cleanly onto PCB pads before the gated release
handoff is allowed. Use the low-level export tools for debugging or interchange
artifacts while iterating; they do not enforce `project_quality_gate()`. The
`manufacturing` profile keeps its export surface narrow around `get_board_stats()` and
`export_manufacturing_package()`, while broader profiles such as `full` and `minimal`
continue to expose the direct `export_*()` tools.

`pcb_placement_quality_gate()` is the blocking geometry/context gate. `pcb_score_placement()`
adds softer density and spread heuristics so an agent can improve layout quality before a
hard failure happens. Placement scoring is now intent-aware for connector edge usage,
decoupling proximity, RF keepouts, power-tree locality, analog/digital separation, and
sensor clustering.

### DFM

- `dfm_load_manufacturer_profile`
- `dfm_run_manufacturer_check`
- `dfm_calculate_manufacturing_cost`

DFM profiles are now bundled with the server for quick fabrication review. The
first v2 profile set includes `JLCPCB` (`standard`, `advanced`), `PCBWay`
(`standard`), and `OSH Park` (`2layer`). `dfm_load_manufacturer_profile`
stores the active selection in the project output directory so later DFM checks
can reuse the same fabricator assumptions.

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

### Simulation

- `sim_run_operating_point`
- `sim_run_ac_analysis`
- `sim_run_transient`
- `sim_run_dc_sweep`
- `sim_check_stability`
- `sim_add_spice_directive`

Simulation tools use direct `ngspice` CLI execution by default and can still use
`InSpice` when it is installed manually in the runtime environment. The
`sim_add_spice_directive` tool stores a project-local sidecar file used by future
MCP simulation runs, which is useful for reusable `.param`, `.include`, or
`.options` lines.

### Signal Integrity

- `si_calculate_trace_impedance`
- `si_calculate_trace_width_for_impedance`
- `si_check_differential_pair_skew`
- `si_validate_length_matching`
- `si_generate_stackup`
- `si_check_via_stub`
- `si_calculate_decoupling_placement`

These helpers provide fast board-level estimates for routing and review. They are
intended for engineering triage and pre-layout guidance, then should be verified
against your fabricator stackup and final KiCad rule setup before tape-out.

### Power Integrity

- `pdn_calculate_voltage_drop`
- `pdn_recommend_decoupling_caps`
- `pdn_check_copper_weight`
- `pdn_generate_power_plane`
- `thermal_calculate_via_count`
- `thermal_check_copper_pour`

These tools focus on quick PDN sanity checks: whether a rail looks too resistive,
whether routed copper is undersized, whether a local plane exists, and how much
thermal stitching is likely needed around hotter regions.

### EMC

- `emc_check_ground_plane_voids`
- `emc_check_return_path_continuity`
- `emc_check_split_plane_crossing`
- `emc_check_decoupling_placement`
- `emc_check_via_stitching`
- `emc_check_differential_pair_symmetry`
- `emc_check_high_speed_routing_rules`
- `emc_run_full_compliance`

These EMC helpers use board-state heuristics so an agent can quickly flag likely
return-path, stitching, plane, and decoupling problems before a manual SI/EMI review.

### Version Control

- `vcs_init_git`
- `vcs_commit_checkpoint`
- `vcs_list_checkpoints`
- `vcs_restore_checkpoint`
- `vcs_tag_release`
- `vcs_diff_with_checkpoint`

These tools scope Git actions to the active KiCad project directory, add local
identity defaults when needed, and protect restores by stashing dirty project
state before rolling files back to a checkpoint commit.

## Workflows

- [First PCB](docs/workflows/first-pcb.md)
- [Schematic to PCB](docs/workflows/schematic-to-pcb.md)
- [Manufacturing Package Export](docs/workflows/manufacturing-export.md)
- [Azure DevOps CI/CD](docs/deployment/azure-devops.md)

The built-in MCP prompt set now also includes:

- `design_review_loop`
- `fix_blocking_issues`
- `manufacturing_release_checklist`

The resource surface now exposes:

- `kicad://project/quality_gate`
- `kicad://project/fix_queue`
- `kicad://schematic/connectivity`
- `kicad://board/placement_quality`

For regression coverage, the repository also ships a benchmark and failure corpus under
`tests/fixtures/benchmark_projects/`. These fixtures are used to prove that clean projects
can reach release export while known-bad projects stay hard-blocked. The corpus includes
label-only schematic failures, overlap/DFM failures, bad decoupling placement, wide sensor
clusters, dirty PCB transfer cases, and SismoSmart-style hierarchy/connectivity regressions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the development docs in [docs/development](docs/development).

## License

Released under the [MIT License](LICENSE).
