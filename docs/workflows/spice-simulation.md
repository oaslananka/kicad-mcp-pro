# SPICE Simulation

Use this workflow to simulate the active saved schematic with ngspice, without
exporting a netlist by hand. Every analysis tool accepts an empty
`netlist_path`; when it is omitted, the server exports a SPICE netlist from the
active `.kicad_sch` and runs that. Pass `netlist_path` only to simulate a
pre-existing `.cir` deck instead.

## Goal

Produce a trustworthy first-pass result from the schematic the agent just built:

- a DC operating point from the saved schematic;
- a transient time-series for wiring-level plots;
- an AC sweep or stability estimate for feedback loops.

## Prerequisites

Simulation is a `simulation` / `experimental` profile surface and needs an
ngspice executable. Discovery checks, in order, a configured path, `ngspice` on
`PATH`, then the KiCad-bundled installs:

- `KICAD_MCP_NGSPICE_CLI` (explicit path, wins when set);
- Windows: `C:\Program Files\KiCad\10.0\bin\ngspice.exe` (and 9.0);
- Linux: `/usr/bin/ngspice`, `/usr/local/bin/ngspice`;
- macOS: `/Applications/KiCad/KiCad.app/Contents/MacOS/ngspice`.

When nothing resolves, the tool raises an actionable error telling you to install
KiCad/ngspice or set `KICAD_MCP_NGSPICE_CLI`. See
[troubleshooting](../troubleshooting.md) if discovery misses your install.

## 1. Build a simulatable schematic

Author the source and passives with `sch_build_circuit()` in one pass. The KiCad
`Simulation_SPICE` library supplies the SPICE source symbols; pass its library
name and the exact `symbol_name` KiCad shows (for example a `VDC` DC source for
an operating point, or a sine source for a transient). The `Device` library
supplies `R`, `C`, and `L` passives. Give every source and passive a real numeric
`value` (for example `value="1k"`); the exported netlist writes it verbatim, and
a missing or symbolic value makes the deck unrunnable.

Wires and labels carry connectivity. `probe_nets` names, the `source_ref` of a
DC sweep, and the `output_net`/`feedback_net` of a stability check all refer to
those net names.

```text
sch_build_circuit(
  symbols=[
    {"library": "Simulation_SPICE", "symbol_name": "VDC",
     "x_mm": 50.8, "y_mm": 63.5, "reference": "V1", "value": "5"},
    {"library": "Device", "symbol_name": "R",
     "x_mm": 76.2, "y_mm": 63.5, "reference": "R1", "value": "1k"},
    {"library": "Device", "symbol_name": "C",
     "x_mm": 101.6, "y_mm": 63.5, "reference": "C1", "value": "100n"}
  ],
  wires=[...],
  labels=[{"name": "IN", ...}, {"name": "OUT", ...}]
)
```

## 2. Run the operating point

Call `sim_run_operating_point()` with no `netlist_path`. The empty path triggers
the automatic export from the saved schematic. Pass `probe_nets` to limit the
reported nodes.

```text
sim_run_operating_point(probe_nets=["IN", "OUT"])
```

The result names the backend and netlist, then lists each scalar trace and its
final value:

```text
Operating point analysis (ngspice-cli):
- Netlist: output/simulation/simulation_input.cir
- Log: output/simulation/...
- Data: output/simulation/...
- Scalars: 2
Values:
- in: 5
- out: 2.49999
```

## 3. Run a transient and read the time series

`sim_run_transient(stop_time_s, step_time_s, probe_nets)` takes the stop time
and step in seconds, plus the nets to record. Both are required; `probe_nets`
and `netlist_path` are optional.

```text
sim_run_transient(stop_time_s=0.005, step_time_s=1e-6, probe_nets=["OUT"])
```

The result header names the backend, netlist, log, data, and raw paths. The
body reports the sample count, the time range, and each waveform's first and
last value. Reuse those files for plotting:

- `data_path` holds the numeric rows ngspice emitted;
- `raw_path` holds the raw binary deck;
- `log_path` holds the simulator log.

```text
Transient analysis (ngspice-cli):
- Netlist: output/simulation/simulation_input.cir
- Data: output/simulation/...
- Samples: 5001
- time: 0 -> 0.005
Waveforms:
- out: 0 -> 4.99997
```

## 4. Sweep AC, DC, or check a loop

The same empty-`netlist_path` rule applies to the rest of the family:

- `sim_run_ac_analysis(start_freq_hz, stop_freq_hz, points_per_decade=20, probe_nets=[...])`;
- `sim_run_dc_sweep(source_ref, start_v, stop_v, step_v, probe_nets=[...])`;
- `sim_check_stability(output_net, feedback_net, start_freq_hz=10, stop_freq_hz=1.0e7)`.

`sim_run_ac_analysis()`, `sim_run_dc_sweep()`, and `sim_check_stability()`
responses add a frequency or sweep range and per-trace magnitude/phase. At a
unity-gain crossover, `sim_check_stability()` reports the crossover frequency,
the loop phase there, and an estimated phase margin.

## Safety boundaries

- Treat simulation results as evidence for review, not as fabrication or
  release sign-off; ERC/DRC and the manufacturing gates still decide release.
- Do not state a transient, operating point, or stability claim without the
  actual returned result; a failed run reports an error instead of a value.
- Keep probe nets, source references, and loop nets equal to real schematic net
  names, or the analysis returns no matching trace.

## Follow-up workflows

- [Schematic to PCB](schematic-to-pcb.md) once the circuit behaves as intended;
- [Manufacturing Export](manufacturing-export.md) only after ERC/DRC/DFM review
  and human approval.
