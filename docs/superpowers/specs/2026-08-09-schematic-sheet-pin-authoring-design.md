# Schematic Sheet-Pin Authoring Design

Status 2026-08-09. Upstream of this spec: `docs/superpowers/2026-08-09-kicad-mcp-sheet-pins-pr.md`
(research). This spec fixes behavior, interfaces, and acceptance.

## 1. Problem

A hierarchical KiCad schematic never reaches clean ERC headlessly with
`kicad-mcp-pro`. Hierarchical labels in a child sheet need matching sheet pins
on the parent sheet symbol -- none of the registered tools write them. Until
now the only way out was the GUI command "Import Sheet Pins".

Worse: the project already **diagnoses the failure itself**. The
`schematic_connectivity_gate` compares each child sheet's hierarchical labels
against its sheet symbol's pins in `tools/validation.py` and reports "Hierarchy
contract mismatch ... top missing ...". Only the tool to fix the reported state
was missing.

The capability already exists underneath: `kicad-sch-api` (already pinned at
`>=0.5.0,<0.6`) has `SheetManager.add_sheet_pin()`, `remove_sheet_pin()`,
`list_sheet_pins()`, and full serialization (`_sheet_pin_to_sexp`).
`add_sheet()` takes a `sheet_pins` parameter the MCP server never forwarded.
**No new dependency needed.**

Upstream, the gap was unreported: no open or closed issue and no PR for "sheet
pin" / "sheet_pin" / "hier_label_mismatch", no hit in the `src/` tree.

## 2. Scope

Four changes to the tool surface:

| Tool | Kind | Purpose |
|---|---|---|
| `sch_import_sheet_pins` | write | child sheet's labels -> pins on the parent symbol |
| `sch_add_sheet_pin` | write | one pin, full manual control |
| `sch_list_sheet_pins` | read | per-sheet verification |
| `sch_create_sheet` | write | `sheet_pins` parameter forwarded |

Explicitly **out of scope**: wiring sheet symbols to each other, moving
`sch_create_sheet` onto the guarded write path, deleting orphaned pins.

## 3. Architecture

### 3.0 Why this does not write through kicad-sch-api

The first draft of this spec wanted to write through
`utils/schematic_roundtrip.roundtrip_edit()` -- load, mutate, save, verify node
counts. A trial against a real fixture ruled that out:

1. **Silent loss of the title block.** A plain load/save cycle of
   `main.kicad_sch` is node-count clean (no lost UUID, all node counts equal),
   but drops `(comment 1 ...)` and `(comment 2 ...)` from the `title_block`,
   and `(show_name no)` / `(do_not_autoplace no)` from the sheet properties.
   The guard in `roundtrip_edit` counts `symbol`, `wire`, `sheet`, and related
   nodes -- **`comment` is not on the list**, so the loss would pass silently.
2. **The round trip is not the project's write path.** `roundtrip_edit` is
   used by no production tool, only by its own tests. Every write tool,
   including `sch_add_hierarchical_label`, goes through `transactional_write`:
   deterministic text mutation, no reparse.
3. **On real child sheets, `save()` refuses to serve.** `main_02_mcu.kicad_sch`
   produces 10 validation errors of the form "Invalid reference format:
   `#PWR042a0301`" -- logged in `HANDOFF.md` as harmless leftover cosmetics.
   Irrelevant to this import (only the root sheet is written), but evidence of
   how brittle the path is.

Consequence: writes go through `transactional_write`; reads use the same text.
**kicad-sch-api is not needed for this feature** -- neither to read nor to
write. That also makes it testable without KiCad and without the library.

Findings 1 and 2 belong as a footnote in the upstream issue: a guard that does
not count `comment` invites false confidence.

### 3.1 `schematic/sheet_pins.py` (new, pure)

No I/O, no `kicad_sch_api` imports, no FastMCP -- text in, text or data out.
Listed in `scripts/check_architecture_boundaries.py` under `DOMAIN_MODULES`
**and** `PURE_HELPERS`.

The as-built record type is a frozen dataclass, not a bare tuple, because a
caller needs to verify what the writer actually placed -- not merely that it
placed *something*:

