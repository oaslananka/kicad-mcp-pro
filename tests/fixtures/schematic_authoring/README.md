# MCU authoring regression

`wroom32e.json` contains one small, deterministic schematic plan and its intended
pin connections. It uses installed KiCad 10 symbol libraries rather than
vendoring library files. The integration test builds both wired and label-only
schematics through the existing MCP tools, adds the intentional unused pin
markers, checks native ERC/SVG, and compares all net memberships and component
reference/value/footprint tuples. It is not an autonomous-agent prompt trial or
hardware validation.

To run with a native KiCad 10 installation, set `KICAD_WIRED_NATIVE_SYMBOL_DIR`
to the official symbol directory and `KICAD_WIRED_NATIVE_CLI` to the native
`kicad-cli` executable (unless already on PATH), then run:

```text
python -m pytest tests/integration/test_wired_mcu_authoring.py
```

The test uses disposable projects and does not write to existing schematics.
Inspect the two exported SVG files in the pytest temporary directory against the
wired-subcircuit skill's readability rubric; netlist equality and zero ERC do
not replace that visual review.
