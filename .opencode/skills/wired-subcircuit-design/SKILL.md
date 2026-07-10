---
name: wired-subcircuit-design
description: Build a genuinely wired, showcase-grade KiCad schematic with KiCad MCP Pro — wired sub-circuit islands plus a tidy label bus — instead of the correct-but-plain by-name-label output of auto layout.
---

# Wired Sub-circuit Design Skill

Use this skill when an agent must produce a schematic that *looks* like a person
drew it — wired functional blocks, conventional power, a clean breakout bus — not
just an electrically valid netlist. It is the deliberate, higher-effort path that
`sch_build_circuit(auto_layout=True, nets=...)` cannot reach.

Specific to `oaslananka/kicad-mcp-pro`. Keep in sync with
`docs/tools-reference.generated.md`. Worked reference:
[`examples/gallery/esp32-c3-wroom-02-breakout`](../../examples/gallery/esp32-c3-wroom-02-breakout/README.md).

## Why auto layout is not enough

`sch_build_circuit` with `nets` uses a **collision-safe terminal** strategy: every
pin endpoint gets a stub plus a same-named global label / power symbol, so nets
connect *by name* and can never short by crossing geometry. That is correct and
ERC-clean, but it reads as a machine netlist: every decoupling cap floats between
its own `+3V3` and `GND` labels instead of being wired. Showcase quality needs
explicit placement and wires. The cosmetic score never measures this — **judge the
render, not the number.**

## The one rule that avoids a blank sheet

Build the whole sheet in a **single `sch_build_circuit` pass** with explicit
`symbols` (with coordinates), `wires`, `labels` and `power_symbols` — and **no**
`nets`, **no** `auto_layout`. Do *not* assemble a schematic from scratch with
repeated `sch_add_symbol` calls: a freshly seeded sheet has no root UUID that the
reader round-trips, so each incremental add stamps a different instance path and
KiCad renders a blank sheet even though the file parses. One pass writes one
consistent root UUID, so every symbol lands on the root sheet.

Compute exact pin coordinates up front with `get_pin_positions(lib, sym, x, y,
rot)` (pure geometry — no placement needed), then wire pin-tip to pin-tip.

## Design pattern

1. **Anchor** the main part (MCU / module) in the center.
2. **Wire the sub-circuit islands.** Decoupling, reset, boot-strap, status LED,
   regulators — draw each as a real wired block ending in power symbols. This is
   what separates a showcase from auto output; do not let these become floating
   labelled pins.
3. **Label bus for the breakout.** Route general IO to a header with matched local
   labels. Generate the part-side and header-side labels **from one source list**
   so the two label sets are identical by construction — this eliminates the whole
   `isolated_pin_label` / `label_dangling` class, not just the ones you happen to
   see.
4. **Conventional power.** `+3V3` up, `GND` down; put exactly one `PWR_FLAG` on
   each supply net so ERC sees the rails driven.
5. **Place each sub-circuit in its own x-column** below the anchor, and keep
   decoupling clear of the anchor's stub fan — most first-pass ERC errors
   (`multiple_net_names`) come from a power symbol landing on a neighbouring
   label.
6. **Fill the title block** with `sch_set_title_block_info`.

## Attach labels correctly

A net label must sit on a wire endpoint. When tapping a sub-circuit node, add a
short stub wire and place the label at the stub's free end — a label floating
beside a wire raises `label_dangling`.

## The loop

1. **Plan** all coordinates from `get_pin_positions`; assemble the four lists.
2. **Build** in one `sch_build_circuit` pass.
3. **Guard with ERC.** Run `run_erc`. Fix every violation before judging looks —
   a blank/oddly-passing ERC means KiCad isn't reading your symbols (see the root
   UUID rule).
4. **See.** Render with `sch_render_png` (or `kicad-cli sch export svg`) and judge
   against the rubric below. The render is ground truth.
5. **Refine** placement for overlaps and composition; rebuild. Stop when ERC is
   clean and nothing overlaps — do not chase the cosmetic score past that.

## Rubric — what "wired showcase" looks like

- Functional blocks are **wired**, not floating labelled pins.
- Power symbols are conventional; one `PWR_FLAG` per supply.
- The breakout bus is tidy and every label is matched (no isolated labels).
- Orthogonal wiring, on-grid, no diagonal runs, no overlapping graphics.
- Complete title block; content composed rather than crammed in one corner.

## Guardrails

- Wired ≠ correct-by-magic. Finish with `run_erc`; a showcase must also be clean.
- Prefer the label bus over routed `nets` wires (`unsafe_routed_wires=True` can
  short by crossing geometry — avoid it).
- One curated example is worth more than a bulk auto-generated gallery; expect
  per-example effort.
