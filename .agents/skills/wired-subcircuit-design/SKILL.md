---
name: wired-subcircuit-design
description: Default workflow for authoring readable new MCU, power, interface and other functional KiCad schematics with KiCad MCP Pro; use wired subcircuits, a tidy label bus, native ERC and rendered review.
---

# Wired Sub-circuit Design Skill

Use this skill for ordinary new functional schematics, not just showcase requests.
A readable drawing has wired functional blocks, conventional power and a clean
breakout bus, not merely an electrically valid netlist. Choose this workflow before
using `sch_build_circuit(auto_layout=True, nets=...)`.

Specific to `oaslananka/kicad-mcp-pro`. Keep in sync with
`docs/tools-reference.generated.md`. Worked reference:
[`examples/gallery/esp32-c3-wroom-02-breakout`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/examples/gallery/esp32-c3-wroom-02-breakout/README.md).

## Default for new functional schematics

For an ordinary MCU development board, agree the circuit and group components by
function before choosing coordinates: power input/regulator and capacitors,
MCU/decoupling, EN/RESET and BOOT networks, UART/GPIO interfaces, and indicator
LEDs. Keep short connections within each block visibly wired; use matched labels
for long inter-block connections and breakouts. Choose the smallest page that fits
content, readable spacing and headings; do not enlarge the page to hide scattered
placement. Keep component Value (for example `10k`) separate from net/function
names (for example `EN`). Adapt the blocks to the actual design; do not impose
ESP32 coordinates or add circuitry that was not requested.

For an existing design, preserve its intent and approved layout. Do not relocate already-wired symbols independently.
Use previewable connectivity-preserving changes only; compare the netlist or
connectivity signature and reference identities before and after. Refuse or roll
back a change that alters connectivity or cannot be verified. A collision-safe
label-only build remains an explicit fallback when placement or wiring cannot be
verified, not a claim of professional readability.

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
5. **Refine** placement for overlaps and composition; rebuild only the approved
   new design. Complete only when native ERC, connectivity and rendered functional
   block readability pass independently. If native rendering is unavailable,
   report visual acceptance as unverified; a high cosmetic score is not a substitute.

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
