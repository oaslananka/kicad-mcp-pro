# Agent-friendly tool workflow index

Use this page when an agent needs to choose tools by workflow instead of scanning an alphabetical reference.

## Recommended agent loop

```text
inspect -> plan -> modify -> preview -> ERC -> DRC -> DFM -> export -> summarize
```

Start read-only. Move to write tools only after the agent has explained the plan and the operator has approved the intended edits.

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
