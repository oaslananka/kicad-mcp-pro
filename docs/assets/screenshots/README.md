# Public Listing Screenshot Manifest

The PNG files in this directory are the committed public-listing screenshot
slots. They are safe evidence images built from repository-owned fixtures and
product surfaces; they must never include private board data, customer files,
secret values, local auth state, private absolute paths, or personal usernames.

Each file must preserve its filename and 1920x1080 dimensions.

| File | Intended evidence | Client/surface | Fixture project | Exact tool call or surface |
|---|---|---|---|---|
| `01-claude-desktop-quality-gate.png` | Quality gate review with pass/fix queue visible | Claude Desktop / MCP transcript | `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro` | `project_quality_gate` |
| `02-cursor-schematic-build.png` | Schematic construction prompt and result summary | Cursor / MCP transcript | `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro` | `sch_build_circuit` |
| `03-vscode-pcb-inspection.png` | Board state inspection with safe read-only result | VS Code MCP / MCP transcript | `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro` | `pcb_get_board_state` |
| `04-tools-reference.png` | Tools reference catalog or generated tool table | Browser/docs | Repository docs | `kicad_list_tool_categories` |
| `05-export-manufacturing.png` | Manufacturing export gate with evidence-linked posture | Claude Desktop / MCP transcript | `tests/fixtures/benchmark_projects/pass_sensor_node/demo.kicad_pro` | `export_manufacturing_package` |

Replacement checklist:

1. Use only repository fixtures or public docs.
2. Capture or render to exactly 1920x1080.
3. Preserve the existing filename.
4. Re-run `SUBMISSION_MODE=1 pnpm run submission:check`.
5. Do not update `scripts/_placeholder_hashes.json`; it is retained only to
   detect obsolete placeholder media in final submission mode.
