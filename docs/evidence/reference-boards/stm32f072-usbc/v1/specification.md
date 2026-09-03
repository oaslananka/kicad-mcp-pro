# STM32F072 USB-C / RS-485 reference board specification

## Purpose

Create a manufacturable two-layer industrial-style controller around STM32F072CBT6. The design combines USB-C device connectivity, SWD debug, an isolated functional area for RS-485 physical-layer connectivity, user IO, recovery testing, and reproducible manufacturing outputs.

## Fixed functional scope

- Use STM32F072CBT6 in LQFP48 and verify the exact symbol/footprint contract.
- Power the board from a USB-C receptacle used as a USB 2.0 device/UFP.
- Use PA11/PA12 for the MCU USB data pair according to the device datasheet/alternate-function contract; verify D-/D+ polarity before wiring.
- Provide independent 5.1 kOhm Rd resistors from CC1 and CC2 to ground and low-capacitance ESD protection on D+/D- near the connector.
- Convert VBUS to 3.3 V with a regulator sized for MCU, transceiver, LEDs, and headers; decouple every MCU supply domain according to the datasheet.
- Provide NRST support, BOOT0 default biasing, one user button, and one status LED.
- Provide a standard SWD debug header exposing SWDIO, SWCLK, NRST, 3V3, and GND.
- Add a 3.3 V RS-485 transceiver driven from a verified UART mapping, with DE/RE control, A/B connector, switchable or jumper-selectable 120 ohm termination, and appropriate bus-side transient protection.
- Add one four-pin 3.3 V I2C expansion header and test points for VBUS, 3V3, GND, USB D+/D-, and RS-485 A/B.

## PCB and layout constraints

- Board outline must fit within 60 mm x 36 mm and use two copper layers.
- Keep the USB D+/D- pair short, coupled, length-balanced, and free of stubs; use a reviewed USB differential-pair rule and continuous ground return.
- Keep USB ESD protection adjacent to the receptacle and separate the noisy RS-485 connector/transient area from the USB/MCU clock-sensitive area.
- Place MCU decoupling close to the corresponding power pins and keep regulator current loops compact.
- Route the RS-485 A/B pair together from transceiver to connector, keep termination physically close to the bus connector/transceiver path, and make the termination state obvious on silkscreen.
- Use ground pours and stitching while preserving sensible return-current paths.
- Silkscreen must identify USB-C, SWD, RESET, BOOT, RS-485 A/B, termination control, I2C, and board revision.

## Validation and evidence requirements

- ERC is required and all blocking findings must be consumed/resolved before PCB sign-off.
- DRC is required after routing and again after the recovery exercise.
- Each valid attempt must include at least one genuine reversible PCB mutation requiring recovery through reviewed MCP operations; direct/manual repair is prohibited.
- Manufacturing generation must produce BOM and Gerbers/drill files twice from the final design and compare stable manifests for reproducibility.
- Final schematic and PCB must parse/reopen successfully after export.

## Reference basis

- ST's STM32F072CB product/datasheet defines the active LQFP48 device, USB function, supply domains, BOOT/NRST, and alternate-function mappings.
- Exact UART pins, transceiver part, protection part, termination implementation, symbol, and footprints must be verified against available component/library contracts before use.
