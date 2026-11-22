# MCU authoring regression

`wroom32e.json` preserves the original small, deterministic schematic plan and
its intended pin connections. `wroom32e_regulator_gpio.json` is a second
independent authoring case: a 5V input connector and PWR_FLAG, AMS1117-3.3
regulator with input/output capacitors, 3.3V MCU rail, GND, and an additional
two-pin GPIO breakout. The new plan splits the 5V and 3.3V wires at each
branch/junction: a visual wire crossing a pin without a segment endpoint is
not a KiCad electrical connection. Power symbols and PWR_FLAG are spaced away
from the connector to avoid obscuring reference/value text. It uses installed KiCad 10 symbol libraries rather than
vendoring library files. The integration test builds both wired and label-only
schematics through the existing MCP tools, adds the intentional unused pin
markers, checks native ERC/SVG, and compares all net memberships and component
reference/value/footprint tuples. In both fixtures the wired and label-only
variants must produce an identical native netlist; the second case adds 38
expected nets and 15 physical components. On a native KiCad 10.0.8 Windows
check, both new variants passed ERC with zero errors/warnings and exported
native SVG and XML without modifying the schematic sources. It is not an autonomous-agent prompt trial or
hardware validation.

To run with a native KiCad 10 installation, set `KICAD_WIRED_NATIVE_SYMBOL_DIR`
to the official symbol directory and `KICAD_WIRED_NATIVE_CLI` to the native
`kicad-cli` executable (unless already on PATH), then run:

```text
python -m pytest tests/integration/test_wired_mcu_authoring.py
```

The test uses disposable projects and does not write to existing schematics.
The expected netlist reflects the fixture, not an independent electrical
engineering sign-off: for real hardware, verify the regulator data sheet,
source voltage tolerance, current/thermal budget, capacitors, pin mapping and
PCB layout before considering the design ready for fabrication. This is not a
model-generated schematic, actual regulator-load test, or manufacturing release.
Inspect the two exported SVG files in the pytest temporary directory against the
wired-subcircuit skill's readability rubric; netlist equality and zero ERC do
not replace that visual review.
