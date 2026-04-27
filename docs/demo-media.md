# Demo Media

The README expects one short demo GIF that shows the project value in the first viewport.

## Target Clip

Length: about 30 seconds.

Workflow:

1. Configure a VS Code MCP session.
2. Call `kicad_set_project`.
3. Call `sch_build_circuit`.
4. Call `pcb_sync_from_schematic`.
5. Call `export_manufacturing_package`.

## Suggested Tooling

Record with `asciinema`, then convert to GIF with `agg`.

```bash
asciinema rec docs/assets/demo.cast
agg docs/assets/demo.cast docs/assets/demo.gif
```

Keep the GIF small enough for GitHub README rendering. If the binary asset is too large, use a linked release asset instead of committing it.
