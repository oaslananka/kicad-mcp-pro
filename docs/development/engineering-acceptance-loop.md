# Evidence-first electronics engineering acceptance loop (v1)

This document applies to **new and partially completed KiCad projects**. It
extends existing project design specs, validators and native PCB transactions; it
is not a new agent framework or an autonomous manufacturer approval authority.

## 1. Engineering contract before irreversible layout

The existing project-specific `.kicad-mcp/project_spec.json` is the source of
explicit design intent. Retain design spec requirements for power rails,
interfaces, mechanical constraints, decoupling and manufacturer; the separately
versioned `HardwareIntentContract` remains the authoritative requirements /
verification / evidence format where applicable. Neither model nor intent is
itself test evidence.

For each **mechanically accessible edge connector**, declare explicit
`mechanical.connector_mating` entries *only after checking the actual footprint
and vendor drawing*. The bounded first version supports **single rectangular
Edge.Cuts boards with front-side footprints**. Missing/unsupported geometry
fails the explicit mating review rather than returning a speculative pass.

Example: GCT USB4085, where the KiCad footprint's local `PCB Edge` marker is
at `(2.975, 6.1)` mm and its local outward mouth direction is `bottom`.
These numbers describe **the specific footprint**, not a generic USB-C socket.
Verify the orientation against the datasheet and the physical plug opening.

```json
{
  "mechanical": {
    "connector_mating": [
      {
        "ref": "J1",
        "footprint_id": "Connector_USB:USB_C_Receptacle_GCT_USB4085",
        "edge": "left",
        "datum_x_mm": 2.975,
        "datum_y_mm": 6.1,
        "normal_local": "bottom",
        "max_datum_error_mm": 0.5,
        "datum_component_tolerance_mm": 0.1,
        "board_edge_tolerance_mm": 0.2,
        "max_direction_error_deg": 10
      }
    ]
  }
}
```

Supply this as the `mechanical` argument to the existing
`project_set_design_intent` MCP call. Do not overwrite unrelated mechanical
constraints when updating a project; the field is deliberately inside the
existing contract. A missing connector-mating entry means **not assessed**, not
physically approved. On declared connectors, `pcb_placement_quality_gate`
checks the transformed footprint datum and mating direction, reports hard
failures, and **does not rotate, move or edit the board**.

A passing v1 check is limited to **2-D mating-datum alignment**. It does *not*
validate connector 3D models, plug/wire/screwdriver swept volumes, enclosure
openings, thermal clearances, PCB-stackup impedance, electrical correctness,
actual assembly compatibility or release readiness. These stay explicit open
risks and require independent checks. Complex Edge.Cuts geometry and B.Cu
mirrored connectors must not silently pass the v1 validator.

## 2. Stage order, conditional on project state

- **Inspect:** identify source revision and file hashes, ERC/DRC baseline,
  existing decisions, approved BOM/footprints, open issues and unknown facts.
- **Specify:** check actual datasheets, power budget, I/O voltage compatibility,
  mechanical edge requirements, manufacturing capabilities and required evidence.
- **Mechanical before detailed routing:** footprint origin/rotation, mating
  direction, courtyard, enclosure, ESD placement, mounting and access.
- **Electrical before cosmetic:** functional nets, decoupling loops, current
  carrying capacity, USB/RS-485 signal classes, proper GND return, then style.
- **Verify:** schema/net parity, KiCad ERC/DRC, relevant geometry, independent
  power/SI/DFM checks; record actual assertions and evidence provenance.
- **Prototype:** acceptance does not mean manufacturing approval; physical and
  electrical validation belong to their own release/human-controlled process.

If a previously approved footprint is wrong, repair the mechanical design in
an isolated copy **before** routing the remaining netlist around it. Progress
in number of traces or airwires is never a substitute for valid layout.

## 3. Safe edits reuse the existing transaction lifecycle

Use the existing native `pcb_begin_commit` → reviewed mutations →
`pcb_push_commit` (or `pcb_drop_commit` on failure), with the documented native
IPC semantics and original file hash. When using an isolated source-backed
preview instead, compare pre/post ERC/DRC and only apply an independently
accepted plan. Always refill copper zones and independently re-read the *saved*
board after edits. Use `pcb_revert` **only when safe to discard all unrelated
unsaved changes**; it is not a scoped rollback tool.

A lost connection during a mutation produces an **unknown state**, not proof of
no write: check saved hash, session, transaction status and journal before retry.
Do not weaken clearance/DRC/DFM thresholds to improve apparent success.

### 2-D datum tolerance budget (not manufacturing acceptance)

For a supplier-documented component datum tolerance and a fabricator's
board-edge profile tolerance, supply **both** optional nonnegative fields
`datum_component_tolerance_mm` and `board_edge_tolerance_mm`. Once either is
present, the other becomes mandatory. The reviewer conservatively requires
`nominal datum-to-edge distance + component tolerance + board-edge tolerance`
not to exceed `max_datum_error_mm`. For example, **0.400 + 0.100 + 0.200 =
0.700 mm**, so a 0.500-mm 2-D limit correctly fails even if the nominal check
passes. Omission of both preserves the legacy **nominal-only** result; it
**does not mean unspecified tolerances are zero or manufacturing-approved**.

The budget excludes PCB placement/solder variation, manufacturer-qualified
native STEP mating registration, housing/cable/ferrule/tool swept volume,
connector torque support and enclosure tolerances. Those still require
separate, explicit evidence and written manufacturing signoff. Never infer
full mechanical PASS solely from this 2-D tool.

## 4. Small tests on every relevant change; full benchmark selectively

The mechanically meaningful micro-regression suite is:

```bash
python -m pytest -q tests/unit/test_connector_mating_engineering_contract.py \
  tests/integration/test_connector_mating_quality_gate.py
```

It covers wrong USB-C orientation despite board-edge proximity, correct 270°
datum alignment, other cardinal angles, missing/mismatched footprint, unknown
nonrectangular board outlines, old design-spec deserialization and actual MCP
spec/gate interaction. Existing native PCB transaction lifecycle tests run
independently. CI discovers these files with the repository's other pytest
suites automatically; a separate long-running benchmark service is unnecessary.

For source changes run the repository pre-push and quality checks. Full real
KiCad + scored end-to-end design attempts are reserved for relevant release or
architecture milestones. The STM32F072 fixture is **unscored**,
keeps 25 native unconnected items and 28 J1 intrinsic clearance issues as of
2026-10-21, and is **not** a production-ready card.

## 5. Continuous improvement from safe evidence

When a reviewer finds a failure, capture: relevant requirement ID, source and
board hash, redacted object refs/geometry, before/after findings, minimal
reproduction and candidate regression test. Route the defect to **design
intent**, **MCP implementation**, **model decision**, **manufacturing limitation**
or **unknown**, rather than categorizing every changed rotation as a model bug.

A separate development agent may propose a fix and test in an isolated branch.
The modifying agent must not approve its own weakened acceptance criteria;
reviews, CI, hardware validation and human-controlled manufacturing remain
separate. Users opt in before any raw commercial designs, screenshots or logs
leave their authorized project environment. Do not send design files as default
telemetry.

Related: mechanical acceptance #1393, routing #1394, existing placement
quality issue #1380, USB4085 DFM blocker #1381, real benchmark #1214.
