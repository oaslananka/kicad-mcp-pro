# KiCad MCP Pro — controlled schematic-edit demonstration evidence

**Date:** 2026-11-07 · **Recording:** [85-second MP4](sponsor-demo-controlled-schematic-edit.mp4) · **Preview:** [PNG](demo-thumbnail.png)

## What the video actually shows

An **uninterrupted recording of a custom diagnostic client monitor while real MCP tool calls run** against a copy of a repository-owned ESP32-C3 example schematic. The UI is explicitly labeled **DEMO HARNESS**; it is not the published KiCad MCP Pro GUI or an autonomous LLM. The KiCad schematic view/inset was rendered by actual `kicad-cli sch export svg` from the **exact same verified source contents**, prior to recording to avoid costly SVG transformations during the live call sequence. Rendered views are not a live KiCad GUI/IPC session.

The demonstration deliberately exercises **two tool plans**:

1. **Unsafe candidate:** insert `EN_DIAG` on an empty part of the sheet; `sch_plan_from_spec` and `sch_preview_plan` run without mutating the schematic; `sch_apply_plan` writes to the isolated copy; `sch_verify_plan` returns **FAIL — unconnected EN_DIAG**; `sch_rollback_plan` restores the **bit-identical input hash**; KiCad ERC remains at **0**.
2. **Corrected candidate:** add the consistent `EN` label at the already-connected EN wire endpoint. Plan, preview, and apply are real MCP calls. `sch_verify_plan` returns **PASS** and an independent KiCad CLI ERC check reports **0 violations**, same as before the change.

The video illustrates **guarded, reversible design-edit tooling** rather than merely scanning a board. A deterministic harness chooses the two candidate edits; no language model reasoned over the project. The changes are small, and the result **does not prove autonomous schematic generation, routing, PCB fabrication, manufacturing sign-off or full benchmark task success**.

## Pinned environment and proof

| Property | Verified observation |
| --- | --- |
| Project | `examples/gallery/esp32-c3-wroom-02-breakout/` (repo-owned example, copied into an isolated scratch directory) |
| KiCad engine | 10.0.8 (native `kicad-cli sch erc` and schematic SVG exporter) |
| KiCad MCP Pro package | Published 4.8.1 |
| MCP transport | stdio |
| Profile and mode | `build` / `write`; **17 callable tools** observed in the session (do not substitute documentation's 24-tool target) |
| Tool calls | `sch_plan_from_spec`, `sch_preview_plan`, `sch_apply_plan`, `sch_verify_plan`, `sch_rollback_plan` |
| ERC before, after rollback, after corrected edit | **0, 0, 0** |
| Input schematic SHA-256 | `b4845b432646d31e09cf4a38e3f57c762680263291c7ecfa79de56c58f64cf68` |
| Final isolated schematic SHA-256 | `692fb3f42fc9c73e1ac226c47da0d8f662f3d87da9d97a9a31de806f54e3a1f9` |
| MP4 | 1600 × 900, approximately 85 seconds, H.264, silent |
| MP4 SHA-256 | `3fe86437b8279be61afa44f2cc507ff789ece130e9388a778cfa28e4007030ab` |

**Scope:** No change to the canonical source example, user board, registry package, production server, GitHub configuration or third-party manufacturing service. All test mutations, checkpoints and ERC reports were confined to scratch copies. No paid model calls, API keys or outbound vendor messages.

## What remains unverified

- A real LLM agent independently interpreting a requested electronics-engineering task and selecting safe MCP tool calls.
- A meaningful corrective design edit beyond a net-label addition, with native PCB/DRC and hardware-engineering review.
- Continuous KiCad PCB Editor IPC state coupled to the MCP mutation.
- Evidence that a full reference board can be built autonomously from a spec and pass the published task-success acceptance criteria (#729/#730).
- Sponsorship, commercial conversion or manufacturer endorsement.

For a sponsor-facing flagship demo, select a realistic engineering task (such as actually repairing a verified schematic connectivity fault), run it using a named AI client/model in an isolated project, then retain a continuous recording of the agent, KiCad and verification results, with complete non-cherry-picked attempt history.
