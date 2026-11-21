# Agent-friendly tool workflow index

Use this page when an agent needs to choose tools by workflow instead of scanning an alphabetical reference.

## Recommended agent loop

```text
inspect -> plan -> modify -> preview -> ERC -> DRC -> DFM -> export -> summarize
```

Start read-only. Move to write tools only after the agent has explained the plan and the operator has approved the intended edits.

## Bind the active project first

Every workflow operates on one active project per server process. Bind it before other calls:

1. `kicad_set_project(project_dir, pcb_file, sch_file, output_dir)` — set the active KiCad project directory and its file paths.
2. `kicad_get_project_info()` — confirm the resolved paths (`kicad_set_project` returns the binding, but re-read it to verify).
3. `project_get_next_action()` — read the next high-priority action derived from the current project gate and follow it before improvising.

Project selection is process-wide, not per MCP session. A shared Streamable HTTP server pins the project at the first tool call and rejects `kicad_set_project` and `kicad_create_new_project` afterwards, so bind the project before connecting HTTP clients or run a dedicated `stdio` process per project. See [Configuration](configuration.md) for the HTTP binding rules.

## Workflow groups

| Workflow | Start with | Write or gated tools | Evidence to collect |
| --- | --- | --- | --- |
| Project discovery | `kicad_get_version()`, `kicad_set_project()`, `kicad_list_tool_categories()` | none | project info resource, tool category list, diagnostics |
| Schematic read | schematic hierarchy and inspection tools | none | sheet list, symbol/net summaries, ERC-relevant notes |
| Schematic write | read-only schematic inspection first | `sch_*` mutation tools, transactional writers | changed files, preview image, visual QA, ERC output |
| PCB read | board stats and board inspection tools | none | layer count, placement summary, DRC-relevant notes |
| PCB write | placement/routing plan first | placement, track, via, zone, and sync tools | changed files, DRC output, placement score, screenshots/renders |
| ERC/DRC | `schematic_connectivity_gate()`, DRC tools | none unless auto-fix is explicitly approved | rule output, warnings, blocking failures |
| DFM/manufacturing | `manufacturing_quality_gate()` | `export_manufacturing_package()` after gates pass | package path, manifest, gate summary |
| Preview/render | `sch_live_preview()`, render and visual diff tools | GUI-facing refresh only with explicit operator intent | PNG/SVG paths, manifest, visual diff, warnings |
| Sourcing/BOM | BOM and pricing tools | none unless fields are explicitly updated | unresolved line list, exact part-code matches, warnings |
| Diagnostics | `doctor`, capability and environment checks | none | runtime diagnostics, missing dependency list |

## Safe starter tools

For first contact, agents should prefer read-only discovery and diagnostics:

1. detect project and runtime version;
2. list available tool categories;
3. inspect schematic and board metadata;
4. run read-only gates and diagnostics;
5. render preview evidence where available;
6. summarize without changing files.

## Write-tool expectations

Before using write tools, the agent should state:

- which file or object will change;
- why the change is needed;
- which verification tools will run afterwards;
- what rollback or review evidence will be available.

After using write tools, the agent should collect structured output, changed files, visual evidence, and ERC/DRC/DFM results before making further changes.

### Default new-schematic authoring

For new functional schematics, follow the [wired-subcircuit-design skill](https://github.com/oaslananka/kicad-mcp-pro/blob/main/skills/wired-subcircuit-design/SKILL.md) before placement. Draw short connected power, reset/boot, decoupling and interface blocks with explicit orthogonal wires, use matched labels between distant blocks, and select the page from content extents. Keep component values distinct from net names. The existing automatic label-only layout is a collision-safe fallback, not a readability acceptance result. Review the native render and ERC separately; for cosmetic transformations preserve netlist/connectivity and reference identity, and refuse or roll back unsafe edits. Do not claim visual quality when native rendering is unavailable.

### PCB transaction scoping

`pcb_begin_commit`, `pcb_push_commit`, and `pcb_drop_commit` group live-board mutations into one native-live transaction. Only reviewed operations participate in an active transaction; the router keeps a fixed allowlist and each participating operation must supply a postcondition verifier.

`pcb_add_tracks_bulk` is **not** in that allowlist. While a transaction is open, calling it is refused with: *"pcb_add_tracks_bulk does not participate in the active native-live transaction. Commit or discard the transaction before using this operation."* Bulk track additions therefore cannot be staged inside a commit group. Either add tracks one at a time with `pcb_add_track` (which does participate), or commit or drop the current transaction before running the bulk call. On an IPC failure the session state becomes ambiguous and further transactions are blocked until the active board is reconciled, so treat a transaction as a single long-running unit rather than interleaving unrelated tool calls.

## Common failure states

- **Project not found:** ask for a valid folder containing a `.kicad_pro` file.
- **KiCad CLI unavailable:** continue with file-backed checks where possible and report missing runtime capability.
- **Preview unavailable:** return the renderer diagnostic and avoid claiming visual confirmation.
- **Gate failed:** stop export or downstream workflow until the failure is reviewed.
- **Readonly mode:** explain that write tools are intentionally unavailable for onboarding.

## Related references

- [Tools Reference](tools-reference.md)
- [Generated Tools Reference](tools-reference.generated.md)
- [Safe Live Preview](workflows/live-preview.md)
- [Manufacturing Export](workflows/manufacturing-export.md)
