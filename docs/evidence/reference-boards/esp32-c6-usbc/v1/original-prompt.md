# ESP32-C6 USB-C autonomous reference-board benchmark

You are performing one clean-start reference-board attempt. Use only the KiCad MCP tools exposed in this session. Do not use a terminal, direct filesystem editing, browser tools, or manual KiCad edits. Do not reuse artifacts from any previous attempt. Never claim a stage passed unless you actually executed and consumed the corresponding evidence.

Build a two-layer USB-C ESP32-C6 development/sensor node within 50 mm x 32 mm. Use a verified ESP32-C6-MINI-1 or ESP32-C6-WROOM-1 module variant with integrated antenna/flash. USB-C is a USB 2.0 UFP: CC1 and CC2 each require 5.1 kOhm Rd to ground; protect D+/D- with a low-capacitance ESD array; connect D- to GPIO12 and D+ to GPIO13. Convert VBUS to 3.3 V with a suitable verified regulator and proper decoupling. Provide reset/EN support, one documented boot-mode button, one user LED on a non-strapping GPIO, a 3.3 V I2C header, and VBUS/3V3/GND/D+/D- test points.

The module antenna must sit at a board edge with the manufacturer's keepout respected. Keep USB short, coupled and length-balanced, use a continuous return path, place ESD adjacent to the connector, and use ground pours/stitching without entering the RF keepout. Verify every symbol/footprint choice against available libraries instead of inventing parts.

The final attempt requires ERC, DRC, a genuine MCP-only recovery exercise, BOM, Gerbers generated twice for reproducibility comparison, and final parse/reopen. If backend capability is insufficient for a required operation, fail honestly; do not simulate or fabricate evidence.

## Phase: schematic

Create a new clean project for this board using KiCad MCP. Build and annotate the complete schematic, including power, USB-C CC resistors, USB ESD protection, regulator/decoupling, ESP32-C6 module, reset/boot controls, LED, I2C header, and test points. Verify component contracts and assign real footprints. Run ERC, consume all findings, correct blocking issues through MCP, and finish with a schematic that is ready to transfer to PCB. Do not start PCB layout in this phase.

## Phase: pcb

Open the project created by the schematic phase and synchronize it to PCB. Create the <=50 mm x 32 mm two-layer outline, establish reviewed net classes/rules, place the ESP32-C6 antenna at a board edge with its keepout preserved, place the USB-C/ESD path tightly, and place regulator decoupling for short current loops. Route all nets, create the ground strategy, add stitching where appropriate, and produce clear silkscreen labels.

Run DRC and consume its findings. Once the board is substantially routed, perform exactly one bounded reversible recovery exercise using MCP mutations: introduce a real non-destructive PCB state that requires recovery, verify the issue is observable, then recover the intended design through MCP without direct file/manual repair. Re-run DRC after recovery and resolve all blocking issues. If the live backend cannot safely execute a real recovery-required mutation, stop rather than inventing evidence.

## Phase: manufacturing

Use the completed project from the previous phases. Re-run required validation as available and consume the final results. Generate a BOM and a complete Gerber/drill manufacturing set into a fresh output location. Generate the same manufacturing outputs independently a second time into a separate output location. Compare stable artifact manifests/digests and report whether the two generations are byte-identical or otherwise normalized-equivalent under an explicit stable rule.

Verify the final schematic and board still parse/reopen after manufacturing generation. Do not modify the design to make export evidence look clean. Finish only when the manufacturing set is reproducible and no required validation or parse/reopen stage is unresolved.
