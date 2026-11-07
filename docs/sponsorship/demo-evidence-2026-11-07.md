# Real-board sponsorship demo — evidence, scope, and limitations

**Recorded:** 7 November 2026 · **Video:** [46-second edited demo](sponsor-demo-royalblue54l.mp4) · **Preview:** [thumbnail](demo-thumbnail.png)

This video is a carefully labeled **edited product demonstration**, not one continuous KiCad IPC session. It combines **22 seconds of genuine KiCad PCB Editor screen recording** from an isolated headless X11 session with cards showing results of **separate, real MCP calls** on the same unmodified KiCad sample. No AI-generated board imagery or fabricated MCP responses were used.

## Software, sample, and reproducibility

| Component | Observed |
| --- | --- |
| KiCad PCB Editor / native CLI | 10.0.8 |
| KiCad MCP Pro package | Published 4.8.1 |
| MCP transport | stdio |
| MCP operating mode and profile | readonly / default |
| MCP tools enumerated | 24 |
| MCP project inspection source | **File-backed fallback**, because live editor IPC could not be connected in the MCP session |
| Input project | RoyalBlue54L Feather, shipped with the installed KiCad 10.0.8 demo package |
| Source acknowledgement | Lords Boards; upstream source README links to its RoyalBlue54L Feather project |
| Sample license | CERN Open Hardware Licence v2 Permissive (CERN-OHL-P-2.0), as provided with the KiCad demo |
| Original PCB SHA-256 | `535dbe212f43a8bab12b23277e176a94ac9694177258af2981c0e7b08e4b7252` |

The recording shows an existing third-party open hardware design; **KiCad MCP Pro did not create this board**. The complete source CAD files are *not* redistributed with this demo. No manufacturer was contacted and no fabrication, release, or hardware validation was performed.

## Measured results — actual MCP tool calls

- `kicad_get_server_info`: server version 4.8.1, KiCad CLI 10.0.8.
- `kicad_get_project_info`: correctly resolved the copied project and source files.
- `pcb_get_board_summary`: **71 footprints, 943 tracks, 95 named nets** using the file-backed parser.
- `run_drc`: **287 findings**, not a clean-board verdict.
- `run_erc`: **27 findings**, not a clean-schematic verdict.
- The source PCB SHA-256 matched before and after the procedure. Changes and outputs were confined to disposable scratch copies; no original design was written.

**Observed discrepancy:** the file-backed `pcb_get_board_summary` reported **185 vias**, while the native `pcbnew` parser and KiCad PCB Editor reported **183 vias**. Therefore the via total was intentionally excluded from the video metrics. This unresolved counting difference must not be presented as validated agreement. It is not a claim of an accepted real-board benchmark.

## What the demo does *not* prove

- No continuous editor-IPC-backed MCP session or native editor write acceptance.
- No complete autonomous board construction, qualified design-signoff or production-ready PCB.
- No real-world fabrication, ordering, electronics bench test or validated sales conversion.
- The source design has unresolved DRC/ERC findings. They are **reported**, not hidden or claimed fixed.
- The graphical recording is edited together with independently observed MCP outputs; it is not a recording of a single agent's seamless end-to-end interaction.

For the eventual continuous real agent/IPC demo, capture a fresh verified host session, preserving its tool traffic and constraints. See [metrics and demo plan](metrics-and-demo.md). The separate `docs/demo-media.md` terminal cast is synthetic and not interchangeable with this genuine GUI recording.
