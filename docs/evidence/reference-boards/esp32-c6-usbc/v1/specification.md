# ESP32-C6 USB-C reference board specification

## Purpose

Create a manufacturable two-layer USB-C development/sensor node around an ESP32-C6 module. The board must exercise schematic creation, native USB, RF-aware placement, PCB routing, recovery after a real reversible mutation, DRC, BOM generation, and reproducible Gerber generation.

## Fixed functional scope

- Use an ESP32-C6-MINI-1 or ESP32-C6-WROOM-1 module variant with integrated flash and antenna; verify the exact KiCad symbol/footprint contract before placement.
- Power the board from a USB-C receptacle used as a USB 2.0 device/UFP.
- Connect USB D- to ESP32-C6 GPIO12 and USB D+ to GPIO13.
- Provide independent 5.1 kOhm Rd resistors from CC1 and CC2 to ground.
- Protect D+ and D- with a low-capacitance USB ESD array located near the connector.
- Convert VBUS to 3.3 V with a regulator sized for the ESP32-C6 module and exposed peripherals; include input/output decoupling per the regulator contract.
- Provide module EN/reset support and one boot-mode button using the module's documented strapping requirements.
- Provide one user LED on a non-strapping GPIO and a four-pin 3.3 V I2C expansion header with GND, 3V3, SDA, and SCL.
- Add accessible test points for VBUS, 3V3, GND, D+, and D-.

## PCB and layout constraints

- Board outline must fit within 50 mm x 32 mm and use two copper layers.
- Place the module antenna at a board edge and obey the module manufacturer's antenna keepout and placement guidance; do not route copper or place components in the keepout.
- Keep the USB D+/D- pair short, coupled, length-balanced, and free of stubs. Use a reviewed USB differential-pair rule with a 90 ohm differential target where the chosen stackup makes that meaningful.
- Keep the ESD device closer to the connector than to the module.
- Use a continuous ground return under USB where permitted and a low-impedance ground strategy for regulator/module decoupling.
- Use a ground pour and stitching vias without violating the antenna keepout.
- Silkscreen must identify USB-C, RESET, BOOT, the I2C header, polarity/orientation where relevant, and board revision.

## Validation and evidence requirements

- ERC is required and its result must be consumed before PCB sign-off.
- DRC is required after routing and again after the recovery exercise.
- Each valid attempt must include at least one genuine reversible PCB mutation that requires recovery. The mutation must be performed and recovered through reviewed MCP operations; manual file repair does not count.
- If a safe reversible recovery exercise cannot be executed with the available backend, record the attempt honestly rather than fabricating recovery evidence.
- Manufacturing generation must produce BOM and Gerbers, then regenerate them independently and compare artifact manifests for reproducibility.
- Final KiCad schematic and board must parse/reopen successfully after all exports.

## Reference basis

- Espressif ESP32-C6 USB Serial/JTAG documentation: GPIO12 is USB D- and GPIO13 is USB D+.
- Espressif ESP32-C6 module datasheets and PCB-layout recommendations govern antenna keepout, power, reset, and strapping details.
- Component values or footprints not fixed above must be chosen from available KiCad libraries and verified before use; do not invent unavailable parts.
