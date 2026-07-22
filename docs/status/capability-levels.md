# Capability Verification Levels

| Capability | Status | Notes |
|---|---|---|
| Project management (`kicad_set_project`, project discovery) | Verified | Covered by unit and integration tests. |
| Schematic reading / inspection | Verified | Stable read surface with fixture-backed coverage. |
| Schematic writing / editing | Experimental | File-backed editing uses the hybrid IPC reload path when KiCad 10+ reports an open schematic document; parser round-trip validation is still required for broad confidence. |
| PCB inspection | Verified | Covered by IPC/file-backed tests and stable board-state helpers. |
| PCB editing (IPC-backed) | Experimental | Requires KiCad 10 live IPC and an open PCB context; live editing tool discovery is hidden when IPC is unavailable. |
| DRC / ERC validation | Verified | CLI and validation-gate backed, with fixture coverage. |
| BOM export | Experimental | Multi-sheet BOM accuracy requires explicit fixture verification. |
| Gerber / drill export | Verified | CLI-backed export path with integration coverage. |
| STEP / 3D export | Verified | CLI-backed export path. |
| FreeRouting / auto-routing | Experimental | Requires an external binary or container; not all installations are stable. |
| ngspice simulation | Experimental | Requires an external binary; currently smoke-level and parser-level coverage. |
| SI / PI / EMC helpers | Experimental | Engineering estimates and review helpers; not a fab-final signoff source. |
| Manufacturing gate / `export_manufacturing_package` | Human approval required | Final release requires explicit human sign-off. |
| PyPI / registry publish | Human approval required | Protected environment and publishing credentials are not fully automated. |
