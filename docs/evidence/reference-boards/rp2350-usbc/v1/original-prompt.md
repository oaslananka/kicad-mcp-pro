# RP2350A USB-C autonomous reference-board benchmark

You are performing one clean-start reference-board attempt. Use only the KiCad MCP tools exposed in this session. Do not use a terminal, direct filesystem editing, browser tools, or manual KiCad edits. Do not reuse a vendor Minimal KiCad project or any prior attempt as the starting design. Vendor references may guide decisions, but the project itself must be created during this attempt. Never claim a stage passed unless its evidence was executed and consumed.

Build a two-layer RP2350A QFN60 controller within 58 mm x 34 mm. Use at least 8 MB verified external QSPI flash, the vendor-recommended 12 MHz crystal implementation, and the current Raspberry Pi Hardware design with RP2350 guidance for the critical switching-regulator network, supply decoupling, flash/crystal placement, and ground/layout details. Do not invent a substitute power topology.

USB-C is a USB 2.0 UFP with separate 5.1 kOhm Rd resistors on CC1/CC2, low-capacitance ESD protection, and D+/D- connected to dedicated RP2350 USB_DP/USB_DM. Provide BOOTSEL, RUN/reset, a dedicated SWD header, one user LED, a 3.3 V I2C header, and test points for VBUS, 3V3, GND, D+/D-, RUN, and QSPI chip select. Verify every symbol, footprint, flash part, connector, ESD part, and critical passive contract.

Keep USB short/coupled with continuous return, keep switching nodes away from USB/crystal, keep QSPI compact, and follow the vendor minimal-layout strategy for the exposed-pad/power region. Final evidence requires ERC, DRC, a genuine MCP-only recovery exercise, BOM, two independently generated Gerber sets with comparison, and final parse/reopen.

## Phase: schematic

Create a new clean KiCad project. Build and annotate the complete RP2350A schematic: all supply/core-regulator circuitry required by the vendor reference, decoupling, QSPI flash, 12 MHz crystal, USB-C/CC/ESD, BOOTSEL, RUN, SWD, LED, I2C header, and test points. Verify component contracts and assign real footprints. Run ERC, consume the report, and resolve blocking issues through MCP. Do not start PCB layout in this phase.

## Phase: pcb

Synchronize the verified schematic into a <=58 mm x 34 mm two-layer PCB. Use the current Raspberry Pi RP2350A minimal-design guidance as the placement/routing reference for the SMPS, exposed-pad region, decoupling, crystal, QSPI flash, and ground strategy. Place USB-C/ESD for a short direct path, keep USB over continuous ground, keep switching nodes away from USB/crystal, and keep QSPI compact. Route all nets and add useful silkscreen/debug access.

Run DRC and consume all findings. Once the design is substantially routed, perform exactly one bounded reversible MCP mutation that creates a real recoverable PCB problem, verify the changed state/validation evidence, then restore the intended design using MCP only. Re-run DRC and resolve all blocking issues. If a safe recovery-required mutation cannot be executed by the live backend, stop rather than fabricating recovery evidence.

## Phase: manufacturing

Use the completed design without manual repair. Re-run required validation as available and consume the final results. Generate BOM plus complete Gerber/drill outputs to a fresh output location, then independently regenerate the same manufacturing set to a second location. Compare stable artifact manifests/digests; report reproducibility only when the comparison supports it.

Verify that final schematic and PCB parse/reopen successfully after exports. Do not modify source design merely to make evidence appear successful; unresolved validation, reproducibility, or parse/reopen stages mean the attempt is incomplete.
