# High-Speed Review Workflow

This workflow uses only MCP tools and headless-safe checks where possible. It is
intended as a preflight before a human layout review, not as a replacement for
field solving or lab validation.

## 1. Set the Project and Intent

Start by setting the active KiCad project, then record the nets and frequencies
that deserve stricter routing and EMC checks:

```text
kicad_set_project(project_dir="/path/to/project")
project_set_design_intent(
  critical_nets=["USB_DP", "USB_DN", "PCIE_TX_P", "PCIE_TX_N"],
  critical_frequencies_mhz=[5000.0, 8000.0],
  thermal_hotspots=["U1", "U7"]
)
```

The `critical_nets` list is reused by placement scoring, EMC return-path checks,
and the high-speed review loop.

## 2. Check Stackup and Time-Domain Routing

Use `pcb_get_stackup` to confirm dielectric and copper data, then run
`route_tune_time_domain` for timing-critical nets. On KiCad 10 projects the tool
derives required length from per-layer dielectric data. If no usable stackup
context is available, it uses the legacy length-based fallback; that fallback is
not a support guarantee for dropped KiCad lines.

```text
route_tune_time_domain(
  net_name="USB_DP",
  target_delay_ps=250.0,
  layer="F_Cu",
  tolerance_pct=5.0
)
```

## 3. Review Via Stubs

`si_check_via_stub` now reports the quarter-wave resonant frequency for each
stub and flags any stub within 10 percent of a frequency listed in
`critical_frequencies_mhz`.

```text
si_check_via_stub(net_name="PCIE_TX_P", max_stub_mm=0.8, dielectric_constant=4.0)
```

Treat a `CRITICAL resonance near ... MHz` line as a routing-review escalation:
backdrill, use blind/buried vias, shorten the stub, or move the layer transition.

## 4. Score Placement Before Routing

Run `pcb_score_placement` after coarse placement. The score includes a
critical-net Manhattan length proxy and thermal-hotspot proximity signal, so it
can catch long high-speed detours and clustered hot parts before routing starts.

## 5. Route and Inspect FreeRouting Telemetry

When a DSN is available, `route_autoroute_freerouting` prefers Docker with the
pinned `ghcr.io/freerouting/freerouting:2.1.0` image and falls back to the JAR
runner. The result includes routed percentage, total nets, unrouted nets, pass
count, wall time, SES path, and the last 4 KB of router output.

```text
route_autoroute_freerouting(
  dsn_path="output/routing/board.dsn",
  max_passes=100,
  threads=8,
  exclude_nets=["GND", "SHIELD"],
  drc_report_path="output/routing/freerouting.drc.json"
)
```

## 6. Run PI and EMC Preflight

For power and thermal risk, use `pdn_calculate_voltage_drop`,
`pdn_check_copper_weight`, and `thermal_calculate_via_count`. The thermal via
tool accepts both the legacy `power_w` mode and the package-envelope mode:

```text
thermal_calculate_via_count(
  package_power_w=2.0,
  ambient_c=35.0,
  max_junction_c=95.0,
  theta_ja_deg_c_w=60.0,
  via_diameter_mm=0.3
)
```

For EMC, call `emc_check_return_path_continuity` without a signal name to sweep
the design-intent critical nets automatically:

```text
emc_check_return_path_continuity(reference_plane_layer="auto", search_radius_mm=2.0)
```

Any reported violation includes a simple geometry hint (`net=..., radius=...mm`)
so an agent can propose stitching vias or plane-continuity edits.

## 7. Commit a Checkpoint

If the board is improving, create a reversible checkpoint before the next
iteration:

```text
vcs_commit_checkpoint(message="High-speed preflight pass")
```

Keep manual SI/PI simulation and lab validation in the loop for final release.
