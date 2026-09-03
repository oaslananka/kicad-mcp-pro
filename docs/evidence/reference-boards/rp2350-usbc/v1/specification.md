# RP2350A USB-C reference board specification

## Purpose

Create a manufacturable two-layer RP2350A controller based on Raspberry Pi's current minimal-hardware guidance while adding USB-C, debug, expansion, recovery testing, and reproducible manufacturing evidence. Critical RP2350 power circuitry and layout must follow the vendor reference rather than being improvised.

## Fixed functional scope

- Use RP2350A in QFN60 and verify the exact symbol/footprint contract.
- Use external QSPI flash of at least 8 MB with a verified RP2350-compatible connection and footprint.
- Use the vendor-recommended 12 MHz crystal implementation and verified load/placement guidance.
- Implement the RP2350 core/power network, including the on-chip switching-regulator external network, by closely following the current Raspberry Pi Hardware design with RP2350 reference and its component/layout guidance.
- Power from a USB-C receptacle used as a USB 2.0 device/UFP with separate 5.1 kOhm Rd resistors on CC1 and CC2.
- Connect USB D+/D- to the dedicated RP2350 USB_DP/USB_DM pins, protect the pair with a low-capacitance ESD array, and preserve a short continuous-return route.
- Provide BOOTSEL and RUN/reset buttons plus a dedicated SWD header exposing SWDIO, SWCLK, GND, and reference supply.
- Provide one user LED and one four-pin 3.3 V I2C expansion header.
- Add accessible test points for VBUS, 3V3, GND, USB D+/D-, RUN, and QSPI chip select.

## PCB and layout constraints

- Board outline must fit within 58 mm x 34 mm and use two copper layers with components on the top side unless a verified constraint requires otherwise.
- Follow Raspberry Pi's RP2350A minimal-design placement and routing guidance closely for the switching-regulator network, crystal, QSPI flash, decoupling, ground strategy, and exposed-pad region.
- Keep USB D+/D- short, coupled, length-balanced, free of stubs, and above a continuous ground return; place USB ESD adjacent to the receptacle.
- Keep QSPI traces compact and organized around the MCU/flash placement; do not route noisy switching nodes through sensitive USB/crystal regions.
- Keep SWD, BOOTSEL, RUN, and expansion access practical at the board edge.
- Use ground pours/stitching consistent with the vendor reference and do not create return-path slots through high-speed areas.
- Silkscreen must identify USB-C, BOOTSEL, RUN, SWD, I2C, pin-1/orientation marks, and board revision.

## Validation and evidence requirements

- ERC is required and blocking issues must be consumed/resolved before PCB sign-off.
- DRC is required after routing and again after the recovery exercise.
- Each valid attempt must perform one genuine bounded reversible PCB mutation requiring recovery through reviewed MCP operations, with no manual file repair.
- Manufacturing generation must create BOM and Gerber/drill outputs twice and compare stable artifact manifests for reproducibility.
- Final schematic and PCB must parse/reopen successfully after manufacturing generation.

## Reference basis

- Raspberry Pi Hardware design with RP2350 is the governing reference for the RP2350A minimal power, crystal, QSPI, decoupling, and layout implementation.
- Raspberry Pi's current RP2350A Minimal KiCad project may be used as design guidance but must not be copied into the clean-start attempt as a pre-completed design.
- The RP2350 product documentation defines dedicated USB_DM/USB_DP, XIN/XOUT, RUN, SWDIO/SWCLK, and supply functions.
- Exact flash, ESD, USB-C connector, passive values, symbols, and footprints must be verified against available library/component contracts before use.
