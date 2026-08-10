# Root Sheet-Symbol Wiring Design

Status 2026-08-10. Continuation of `2026-08-09-schematic-sheet-pin-authoring-design.md`
(merged as oaslananka/kicad-mcp-pro#626, straggler in #632).

## 1. Problem

Sheet pins alone do not make two sheets one net electrically. In KiCad, a
sheet pin joins a child sheet's hierarchical label to a point on the parent
sheet symbol -- nothing more. For a net to cross the sheet boundary, something
in the **parent** sheet has to connect the pins. Matching names are not
enough, unlike global labels.

That was the bug in Section 8 of the previous spec, and it is fixed there.
This is the missing second step.

Reference case `hardware/transmitter/pcb/main` after the pin import
(measured, kicad-cli 10.0.5): ERC 77, of which 61 `isolated_pin_label`, 8
`pin_not_connected`, 7 `pin_not_driven`, 1 intentional `pin_to_pin`. 36
distinct net names across 81 sheet pins, **every name on >=2 sheets**, no
orphans. `02_mcu` touches 35 of the 36 -- the topology is a star.

## 2. The approach: labels, not wires

Connecting 36 nets across 7 sheet symbols with wires would be a routing
problem with crossings -- and the `kicad-hardware` skill warns that crossing
wires merge geometrically in KiCad and produce silent shorts. Scripted, that
is a dead end.

The standard way out is the **stub-then-label idiom**: a short wire stub
outward from every sheet pin, ending in a **local label** carrying the pin's
name. Same-named local labels on one sheet are one net. No wire has to route
around a sheet symbol, nothing crosses, and the result is deterministic.

Side effect, deliberately accepted: the net is then named `/I2S_BCLK` instead
of `/02_mcu/I2S_BCLK` -- a root-named net instead of two sheet-local ones.
That is the intended state, but it does change net names in exports.

## 3. Two tools, not one

Wiring needs room for the labels; making room means moving sheet symbols.
Those are two jobs. Folding them into one was an Important Finding on the
previous PR -- here they are separated from the start.

### 3.1 `sch_spread_sheets(min_gap_mm=None, margin_mm=2.54, dry_run=False)`

Groups sheet symbols into columns by overlapping x-span and shifts columns
right until every neighboring gap is wide enough. Both the sheet's own origin
**and** every one of its pins move.

The requirement is derived from the names that actually **face each other**,
not from the longest name in the document:

```
required = 2 * stub + text_width(longest right-edge name in the left column)
                     + text_width(longest left-edge name in the right column)
                     + margin_mm
```

`text_width` is the well-known heuristic `0.6 x text height x character
count`, and is named as such. `margin_mm` exists because the estimate is an
estimate; without a margin, noise decides the outcome. `min_gap_mm` overrides
the derivation for anyone who wants a fixed spacing.

Shifts round up to the grid. Sheets never shrink, never move left, and their
y position is never touched.

**Safety rule:** a sheet with a wire already ending on one of its pins is
**not** moved -- it is reported instead, since moving it would silently
disconnect that wire. This is why the order matters: spread first, then wire.

**Page edge:** the paper size is read from the `(paper "...")` node. The
usable edge is the paper width minus **10 mm** -- a deliberately conservative
figure, because KiCad's frame and title block occupy space on the right whose
exact width depends on the worksheet settings. Widths: A4 297, A3 420, A2 594,
A1 841, A0 1189, A 279.4, B 431.8, C 558.8, D 863.6, E 1117.6 mm (landscape;
`(paper "A4" portrait)` swaps the values). An unrecognized paper size is not a
reason to abort: the check is skipped and named as skipped in the report,
rather than inventing a wrong limit.

If a column would move past that edge, the tool aborts and reports how much
it is short by. It never pushes anything off the paper.

### 3.2 `sch_wire_sheet_pins(sheet=None, stub_mm=2.54, dry_run=False)`

One stub outward per sheet pin, with a local label carrying the pin's name at
the outer end.

| Pin rotation | Edge | Stub | Label alignment |
|---|---|---|---|
| 0 | right | rightward | left (text points outward) |
| 180 | left | leftward | right |
| 90 | top | upward (y decreases) | rotation 90, justify left |
| 270 | bottom | downward (y increases) | rotation 90, justify right |

Rotation follows the same edge table `_EDGE_GEOMETRY` already carries in the
pin module; justification always points away from the sheet. The importer
only ever places pins on the left and right edge; top and bottom only arise
through `sch_add_sheet_pin` -- they are handled anyway, so a hand-placed pin
never comes out unwired.

All coordinates snap to the schematic grid. `sheet=None` processes every
sheet symbol.

**Non-destructive and idempotent:**

| Case | Behavior |
|---|---|
| Pin without a wire | create stub + label |
| Pin already ending a wire | skip, report as unchanged |
| Existing wire or existing label | never deleted, never moved |

A second run with nothing to change writes nothing.

**What is reported instead of swallowed:**

- names that occur on only **one** sheet symbol -- their label would dangle
  (in the reference case: zero)
- label pairs whose text would overlap, with the missing amount and a pointer
  to `sch_spread_sheets`
- that the text width is estimated, not measured

## 4. Architecture

The same seams as the pin import.

**New: `schematic/sheet_wiring.py`** -- pure, standard library only, listed in
`DOMAIN_MODULES` and `PURE_HELPERS`. Holds column grouping, the gap
calculation, move planning, and the stub/label geometry.

**Reused from the merged state:** `parse_sheet_blocks`, `SheetPinRecord`
(name, type, x, y, rotation, UUID), `edge_for_rotation`, the
parenthesis-and-string-safe `_block_end`, `_splice` with its two guards,
`_format_mm`.

**Written through** `transactional_write`, like everything else. Wires and
labels are top-level nodes, not inside the sheet block -- they are inserted
before `(sheet_instances`, the same anchor `sch_add_hierarchical_label`
already uses. The existing `wire_block` and `label_block` builders in the
composition root produce those blocks. `sch_spread_sheets`, by contrast,
mutates sheet blocks and uses the same splice as the pin import.

**kicad-sch-api is not used for writing** -- same reason as before: its
round trip drops `(comment ...)` from the title block.

### 4.1 What changed from the plan during implementation

Each of the following was a divergence caught in review, not something
foreseen when this spec was first drafted:

- **`SheetBlock` gained `at_span` and `pin_at_spans`.** The design as first
  imagined did not anticipate needing this: `sch_spread_sheets` moves a sheet
  by rewriting exactly one `(at x y)` node -- the sheet's own -- plus one
  `(at x y rot)` node per pin, and nothing else about the block. That is only
  possible because the parser now carries the character span of each of those
  nodes alongside the parsed value. Every other byte of the sheet and its
  pins (styling, UUIDs, pin order) survives a move untouched.
- **The stub's start is the pin's exact, unsnapped position.** KiCad connects
  wires and pins only on exact coordinate equality; snapping `x1`/`y1` to the
  grid would move the stub's start off the pin itself and leave it touching
  nothing. Only the far end is snapped, and only along the stub's own axis
  (`dx` or `dy` is always zero, never both) -- the perpendicular coordinate is
  copied straight from the pin, so the stub cannot go diagonal even when the
  pin itself sits off-grid.
- **An off-grid pin produces a note pointing at `sch_align_to_grid`**, rather
  than silently emitting a diagonal stub or refusing to wire the pin at all.
- **The heuristic disclosure is carried on every return path** that hands out
  a heuristic-derived number, including the page-overflow path in
  `plan_spread`. The overflow figure is itself computed from `right_edge_mm`,
  which was derived from the estimated text width whenever a shift came from
  the heuristic rather than an explicit `min_gap_mm` -- so the rejected
  (overflow) plan discloses the heuristic just as the accepted one does.
- **Collision detection is exhaustive pairwise within a row**
  (`itertools.combinations`, not a left-to-right sweep), because a wide label
  that swallows two narrower, mutually non-overlapping ones needs both pairs
  reported, and a three-label chain overlapping A-B, B-C, and A-C needs all
  three -- a running-maximum sweep misses A-C once C's span exceeds B's. It
  reports the **true intersection width** (`hi - lo` of the overlapping
  spans), not the difference between label extents. It does **not** examine
  vertical (top/bottom-edge) labels: this module's own placement rule never
  produces one -- only hand-editing a pin's rotation does -- and judging a
  vertical label's text-flow direction correctly under a 90-degree rotation
  plus KiCad's justify convention is not something this function can verify
  without a live render. Reporting a guess would be worse than reporting
  nothing; `plan_sheet_wiring` discloses the gap once in its notes whenever
  any vertical label is present, so it is never silently unhandled.
- **`check_edits_non_overlapping` is shared** between `_splice` (the pin
  import's own guard) and the document-wide spread in `spread_sheets` --
  the same precondition applies to both: replaying edits in descending
  `start` order is only safe if the spans are pairwise non-overlapping.
- **A pin whose `(at ...)` cannot be read is skipped and reported, never
  rewritten.** `parse_sheet_blocks` represents an unparseable pin position as
  a zero-length span (`pin_start == pin_end`) rather than raising. Inserting
  text at a zero-width span would add a spurious `(at ...)` node beside the
  pin instead of replacing one, producing malformed output -- `spread_sheets`
  checks for this explicitly, leaves that pin in place, and reports it by
  name, telling the caller to open the file in KiCad and save it once.

## 5. Error handling

- unknown sheet, sheet without an addressable block -> descriptive message,
  no write
- page edge exceeded -> abort with the missing amount
- a sheet blocked from moving -> reported, the remaining columns still run
- node loss on write -> `transactional_write` rolls back

All sheets in **one** `transactional_write`: either everything, or nothing.

## 6. Tests

| File | Content |
|---|---|
| `tests/unit/test_sheet_wiring_spread.py` | column grouping, gap requirement from facing names, the margin, grid rounding, page-edge abort, move refusal when a pin is already wired, heuristic disclosure on both the accepted and the overflow path |
| `tests/unit/test_sheet_wiring_stubs.py` | stub and label per edge, grid snapping (start unsnapped, far end snapped only along its axis), detection of already-wired pins, orphan and collision reporting, the true-intersection-width collision measure, vertical-label disclosure, plan stability across repeated runs |
| `tests/unit/test_schematic_hierarchy_authoring_service.py` | one write for all sheets, `dry_run` writes nothing, report text |
| `tests/unit/test_schematic_hierarchy_authoring_registration.py` | both tools registered, input validation |
| `tests/integration/test_schematic_root_sheet_wiring.py` | fixture spread -> wire -> read back with `kicad_sch_api`; title block byte-for-byte unchanged |

## 7. Acceptance on the reference case

This is the measurement that had to fail against the pin import, because that
checked the wrong step.

Starting point after the import: ERC 77, 132 named nets, 107 components.

1. `pin_not_connected` 8 -> 0
2. `/02_mcu/I2S_BCLK` and `/05_audio/I2S_BCLK` become **one** net containing
   both U301.28 **and** U501.16
3. The count of named nets drops by exactly the number of merged duplicate
   occurrences
4. `isolated_pin_label` -- measured, not predicted. A sharp drop is expected;
   the number is recorded after the measurement, not before
5. No component lost, `title_block` byte-for-byte unchanged
6. A second run of both tools is a no-op
7. **The root sheet is rendered and looked at.** The `kicad-hardware` skill
   requires this explicitly, and it was skipped during the pin import. 81
   labels in 19 mm gaps is exactly the case where a number can "fit" and the
   picture is still unreadable

## 8. Measured starting point on spacing

With `stub = 2.54 mm` and the text-width heuristic:

| Gap | present | required (no margin) | driving pair |
|---|---|---|---|
| 05_audio -> 06_joystick | 19.05 | 18.03 | `I2C1_SDA` \| `TOUCH_INT` |
| 06_joystick -> 03_display | 19.05 | 18.80 | `SPI2_MOSI` \| `SPI2_MOSI` |
| 03_display -> 04_i2c | 20.32 | 18.03 | `TOUCH_INT` \| `I2C0_SCL` |

Without the margin there would be nothing to do -- the middle gap would have
0.25 mm of slack, which is within the estimate's error. With `margin_mm =
2.54`, exactly that one gap widens by one grid step. Paper is **A4** (297 mm
wide); the sheets end at x = 210.82, and the reserve to the right is ample.

## 9. Afterward

Once this is done, the main board's schematic is electrically complete and
`HANDOFF.md` loses its last GUI step. Both tools go up as their own PR -- the
continuation of #626: first the server could not write the pins, then it
could not connect them.
