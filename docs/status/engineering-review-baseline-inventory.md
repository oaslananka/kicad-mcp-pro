# Engineering Review & Baseline Control Inventory (T0)

Date: 2026-11-03
Milestone: M18 — Engineering Review & Visual Quality
Issue: [#1578](https://github.com/oaslananka/kicad-mcp-pro/issues/1578) (T0 — Baseline Inventory)
Branch: `audit/review-baseline-inventory-1578`
Reproduction Suite: [`tests/unit/test_engineering_review_baseline_false_pass.py`](file:///home/amd/Desktop/OPS_WORKSPACE/GITHUB/oaslananka/kicad-mcp-pro/tests/unit/test_engineering_review_baseline_false_pass.py)

---

## Executive Summary

This inventory maps all existing engineering controls, validation gates, critics, and review mechanisms across `kicad-mcp-pro`. In accordance with milestone M18 principles:
1. A tool name, rule name, report field, or checklist item is not proof that its underlying physical condition is verified.
2. Incomplete coverage, missing inputs, unsupported geometry, or stale evidence must be reported honestly (`NOT_ASSESSED` or `BLOCKED`) and must never silently adapt to `PASS`.
3. Readability and aesthetic style preferences are distinct from electrical correctness and manufacturing compliance.

### Classification Taxonomy
- `existing_verified`: Evaluated directly by an authoritative engine (native KiCad CLI, exact S-expression parser with real coordinates, or complete mathematical formula).
- `existing_bounded`: Evaluated with explicit, documented 2D or nominal limits; does not claim full 3D, physics, or fab approval.
- `integration_gap`: Check exists or is claimed, but contains a bypass, missing net binding, missing pin coordinate, or keyword-presence proxy.
- `new_check`: Proposed or declared in rules/docs/milestones but not currently implemented.
- `external_review`: Requires external specialist review, physical lab test, or human signoff.

---

## 1. Verified False-PASS Reproductions

Six suspected false-PASS paths were statically identified and reproduced deterministically in [`test_engineering_review_baseline_false_pass.py`](file:///home/amd/Desktop/OPS_WORKSPACE/GITHUB/oaslananka/kicad-mcp-pro/tests/unit/test_engineering_review_baseline_false_pass.py):

| # | Suspected Path | Owning Service / Function | Real Mechanism | Reproduction Status |
|---|---|---|---|---|
| 1 | Generic 90° corner treated as electrical defect | `src/kicad_mcp/tools/validation.py`<br>`_evaluate_route_corner_style_gate()` | Fails release gate unconditionally (`max_90_degree_corners=0`) even for low-speed DC or non-SI tracks where modern fabs have no issue. | **Reproduced** (`test_reproduce_generic_90_degree_style_treated_as_electrical_defect`) |
| 2 | Workflow completed metadata treated as evidence | `src/kicad_mcp/tools/project_workflow.py`<br>`build_design_workflow()` | Caller passes a list of phase names as strings; service marks them `COMPLETE` without evaluating ERC/DRC/evidence. | **Reproduced** (`test_reproduce_workflow_completed_metadata_treated_as_evidence`) |
| 3 | File/keyword presence treated as insulation review | `src/kicad_mcp/manufacturing/release_evidence.py`<br>`_evaluate_hv_safety_gate()` | Scans `*.kicad_dru` for substring `"clearance"`. Any default clearance rule passes a 230V hazardous mains safety check. | **Reproduced** (`test_reproduce_hv_safety_keyword_presence_treated_as_insulation_review`) |
| 4 | Near but wrong-net capacitor | `src/kicad_mcp/tools/emc_compliance.py`<br>`_nearest_cap_distance_mm()` | Searches for any footprint starting with `"C"` within `max_distance_mm` of IC origin; completely ignores net connectivity (e.g. +12V cap passes for +3.3V IC). | **Reproduced** (`test_reproduce_near_wrong_net_capacitor_passes_decoupling`) |
| 5 | Missing power pin falling back to footprint centre | `src/kicad_mcp/tools/signal_integrity_decoupling_placement.py`<br>`_find_power_anchor()` | If named `power_pin` is not found on pads of `ic_ref`, it silently returns `point_xy_mm(footprint.position)` rather than raising or returning `NOT_ASSESSED`. | **Reproduced** (`test_reproduce_missing_power_pin_fallback_to_footprint_centre`) |
| 6 | Empty or unsupported results becoming PASS | `src/kicad_mcp/models/visual_qa.py`<br>`run_cosmetic_qa()` | A blank schematic with 0 symbols and 0 wires returns `status="PASS"` and `cosmetic_score >= 95.0` because penalty loop has 0 findings. | **Reproduced** (`test_reproduce_empty_schematic_cosmetic_score_passes_without_circuit`) |

---

## 2. Control-to-Source-to-Input-to-Method-to-Evidence Map

### Domain 1: Native ERC & DRC (Schematic & Layout Core)
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `run_erc` | `tools/schematic.py`<br>`validation/` | `.kicad_sch` active file, KiCad CLI in `PATH` | Native KiCad CLI `kicad-cli sch erc --format json` execution. | Full schematic hierarchy | Returns error payload if CLI missing or file unreadable. | Tied to `.kicad_sch` hash and KiCad CLI version. | Blocks `schematic_quality_gate` on ERC errors. | `existing_verified` | `test_cli_erc_runner.py` |
| `run_drc` | `tools/validation.py`<br>`validation/drc_runner.py` | `.kicad_pcb` active file, KiCad CLI in `PATH` | Native KiCad CLI `kicad-cli pcb drc --format json` execution. | Full PCB geometry (copper, courtyard, edge) | Classifies into `success`, `has_violations`, `unavailable`, `malformed`. | Tied to `.kicad_pcb` hash and KiCad CLI version. | Blocks `pcb_quality_gate` on DRC violations. | `existing_verified` | `test_drc_runner.py` |
| `drc_list_rules`, `drc_rule_create`, `drc_validate_exclusions` | `tools/validation.py` | `.kicad_dru` custom rules file | Custom S-expression parser/writer for `.kicad_dru`. | KiCad DRC rule AST | Returns empty list if no `.kicad_dru` file exists. | Tied to `.kicad_dru` hash. | Modifies DRC severity and exclusions. | `existing_bounded` | `test_drc_rules.py` |

### Domain 2: Schematic Connectivity & Hierarchy
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `schematic_connectivity_gate` | `tools/validation.py` | `.kicad_sch` AST | Scans pin-to-wire coordinate coincidence, global/hierarchical labels. | 2D schematic sheet | Returns BLOCKED if schematic unreadable; passes if no open pins found. | Tied to `.kicad_sch` hash. | Part of `project_quality_gate`. | `existing_verified` | `test_schematic_connectivity.py` |
| `sch_analyze_net_compilation` | `tools/schematic_circuit_compilation.py` | `.kicad_sch` text, sheets | In-memory netlist compilation and endpoint grouping. | S-expression schematic AST | Returns empty netlist if sheet empty. | In-memory only; no persisted evidence record. | Advisory for compiler/transfer. | `existing_bounded` | `test_schematic_compilation.py` |
| `validate_footprints_vs_schematic` | `tools/schematic_transfer.py` | Schematic symbol refs, PCB footprint refs | Set intersection and difference between schematic references and PCB footprint references. | Component references | Returns missing footprint list. | Tied to schematic and board hashes. | Blocks transfer gate. | `existing_verified` | `test_schematic_transfer.py` |

### Domain 3: Schematic Cosmetics & Visual QA
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `sch_cosmetic_score`, `run_cosmetic_qa` | `tools/schematic_cosmetics.py`<br>`models/visual_qa.py` | `.kicad_sch` text | Headless S-expression geometry parser: checks label collisions, symbol body/text overlap, dense fanout, grid alignment, diagonal wires, font consistency, power symbol orientation. | Bounding boxes of symbols, labels, wires | **False-PASS gap:** Blank schematic returns 97/100 and PASS. | In-memory score; no freshness hash. | Advisory (used in visual QA loop). | `integration_gap` | `test_visual_qa.py`, `test_cosmetics_gate.py` |
| `sch_snap_to_grid`, `sch_straighten_wires`, `sch_normalize_fonts` | `tools/schematic_cosmetics.py` | `.kicad_sch` file | Coordinate-independent connectivity signature comparison before/after mutation. Refuses write if connectivity changes. | Coordinate alignment (0.5 mm wire, 0.01 mm font) | Refuses mutation and preserves original file on failure. | Writes mutation checkpoint for visual diff. | Fixer action (Phase B). | `existing_verified` | `test_schematic_cosmetics.py` |

### Domain 4: PCB Placement & Clustering
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `pcb_placement_quality_gate` | `tools/validation.py` | `.kicad_pcb` footprints and Edge.Cuts | Checks footprint bounding boxes for mutual overlaps, checks if footprints lie outside board frame. | Courtyard bounding rectangles | If board frame is unparseable, marks BLOCKED. | Tied to `.kicad_pcb` hash. | Blocks `project_quality_gate`. | `existing_bounded` | `test_gate_logic.py` |
| `pcb_score_placement` | `tools/validation.py` | `.kicad_pcb`, `DesignIntent` | Deductive score starting from 100 based on keepout, cluster, proximity, and thermal penalties. | 2D bounding boxes and centroids | Empty board or board with no intent gets 100/100 score. | No evidence record. | Advisory score. | `existing_bounded` | `test_placement_scoring.py` |

### Domain 5: Connector Mating & Alignment (#1393)
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `evaluate_connector_mating` | `project/connector_mating_review.py` | `ConnectorMatingSpec`, PCB footprints, Edge.Cuts frame | Calculates transformed mating datum (offset + rotation), normal vector angle relative to edge normal, distance to perimeter. | Rectangular Edge.Cuts outline only | Fails closed if outline is non-rectangular, missing position, or wrong layer. | In-memory check against intent spec. | Proposed gate integration in T6 (#1393). | `existing_bounded` | `test_connector_mating_review.py` |
| `_evaluate_connectors` (legacy placement) | `tools/validation.py` | `intent.connector_refs`, footprints, Edge.Cuts frame | Measures euclidean distance from footprint centroid to nearest edge: `distance <= 5.0 mm`. | Distance to infinite edge lines | If `intent.connector_refs` is empty, check is skipped (0 checked, 0 violations). | In-memory. | Blocks `pcb_placement_quality_gate`. | `integration_gap` | `test_gate_logic.py` |

### Domain 6: Decoupling & Critical Placement
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `emc_check_decoupling_placement` | `tools/emc_compliance.py` | Board footprints | Nearest footprint starting with `"C"` to footprint starting with `"U"`. | Euclidean distance between centroids | **False-PASS gap:** Ignores net connectivity; unrelated rail cap passes check. | In-memory. | Critic verdict (WARN/PASS). | `integration_gap` | `test_emc_compliance.py` |
| `si_calculate_decoupling_placement` | `signal_integrity/decoupling_placement.py` | `ic_ref`, `power_pin`, `target_freq_mhz` | Compares nearest capacitor distance against recommended $\lambda/10$ or quarter-wave limit. | Pad coordinate to footprint centroid | **False-PASS gap:** Non-existent `power_pin` silently returns IC centroid. | In-memory text output. | Informational / critic. | `integration_gap` | `test_si_gate_verdicts.py` |
| `_evaluate_decoupling` (validation.py) | `tools/validation.py` | `intent.decoupling_pairs`, IC/Cap pad positions | Matches same-supply-net power pad to decoupling capacitor pad (excluding GND/VSS). | 2D pad coordinates | If no power pads found, reports warning and falls back to cap centroid. | Part of placement analysis. | Penalizes placement score. | `existing_bounded` | `test_gate_logic.py` |

### Domain 7: Routing Style & Geometry
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `pcb_route_corner_style_gate` | `tools/validation.py` | `.kicad_pcb` track segments | Finds two segments meeting at $90^\circ \pm 5^\circ$ with length $\ge 0.25$ mm. | Linear track segments on same net/layer | **False-FAIL gap:** Fails release gate unconditionally on any 90° corner without checking whether project policy allows it. | In-memory. | Bundled into `project_professional_release_gate`. | `integration_gap` | `test_professional_quality_gates.py` |
| `pcb_stackup_consistency_gate` | `tools/validation.py` | `.kicad_pcb` layer table & stackup | Compares layer count in layer table with copper layers defined in stackup block. | S-expression board header | Returns BLOCKED if PCB unreadable. | In-memory. | Blocks release gate. | `existing_verified` | `test_professional_quality_gates.py` |

### Domain 8: High-Speed & Signal Integrity
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `si_calculate_trace_impedance` | `signal_integrity/impedance.py` | Trace width, height, dielectric $E_r$, thickness | Quasi-static IPC-2141 microstrip & stripline analytical equations. | Microstrip and symmetric stripline | Returns error if input parameters are non-physical ($w \le 0$, $h \le 0$). | Analytical formula; no solver required. | Informational / design aid. | `existing_bounded` | `test_signal_integrity.py` |
| `si_check_differential_pair_skew` | `signal_integrity/differential_pair_skew.py` | Positive & negative track lengths, dielectric $E_r$ | $\Delta L = \lvert L_p - L_n \rvert$, $\Delta t = \Delta L \cdot \frac{\sqrt{E_r}}{c}$. | Routed track lengths | Returns WARN if nets are not both routed. | Analytical calculation. | Informational / critic. | `existing_bounded` | `test_signal_integrity.py` |
| `si_check_via_stub` | `signal_integrity/via_stub.py` | Via layer span, board thickness, signal layers, $E_r$ | Stub length $h = \text{total} - \text{routed}$, $f_0 = \frac{c}{4 h \sqrt{E_r}}$. | Through-hole via geometry | Flags stubs resonant within 10% of declared critical frequency. | Analytical calculation. | Informational / critic. | `existing_bounded` | `test_signal_integrity.py` |
| `si_get_solver_capabilities` | `signal_integrity/solver_capabilities.py` | System environment | Reports available solver backends (analytical built-in; FEM/FDTD unavailable). | System probe | Accurately returns `available: false` for full-wave 3D solvers. | System state. | Prevents fake solver claims. | `existing_verified` | `test_signal_integrity.py` |

### Domain 9: Power Integrity & Thermal
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `check_power_integrity` | `power_integrity/voltage_drop.py` | Net name, load current, track length & width, copper weight | DC resistance $R = \rho \frac{L}{A}$, voltage drop $\Delta V = I \cdot R$. | Rectangular track segments | Returns WARN if net not routed or current not specified. | Analytical Ohm's law. | Critic verdict. | `existing_bounded` | `test_power_integrity.py` |
| `pdn_check_copper_weight` | `power_integrity/copper_weight.py` | Trace width, copper thickness, target current | IPC-2152 current-carrying capacity for $\Delta T = 10^\circ\text{C}$ rise. | Single surface/internal track | Returns recommendation based on empirical tables. | Analytical empirical model. | Informational. | `existing_bounded` | `test_power_integrity.py` |
| `thermal_check_copper_pour` | `tools/power_integrity_thermal_pour.py` | Net name, board zones | Scans board for filled copper zone associated with net. | Filled polygon zones | Returns WARN if no pour found for designated thermal net. | S-expression inspection. | Critic verdict. | `existing_verified` | `test_power_integrity.py` |

### Domain 10: High-Voltage, Safety & Creepage
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `_evaluate_hv_safety_gate` | `manufacturing/release_evidence.py` | Project dir, `is_hv`, `voltage_v`, domain | **False-PASS gap:** Scans `*.kicad_dru` for substring `"clearance"` or `"creepage"`. | File text search | Passes if word `"clearance"` appears anywhere in `.dru`. | Releases gate on string presence. | Blocks manufacturing release. | `integration_gap` | `test_manufacturing_release_evidence_service.py` |
| `pcb_check_creepage_clearance` | `tools/pcb.py` | Pad positions and spacing | Measures pairwise pad distances against IEC-60664 heuristic lookup table. | 2D pad positions | Fails if $< 2$ pads on different nets. | Analytical heuristic. | Critic verdict. | `existing_bounded` | `test_pcb_gate_net_diagnostics.py` |

### Domain 11: DFM & Manufacturing Readiness
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `dfm_run_manufacturer_check` | `tools/dfm.py` | Active DFM profile (e.g. JLCPCB standard), board metrics, DRC report | Compares track widths, drill sizes, via diameters, clearances against manufacturer profile. | Circular drills, rectangular tracks | Returns WARN for manual inspection items (annular ring, copper-to-edge). | Profile JSON resource. | Returns `VerdictReport`. | `existing_bounded` | `test_dfm.py` |
| `audit_pth_annular_ring_lines` | `tools/pth_annular_audit.py` | Board text, minimum ring (mm) | Calculates nominal circular annular ring: $\frac{\min(x,y) - \text{hole}}{2} - \text{offset}$. | Circular PTH lands only | Non-circular pads and slots count as unmeasured; explicitly never claims PASS. | Bounded S-expression scan. | Flags nominal violations. | `existing_bounded` | `test_pth_annular_audit.py` |
| `manufacturing_cpl_rotation` | `tools/manufacturing_cpl_rotation.py` | Footprint lib ID, PCB rotation | Applies EIA-481 / manufacturer standard rotation offsets for pick-and-place files. | SMD components | Returns 0 offset if component not in normalization table. | Lookup table. | Applied during CPL generation. | `existing_bounded` | `test_manufacturing_cpl.py` |

### Domain 12: BOM & Component Sourcing
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `lib_check_sourcing_policy` | `tools/library_sourcing.py` | Part number, manufacturer, lifecycle | Validates lifecycle status (active vs obsolete), minimum stock thresholds, distributor availability. | Supplier API data / local cache | Returns BLOCKED if external supplier API is offline or unauthenticated. | Caches responses with TTL. | Sourcing gate. | `existing_bounded` | `test_library_sourcing.py` |
| `find_component_contract` | `models/component_contracts.py`<br>`models/contract_verifier.py` | Component lib ID / ref | Verifies pin net groups against required seeds (e.g. ESP32-S3 GND + 3V3). | Schematic net connections | Returns None if part has no contract seed in registry. | Pure domain contract. | Advisory / verification. | `existing_verified` | `test_component_contracts.py` |

### Domain 13: Hardware Intent & Engineering Graph
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `HardwareIntentContract` | `project/hardware_intent_contract.py` | Intent JSON/YAML | Validates typed constraints: power rails, critical nets, diff pairs, interfaces, connector specs. | Typed Pydantic models | Strict validation (extra fields forbidden, finite numbers required). | Versioned schema (v1). | Foundation for downstream gates. | `existing_verified` | `test_hardware_intent_contract.py` |
| `EngineeringGraph` | `ir/engineering_graph.py` | IR / S-expressions | Graph of entities (Project, Component, Pin, Net) with typed edges (`CONTAINS`, `CONNECTS_TO`). | Graph topology | Returns empty graph on empty design. | SHA-256 entity hashing. | Core dependency model for T1–T10. | `existing_verified` | `test_engineering_graph.py` |
| `EvidenceFreshnessService` | `project/evidence_freshness.py` | Evidence record, entity inputs, current graph | Calculates exact input digests; transitions between `STILL_VALID`, `REQUIRES_RECHECK`, `INVALIDATED`. | Graph entity hashes | Missing input hashes or unknown mutation scope always produces `REQUIRES_RECHECK`. | Authoritative hash checking. | Governs evidence acceptance. | `existing_verified` | `test_evidence_freshness.py` |

### Domain 14: Workflow, Release Policy & Audit
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `ReleaseApprovalAuditHistory` | `project/release_approval_audit.py` | SQLite DB (`release_approval_history-v1.db`), immutable events | Merkle-linked append-only audit trail: `approval` or `waiver` bound to exact evidence SHA-256. | Hash chain ($H_n = \text{SHA256}(H_{n-1} + \dots)$) | Database integrity verified on open; tampering detected. | Immutable SQLite DB. | Authoritative release authority. | `existing_verified` | `test_release_evidence_store.py` |
| `project_design_workflow` | `project/workflow.py`<br>`tools/project_workflow.py` | `completed_phases: list[str]` | **False-PASS gap:** Marks phases as `COMPLETE` based on user-provided string array without gate verification. | N/A | If empty, returns initial stage as READY. | In-memory string matching. | Visual roadmap. | `integration_gap` | `test_workflow.py` |
| `project_quality_gate` | `tools/validation.py` | Schematic, PCB, DFM, parity gate results | Evaluates bundle: `schematic_quality_gate`, `pcb_quality_gate`, `manufacturing_quality_gate`. | All board & sch domains | Returns `VerdictReport`. If any child fails, returns `FAIL`. | Aggregates child gate verdicts. | Primary human/agent gate. | `existing_verified` | `test_gate_logic.py` |

### Domain 15: External Analysis & Simulation Evidence
| Control / Tool | Owning Module | Inputs & Required Context | Actual Method & Operation | Supported Geometry | Empty / Error Behavior | Evidence & Freshness | Gate Effect | Classification | Existing Tests |
|---|---|---|---|---|---|---|---|---|---|
| `sim_validate_spice_setup` | `tools/simulation.py` | SPICE library paths, schematic models | Checks SPICE model file existence and readable syntax. | File system / AST | Returns BLOCKED if SPICE models missing or ngspice missing. | File path check. | Simulation gate. | `existing_bounded` | `test_simulation.py` |
| External analysis import (T8) | `tools/` (downstream in #1585) | External simulation report files (touchstone, CSV, JSON) | Proposed: bounded, schema-validated file import with provenance and hash validation. | Touchstone, tabular | Reject foreign board or stale revision reports. | Input file hash + solver version. | Evidence attachment. | `new_check` | Planned in #1585 |

---

## 3. Related Issues & PR Mapping (No Duplicate Work)

| Task / Domain | Issue | Scope Boundary | Existing Work to Reuse |
|---|---|---|---|
| **T0 (Envanter)** | [#1578](https://github.com/oaslananka/kicad-mcp-pro/issues/1578) | Map all existing controls, evidence, methods, and false-PASS paths. | This document and [`test_engineering_review_baseline_false_pass.py`](file:///home/amd/Desktop/OPS_WORKSPACE/GITHUB/oaslananka/kicad-mcp-pro/tests/unit/test_engineering_review_baseline_false_pass.py). |
| **T1 (Model)** | [#1579](https://github.com/oaslananka/kicad-mcp-pro/issues/1579) | Versioned `ReviewRule`, `ReviewContext`, `ReviewAssessment`, `ReviewCoverage`. | Extends `src/kicad_mcp/models/verdict.py` and `intent.py`; pure domain logic. |
| **T2 (Tazelik)** | [#1580](https://github.com/oaslananka/kicad-mcp-pro/issues/1580) | Bind coverage and freshness to workflow decisions; prevent fake PASS. | Uses `project/evidence_freshness.py` and `project/release_approval_audit.py`. |
| **T3 (Routing)** | [#1581](https://github.com/oaslananka/kicad-mcp-pro/issues/1581) | Separate routing style policy from electrical defects. | Reuses `_route_90_degree_corners()`; does not replace #1394 path planning. |
| **T4 (Yerleşim)** | [#1582](https://github.com/oaslananka/kicad-mcp-pro/issues/1582) | Net- and pin-aware decoupling and placement verification. | Reuses `_matching_supply_pad_distance()` and `EngineeringGraph` topology. |
| **T5 (Kozmetik)** | [#1583](https://github.com/oaslananka/kicad-mcp-pro/issues/1583) | Safe visual QA and schematic/PCB readability review. | Reuses `models/visual_qa.py` and `schematic_cosmetics.py` invariant guards. |
| **T6 (Mekanik)** | [#1393](https://github.com/oaslananka/kicad-mcp-pro/issues/1393) | Connector mating direction and board-edge alignment. | Reuses `project/connector_mating_review.py`; avoids duplicating #1393. |
| **T7 (Elektrik)** | [#1584](https://github.com/oaslananka/kicad-mcp-pro/issues/1584) | Derating, voltage drop, power budgets, thermal boundary contracts. | Connects existing analytical formulas to explicit requirements. |
| **T8 (Dış Delil)** | [#1585](https://github.com/oaslananka/kicad-mcp-pro/issues/1585) | Safe local file import of external solver reports. | Downstream of #947 (SolverProvider v1); safe ingestion first. |
| **T9 (DFM/BOM)** | [#1586](https://github.com/oaslananka/kicad-mcp-pro/issues/1586) | Versioned fabricator profiles, assembly polarity, BOM alternates. | Reuses `tools/dfm.py`, `pth_annular_audit.py`, `manufacturing_cpl_rotation.py`. |
| **T10 (Raporlama)**| [#1587](https://github.com/oaslananka/kicad-mcp-pro/issues/1587) | Integrated reporting across project reports and agent skills. | Integrates incrementally with T1–T9; updates canonical skills. |
| **Epic** | [#1588](https://github.com/oaslananka/kicad-mcp-pro/issues/1588) | Milestone container and exit criteria tracking. | Closes after all tasks satisfy acceptance criteria. |

---

## 4. Acceptance Checklist Verification

- [x] **Every in-scope control classified**: `existing_verified`, `existing_bounded`, `integration_gap`, `new_check`, `external_review` across 15 domains.
- [x] **Real implementation and authoritative inputs named**: owning module, input parameters, calculation/native operations documented.
- [x] **Method, outputs, freshness/evidence and gate effect recorded**: exact mechanism, geometry support, and gate consequences cataloged.
- [x] **Unknown, unsupported, empty and unavailable cases explicit**: behavior on empty inputs, missing tools, and unsupported primitives identified.
- [x] **Existing issues/PRs mapped**: #1393, #1394, #1381, #729, #730, #1214, #944, #1141, #947 linked to avoid duplicate work.
- [x] **Six suspected false-PASS paths reproduced**: backed by automated unit tests in `tests/unit/test_engineering_review_baseline_false_pass.py`.
