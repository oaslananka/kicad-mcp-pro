# STM32F072 USB-C / RS-485 autonomous reference-board benchmark

You are performing one clean-start reference-board attempt. Use only the KiCad MCP tools exposed in this session. Do not use a terminal, direct filesystem editing, browser tools, or manual KiCad edits. Do not reuse artifacts from any previous attempt. Never claim a stage passed unless you executed and consumed its evidence.

Build a two-layer STM32F072CBT6 controller within 60 mm x 36 mm. USB-C is a USB 2.0 UFP with separate 5.1 kOhm Rd resistors on CC1/CC2 and low-capacitance ESD protection on D+/D-. Use the MCU USB pins defined by the STM32F072CBT6 contract and verify polarity/alternate functions. Convert VBUS to 3.3 V and decouple all MCU supply domains. Provide NRST, BOOT0 bias, a user button, status LED, and a standard SWD header.

Add a verified 3.3 V RS-485 transceiver on an available UART with explicit DE/RE control, A/B connector, selectable 120 ohm termination, and bus transient protection. Add a 3.3 V I2C expansion header and test points for VBUS, 3V3, GND, USB D+/D-, and RS-485 A/B. Verify every symbol, footprint, UART mapping, and protection/transceiver contract rather than guessing.

Keep USB short/coupled with continuous return, place USB ESD near the receptacle, keep decoupling and regulator loops compact, and keep the RS-485 connector/protection area physically organized away from the sensitive USB/MCU area. Final evidence requires ERC, DRC, a real MCP-only recovery exercise, BOM, two independent Gerber generations with comparison, and final parse/reopen.

## Phase: schematic

Create a clean KiCad project and complete the schematic for power, USB-C, MCU supply/decoupling, reset/boot, SWD, user IO, RS-485 transceiver/DE/RE/termination/protection, I2C header, and test points. Verify component contracts, annotate, and assign real footprints. Run ERC, consume the report, and resolve blocking issues through MCP. Do not begin PCB layout in this phase.

## Phase: pcb

Synchronize the verified schematic to PCB. Create the <=60 mm x 36 mm two-layer outline, reviewed rules/net classes, compact MCU power placement, short USB path, organized SWD access, and a clearly separated RS-485 connector/protection/termination area. Place and route all components, create appropriate ground pours/returns, and add clear silkscreen identifiers.

Run DRC and consume its findings. After the board is substantially routed, perform exactly one bounded reversible MCP mutation that creates a genuine recoverable PCB problem, observe the problem through validation/state evidence, then restore the intended design using MCP only. Re-run DRC after recovery and resolve all blocking issues. If the backend cannot safely perform a real recovery-required mutation, stop rather than fabricate recovery evidence.

## Phase: manufacturing

Use the completed design without manual edits. Re-run required validation as available and consume the final results. Generate BOM plus complete Gerber/drill outputs to one fresh output location, then regenerate the same set independently to a second location. Compare stable artifact manifests/digests and report byte-identical or explicitly normalized-equivalent results only when supported by evidence.

Verify that the final schematic and PCB parse/reopen successfully after manufacturing generation. Do not alter the design merely to make export evidence look clean; unresolved validation, reproducibility, or parse/reopen stages mean the attempt is not complete.
