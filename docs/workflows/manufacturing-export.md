# Manufacturing Export

This is the end-to-end path from a routed board to a gated, signed-off release
package — including sourcing, part validation, and the manufacturing sign-off.
Each step lists the tool to call and what a good result looks like.

## 1. Source real, sourceable parts

Search a live distributor catalog. `jlcsearch` needs no credentials; `nexar`,
`digikey`, and `mouser` use credentials loaded from `.env` at server startup
(`NEXAR_CLIENT_ID`/`NEXAR_CLIENT_SECRET`, `DIGIKEY_CLIENT_ID`/`DIGIKEY_CLIENT_SECRET`,
`MOUSER_API_KEY`).

```text
lib_search_components(keyword="STM32F103C8T6", source="digikey", min_stock=1000)
```

Expected: one line per match with `MPN | package | stock | unit price | basic/extended`,
and — when the provider reports it — `lifecycle` and `RoHS`. Prefer in-stock,
lifecycle-`Active`, RoHS-compliant parts. If a credentialed source is unconfigured
the tool says so and you can fall back to `source="jlcsearch"`.

## 2. Check derating and approved-vendor compliance

Before committing a part, confirm it is operated within its derating limit and is
from an approved vendor.

```text
lib_check_derating(kind="capacitor", parameter="voltage",
                   rated_value=25.0, operating_value=12.0,
                   manufacturer="Murata", approved_vendors=["Murata", "TDK"])
```

Expected: `Part sourcing compliance: PASS` with a derating line (utilization vs the
limit) and an AVL line. A part over its derating limit or off the approved-vendor
list returns `FAIL`. Derating factors are conservative general practice, not a
named MIL/IPC mandate — the verdict says so.

## 3. Validate footprints against IPC-7351B

For chip passives, confirm the land pattern matches the IPC-7351B nominal (a hard
gate — gross deviation blocks).

```text
lib_validate_footprint_ipc7351(footprint_path="footprints/C_0805.kicad_mod",
                               size_code="0805", density="B")
```

Expected: `Footprint IPC-7351B validation: PASS`. `FAIL` lists the per-dimension
deviation (pad width/height/pitch vs nominal). Scope is chip passives (0201–2512)
against the IPC standard nominal, not a datasheet-specific land pattern.

## 4. When editing an existing board: scope the re-validation

After changing an existing project, do not re-run everything blindly. Assess which
gates the change can affect.

```text
project_assess_edit_impact()
```

Expected: an `Edit-impact analysis` listing each semantic change and `Gates to
re-run:` vs `Gates preserved:`. Re-run only the impacted gates; the preserved ones
stay proven.

## 5. Run the full quality gate

```text
project_quality_gate()
```

Expected: `PASS`. If not, stop and fix the reported blocking issues, then re-run.
`pcb_transfer_quality_gate()` confirms named schematic pad nets survived sync; run
`run_drc()` / `run_erc()` for detailed reports.

## 6. Produce the manufacturing sign-off

Bind every declared design-intent requirement to a passing check, with provenance.

```text
project_signoff_report()
```

Expected: `Manufacturing sign-off: PASS` with each requirement bound to its backing
gate(s), the checks, and provenance (engine versions, rule profile, intent and
content hashes). A board with **no declared intent** is `UNVERIFIED`, not a silent
PASS — declare requirements with `project_set_design_intent()` first.

## 7. Gated release

`export_manufacturing_package()` is the final step and is hard-gated on the same
project gate, so it runs only once the gate is clean **and** a project-local human
approval evidence JSON file is supplied via `approval_evidence_path`. That file must
include `approved_by`, `approved_at_utc`, and `approval_scope`. The export writes a
`manufacturing_release_report.json` that links the approval evidence, quality-gate
outcomes, exported Gerber/drill/BOM/PnP/IPC artifacts, file sizes, and SHA256 hashes.
Direct `export_*()` tools do not enforce the full gate or approval evidence — use
them only for low-level debug or interchange artifacts, switching to a broader
profile (`full`/`minimal`) if needed. Finish with `mfg_generate_release_manifest()`
for the SHA256-signed, provenance-stamped manifest.