```python
@dataclass(frozen=True)
class SheetPinRecord:
    """One existing ``(pin ...)`` node of a sheet block, as parsed from text."""
    name: str
    pin_type: str          # input | output | bidirectional | tri_state | passive
    x_mm: float
    y_mm: float
    rotation: int
    uuid: str

@dataclass(frozen=True)
class SheetBlock:
    name: str
    filename: str
    origin: tuple[float, float]
    size: tuple[float, float]
    pins: tuple[SheetPinRecord, ...]
    start: int                              # character index of "(sheet" in the root text
    end: int                                # index past the closing parenthesis
    size_span: tuple[int, int]              # character span of the sheet's own (size w h) node
    pin_spans: tuple[tuple[int, int], ...]  # whole-line spans of the existing (pin ...) blocks
    instances_start: int | None             # anchor new pins go before

@dataclass(frozen=True)
class SheetPinPlacement:
    name: str
    pin_type: str
    edge: str               # left | right (plan_sheet_pins) or all four (placement_on_edge)
    x_mm: float
    y_mm: float
    rotation: int            # left -> 180, right -> 0 (and 90/270 for top/bottom)
    justify: str
    uuid: str                 # existing UUID, or "" for a new pin the caller must stamp
    action: str                # "add" | "retype" | "keep"

@dataclass(frozen=True)
class SheetPinPlan:
    placements: tuple[SheetPinPlacement, ...]
    size: tuple[float, float]      # possibly grown, never shrunk
    orphans: tuple[str, ...]
    conflicts: tuple[str, ...]
    overflow: tuple[str, ...]
    notes: tuple[str, ...]

def parse_hierarchical_labels(text: str) -> tuple[tuple[str, str], ...]: ...
def parse_sheet_blocks(text: str) -> tuple[SheetBlock, ...]: ...

def plan_sheet_pins(
    labels: Sequence[tuple[str, str]],          # (name, shape), in file order
    sheet: SheetBlock,
    *,
    grid_mm: float,
    pitch_mm: float = 2.54,
    margin_mm: float = 2.54,
    text_height_mm: float = 1.27,
    grow_sheet: bool = True,
) -> SheetPinPlan: ...

def placement_on_edge(
    sheet: SheetBlock, name: str, pin_type: str, edge: str,
    position_along_edge: float, uuid: str,
) -> SheetPinPlacement: ...

def sheet_pin_block(placement: SheetPinPlacement, indent: str = "\t\t") -> str: ...
def apply_plan(text: str, sheet: SheetBlock, plan: SheetPinPlan) -> str: ...
def insert_pin(text: str, sheet: SheetBlock, placement: SheetPinPlacement) -> str: ...
```

`plan_sheet_pins` computes absolute coordinates directly, not
`position_along_edge` -- the detour through kicad-sch-api's edge semantics is
unnecessary because the module writes the `(at x y rot)` line itself. The
library's own edge table is still the reference for rotation and
justification: `right` -> 0 deg, `left` -> 180 deg (and 90/270 for `top` /
`bottom`, used by `placement_on_edge`).

`apply_plan` replaces the `(size w h)` line inside the `(sheet ...)` block,
removes every existing `(pin ...)` block, and inserts the new ones before the
`(instances` node -- the same insertion point
`tests/integration/test_schematic_connectivity_gate.py` used to reach by hand
before this feature existed.

The splice itself is guarded by a private `_check_non_overlapping` helper that
`apply_plan` and `insert_pin` both go through via `_splice`: replaying edits in
descending order of `start` is only safe if the spans are pairwise
non-overlapping, and a `(pin ...)` node sharing a physical source line with
`(instances ...)` or `(size ...)` would violate that. When it happens, the
module raises a named `ValueError` instead of silently corrupting the
schematic.

### 3.2 `schematic/hierarchy_authoring.py` (extended)

`SchematicHierarchyAuthoringService` gains `add_sheet_pin()` and
`import_sheet_pins()`, composed from injected helpers like the rest of the
class. New injected helpers:

- `read_text(path) -> str` -- read a child sheet's file contents
- `grid_mm() -> float` -- bound to `SCHEMATIC_GRID_MM`
- `new_uuid() -> str` -- already exists in the composition root

Writes go through the existing `transactional_write` protocol the class
already has injected. Its guard `_guard_schematic_structural_loss` applies as
before; `(pin ...)` is not on its node list, so rearranging existing pins does
not trip it. The title block is never touched.

**Write-time geometry guard.** Both `import_sheet_pins` and `add_sheet_pin`
read a sheet's `origin` and `size` once, plan against that snapshot, and then
re-read the sheet inside the write's mutator immediately before splicing. If
`origin` or `size` differ from what was read -- the sheet moved or was resized
by something else between the read and the write -- the mutator raises
`ValueError` and the transaction aborts with a message naming the old and new
values, rather than splicing coordinates computed against stale geometry.
`sch_create_sheet`'s own `_apply_sheet_pins` helper (below) carries the same
guard.

`create_sheet` does not apply `sheet_pins` inline; it delegates to a private
`_apply_sheet_pins(name, top_schematic_path, sheet_pins)` helper, called only
after the sheet itself is created and saved. This is a second, independent
write on top of that one, through the same text splice `import_sheet_pins`
uses -- never through `kicad_sch_api.add_sheet()`'s own `sheet_pins` argument,
whose load/save round trip silently drops `(comment N ...)` nodes from the
title block (Section 3.0). `_apply_sheet_pins` never raises: a failure here is
folded into the returned string, so the sheet stays reported as created even
if its pins could not be written.

