# Read-only agent review workflow

Use this workflow before allowing an agent to modify KiCad files. It gives the agent enough project context to inspect, render, and summarize without writing design data.

## Goal

Produce a safe first-pass project review that answers:

- what KiCad project is open;
- which schematic and board files are present;
- whether ERC/DRC-relevant issues are visible;
- whether a schematic preview can be rendered;
- what the agent recommends checking next.

## First prompt

```text
Open the current KiCad project, inspect the schematic hierarchy, list ERC-relevant issues, render a schematic preview, and explain what changed without modifying files.
```

## Recommended setup

Use read-only mode for first contact:

```json
{
  "KICAD_MCP_PROFILE": "default",
  "KICAD_MCP_OPERATING_MODE": "readonly"
}
```

## Expected tool sequence

A careful agent should follow this sequence:

1. discover the active project and available KiCad files;
2. inspect schematic hierarchy and board metadata;
3. run read-only ERC/DRC or diagnostic tools where available;
4. render a schematic preview or report why rendering is unavailable;
5. summarize findings and recommended next actions;
6. stop before using write tools.

## Expected output

The final answer should include:

- project identity and files inspected;
- ERC/DRC or diagnostic findings;
- preview/render artifact path when produced;
- warnings about missing KiCad CLI, missing board file, or unavailable renderer;
- next actions grouped into safe read-only checks and optional write-mode changes.

## Safety boundaries

- Do not switch to write mode during this workflow.
- Do not use auto-fix, placement, routing, netlist mutation, or export publication tools.
- Treat previews and reports as evidence for human review, not as fabrication sign-off.
- If a tool reports an unsafe, dirty, or unavailable state, summarize it instead of retrying with broader permissions.

## Follow-up workflows

After the read-only review is complete, use:

- [Safe live-preview workflow](live-preview.md) for schematic edit feedback;
- [Professional Circuit Design](professional-circuit-design.md) for planned design changes;
- [Manufacturing Export](manufacturing-export.md) only after ERC/DRC/DFM review and human approval.
