# KiCad 10.0.4 Canary Summary

- Generated: 2026-07-03T13:45:00Z
- Source commit: `ca9941e`
- Host: `ops-vps-fra1`
- OS: Ubuntu 22.04.5 LTS
- Package source: `ppa:kicad/kicad-10.0-releases`
- CLI path: `/usr/bin/kicad-cli`
- CLI version: `10.0.4`
- Runner user: `kicadcanary`
- Result: PASS
- Failing fixtures: none
- Passing steps: 31
- Optional skips: 1, `allegro-import-capability`, because KiCad 10.0.4 CLI help did not advertise the optional `allegro` token.
- Generated artifact bundle: 129,071 bytes
- Generated artifact bundle SHA-256: `d5d918932713ab9aad09626670caf1690ab84f5a7cd1b133fcd7c66f11f74057`

Command:

```bash
.venv/bin/python scripts/kicad_canary.py run --artifacts /tmp/kicad-canary-artifacts/kicad-10-0-4-2026-07-03 --kicad-range 10.0.x
```

Covered surface:

- Version detection.
- Clean and dirty ERC JSON.
- Clean and dirty DRC JSON.
- Schematic PDF and property-popup suppression PDF.
- PCB PDF, SVG, DXF, render, STEP, STEPZ, BREP, GLB, and STL exports.
- BOM, netlist, board statistics, schematic DXF, schematic SVG, Python BOM, and SPICE netlist exports.
- PADS import probe and optional Allegro import probe.
- Gerber, drill, and IPC-2581 manufacturing outputs.
- Path-with-spaces, Unicode path, and read-only output behavior.