### 3.3 `schematic/topology.py` (extended)

`list_sheet_pins(schematic_file, sheet_name)` -- read-only. Reports, per pin,
its name, type, edge (derived from its rotation via `edge_for_rotation`, or
omitted if the rotation is not one KiCad itself writes), and `(x_mm, y_mm)`
position, followed by the sheet symbol's own origin and size.

### 3.4 Adapter, registry, models

- `tools/schematic_hierarchy_authoring.py`: two `@mcp.tool()` wrappers
  (`sch_add_sheet_pin`, `sch_import_sheet_pins`), `sheet_pins` added to
  `sch_create_sheet`
- `tools/schematic_topology.py`: `sch_list_sheet_pins`
- `models/schematic.py`: `SheetPinInput`, `ImportSheetPinsInput`,
  `ListSheetPinsInput`; `CreateSheetInput` extended with `sheet_pins`
- `tools/schematic.py` (composition root): injects the new helpers
- `tools/router.py`: the three new names added to the schematic category
- `tools/metadata.py`: annotations. `import_` counts as a write prefix,
  `list_` as a read prefix -- the automatic classification applies without
  changes.

## 4. Behavior of `sch_import_sheet_pins`

```
sch_import_sheet_pins(
    sheet: str | None = None,      # None = every child sheet
    grow_sheet: bool = True,
    dry_run: bool = False,
) -> str
```

**Source of truth** is the child sheet: every `hierarchical_label` in it,
deduplicated by name. `shape` maps 1:1 to `pin_type`; the vocabulary is
`input | output | bidirectional | tri_state | passive` in both places.

**Edge assignment:** `input` -> left edge, everything else -> right edge.
Within an edge, alphabetical by name, 2.54 mm pitch, 2.54 mm margin top and
bottom. This reads as a block diagram with flow from left to right.

**Full re-layout.** The import always re-lays-out *all* pins of the sheet,
including ones that already existed and orphans -- not only the newly added
ones. This is not a convenience, it is necessary: for `edge="left"`,
kicad-sch-api's `position_along_edge` measures from the **bottom edge**
(`y = sheet_y + height - pos`). If the sheet height grows, every left pin whose
offset is left untouched would shift. Only one deterministic overall layout is
internally consistent -- and it is what makes a second run a true no-op,
because the same input produces the same layout. Anyone who hand-placed pins
and wants to keep them uses `sch_add_sheet_pin` instead of the import.

**Growth** (`grow_sheet=True`): height grows to fit the fuller edge, rounded up
to a multiple of the schematic grid. Width grows only if the estimated text
width of both columns would collide; the estimate `0.6 x text height x
character count` is a **heuristic** and is named as such in the docstring and
in the output. The sheet symbol never shrinks and is never moved.

With `grow_sheet=False` the size stays fixed. Pins that then no longer fit
their edge land in `SheetPinPlan.overflow`; for that sheet **nothing at all**
is written, and the report names the affected pins and the height that would
be required. A half-pinned sheet would be worse than an unchanged one.

**Grid alignment:** the *absolute* pin position is snapped to the schematic
grid (`SCHEMATIC_GRID_MM`, default 1.27 mm), and `position_along_edge` is
computed back from that. Without this, pins would sit between grid points and
no wire would snap to them. If the sheet origin itself is off-grid, the x
position of edge pins cannot be corrected without moving the sheet -- that is
reported as a note, pointing at `sch_align_to_grid`.

**Idempotent, non-destructive:**

| Case | Behavior |
|---|---|
| Pin missing | create it |
| Pin exists, type matches | name and UUID kept, position follows the re-layout |
| Pin exists, type differs | type is aligned to the child label, reported |
| Pin without a matching label | **not** deleted; reported as an orphan and still laid out |
| One name, multiple `shape`s in the child sheet | first occurrence wins, conflict reported |

Existing pins keep their UUID: `parse_sheet_blocks` reads it, and
`sheet_pin_block` writes it back. KiCad references these UUIDs nowhere, but
stable IDs keep the git diff small and reviewable -- at 81 pins that is the
difference between a reviewable and an unreviewable commit.

A second run with no changes to the child sheet produces the same plan, does
not change the file, and reports only "keep".

`dry_run=True` produces the same report and writes nothing.

## 5. Behavior of `sch_add_sheet_pin`

```
sch_add_sheet_pin(
    sheet: str,
    name: str,
    pin_type: str = "input",
    edge: str = "left",            # left | right | top | bottom
    position_along_edge: float = 2.54,
) -> str
```

A thin wrapper around `placement_on_edge()`, all four edges, no automation.
This is the escape hatch for anyone the auto-layout does not suit. Edge
semantics as documented by kicad-sch-api (clockwise from the right; `left`
measures from the bottom, `right` from the top).

