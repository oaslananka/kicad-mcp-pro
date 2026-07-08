# Glossary

This glossary explains common electronics, manufacturing, and evidence terms used in KiCad MCP Pro docs and agent workflows.

| Term | Meaning |
| --- | --- |
| ERC | Electrical Rules Check. A schematic-level check for issues such as unconnected pins, conflicting pin types, or undriven power inputs. |
| DRC | Design Rules Check. A PCB-level check for clearance, track width, via, zone, and manufacturing rule violations. |
| DFM | Design for Manufacturing. Review of whether a board can be fabricated and assembled reliably by a manufacturer. |
| BOM | Bill of Materials. The component list needed for sourcing, assembly, costing, and release review. |
| Gerber | Standard PCB fabrication output describing copper, solder mask, silkscreen, and related manufacturing layers. |
| Drill file | Manufacturing output describing plated and non-plated holes. Usually reviewed with Gerbers before fabrication. |
| Pick-and-place | Assembly file listing component references, package positions, rotations, and board side. |
| Proof artifact | A durable file that supports a claim made by a tool run, such as a report, manifest, rendered image, exported package, or CI output. |
| Visual evidence | A render, screenshot, diff image, or preview that lets a human or agent inspect visible design state. |
| Manifest | A structured JSON file that records what happened during a workflow, including inputs, watched files, generated artifacts, warnings, and safety decisions. |
| Live preview | A schematic feedback workflow that watches design files and can produce rendered preview evidence after changes settle. |
| Human sign-off | Final engineering approval by a qualified human. KiCad MCP Pro can assist review but does not replace sign-off. |

## Agent usage note

Agents should prefer structured tool output and proof artifacts over natural-language summaries when making workflow decisions. A clean ERC/DRC/DFM result is useful evidence, but it is not a guarantee of fabrication readiness or product safety.