## 6. Error handling

- Missing sheet, unknown `pin_type`, unknown `edge` -> descriptive message, no
  write
- Child sheet file missing or unreadable -> that sheet is skipped and listed
  as blocked in the report; the remaining sheets still run
- Sheet block without an `(instances` node or without `(size` -> sheet is
  skipped and reported instead of splicing at the wrong place
- Sheet moved or resized since it was read -> the write-time geometry guard
  (Section 3.2) aborts the transaction and reports old vs. new origin/size
- Node loss on write -> `transactional_write` rolls back and raises
  `SchematicWriteUnsafeError`

`sch_import_sheet_pins` writes every touched sheet in **one**
`transactional_write`: either all changes land in the file, or none do.

## 7. Tests

| File | Content |
|---|---|
| `tests/unit/test_sheet_pins_parsing.py` | `parse_hierarchical_labels`, `parse_sheet_blocks`, table-driven |
| `tests/unit/test_sheet_pins_planning.py` | edge assignment, sort order, growth in height and width, grid snap, `grow_sheet=False`, orphans, shape conflicts, UUID preservation, idempotence at plan level |
| `tests/unit/test_sheet_pins_emission.py` | `sheet_pin_block`, `apply_plan`, `insert_pin`, `_check_non_overlapping` |
| `tests/unit/test_schematic_hierarchy_authoring_service.py` | fakes for the new helpers; `dry_run` writes nothing; exactly one `transactional_write` for all sheets; report text; the write-time geometry guard |
| `tests/unit/test_schematic_hierarchy_authoring_registration.py` | new tools registered, input validation |
| `tests/unit/test_schematic_hierarchy_authoring_architecture.py` | `sheet_pins` in `DOMAIN_MODULES` and `PURE_HELPERS`, `register()` under the line limit |
| `tests/unit/test_schematic_topology_sheet_pins.py` | `sch_list_sheet_pins` |
| `tests/integration/test_schematic_sheet_pin_import.py` | real mini-hierarchy fixture: import through the actual `sch_import_sheet_pins` tool, then **read** the result back with `kicad_sch_api` and check the pins -- the evidence that our text is what KiCad's own data model expects. Also: the `title_block` is unchanged character for character |

`tests/integration/test_schematic_connectivity_gate.py` used to splice sheet
pins into the file by hand through `_inject_sheet_pin()`. That helper now
calls `sch_import_sheet_pins` internally instead -- so the test now shows that
the gate's reported state is not just diagnosable but also fixable, through
the same tool a user would run.

`pnpm run docs:tools` and `pnpm run metadata:check` must be regenerated,
otherwise the drift tests fire. `task ci` before the PR.

## 8. Acceptance on the reference case

`hardware/transmitter/pcb/main`: 7 sheets, 36 sheet-crossing nets, 85
hierarchical labels with **81 distinct names** -- exactly the number of
reported `hier_label_mismatch`.

Procedure per `HANDOFF.md`: export the netlist on a copy before and after,
diff net names and pin assignments, plus ERC counts.

Starting point (150 ERC messages, 132 nets):

| Count | Type |
|---|---|
| 81 | `hier_label_mismatch` |
| 61 | `isolated_pin_label` |
| 7 | `pin_not_driven` |
| 1 | `pin_to_pin` (U501 exposed pad, intentional) |

Acceptance criteria:

1. `hier_label_mismatch` = 0
2. `isolated_pin_label` and `pin_not_driven` drop sharply
3. The previously duplicated nets merge: `/02_mcu/I2S_BCLK` and
   `/05_audio/I2S_BCLK` become one net containing both U301.28 **and** U501.16
4. No component and no net is lost; the net count drops only where
   same-named sheet nets merge
5. `02_mcu` gets 17 pins on the left and 18 on the right and grows from
   20.32 to 48.26 mm in height; the sheet row at y = 90.17 stays clear
6. A second run is a no-op
7. `main.kicad_sch`'s `title_block` is byte-for-byte unchanged; `comment 1`
   and `comment 2` are still present

Only after this is verified against a copy is the same run applied to the
real board and committed to OpenDriveHub. After that, step 1 in
`hardware/transmitter/pcb/main/HANDOFF.md` no longer applies.

## 9. Upstream path

1. Feature-request issue following the project's own template: the problem,
   the tool-surface gap, the note that `schematic_connectivity_gate` already
   reports it, the reference-case numbers
2. Fork, branch `feat/schematic-sheet-pins`, Conventional Commits with DCO
   `Signed-off-by: Peter Buchegger <peter.buchegger7@gmail.com>`
3. PR with `Closes #N`, before/after numbers as test evidence, spec and plan
   under `docs/superpowers/` following the project's convention

Work happens against the cloned source, not against the wheel in the uv cache.
