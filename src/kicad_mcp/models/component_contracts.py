"""Seed registry of known component connectivity contracts."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase


@dataclass(frozen=True, slots=True)
class ComponentContract:
    """Minimal connectivity expectations for a known component."""

    key: str
    category: str = ""
    lib_ids: tuple[str, ...] = ()
    footprint_patterns: tuple[str, ...] = ()
    required_net_groups: tuple[tuple[str, ...], ...] = ()
    notes: str = ""


COMPONENT_CONTRACTS: tuple[ComponentContract, ...] = (
    ComponentContract(
        key="esp32_s3_wroom_1",
        category="mcu_module",
        lib_ids=("RF_Module:ESP32-S3-WROOM-1",),
        footprint_patterns=("RF_Module:ESP32-S3-WROOM-1*",),
        required_net_groups=(("GND",), ("+3.3V", "+3V3", "3V3")),
        notes="ESP32 modules should at least expose ground and a 3.3 V rail.",
    ),
    ComponentContract(
        key="adxl355",
        category="sensor",
        lib_ids=("Sensor_Motion:ADXL355",),
        footprint_patterns=("Package_LGA:*ADXL355*",),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "3V3_ANA"),
            ("SPI_SCLK",),
            ("SPI_MOSI",),
            ("SPI_MISO",),
        ),
        notes="ADXL355 blocks should expose power plus SPI connectivity.",
    ),
    ComponentContract(
        key="bme280",
        category="sensor",
        lib_ids=("Sensor:BME280", "Sensor_Specialized:BME280"),
        footprint_patterns=("Package_LGA:*BME280*", "Package_LGA:*Bosch_LGA-8*"),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "3V3_ANA"),
            ("I2C_SDA",),
            ("I2C_SCL",),
        ),
        notes="BME280-class blocks should expose power plus I2C connectivity.",
    ),
    ComponentContract(
        key="usb_c_power_entry",
        category="connector",
        lib_ids=("Connector:USB_C_Receptacle_USB2.0_16P",),
        footprint_patterns=("Connector_USB:USB_C_Receptacle*",),
        required_net_groups=(("GND",), ("+5V", "VBUS")),
        notes="USB-C receptacles should at least provide GND and VBUS.",
    ),
    ComponentContract(
        key="ap2112k_3v3",
        category="regulator",
        lib_ids=("Regulator_Linear:AP2112K-3.3",),
        footprint_patterns=("Package_TO_SOT_SMD:SOT-23-5*",),
        required_net_groups=(
            ("GND",),
            ("+5V", "VBUS"),
            ("+3.3V", "+3V3", "3V3", "3V3_ANA"),
        ),
        notes="AP2112 3.3 V regulators should expose ground, input, and output rails.",
    ),
    ComponentContract(
        key="stm32_mcu",
        category="mcu",
        lib_ids=(
            "MCU_ST_STM32F1:STM32F103C8Tx",
            "MCU_ST_STM32F4:STM32F405RGTx",
            "MCU_ST_STM32G0:STM32G0B1KBTx",
            "MCU_ST_STM32L4:STM32L432KCUx",
        ),
        required_net_groups=(("GND",), ("+3.3V", "+3V3", "VDD")),
        notes="STM32-class MCUs should expose ground and their primary VDD rail.",
    ),
    ComponentContract(
        key="rp2040",
        category="mcu",
        lib_ids=("MCU_RaspberryPi_and_Broadcom:RP2040",),
        required_net_groups=(("GND",), ("+3.3V", "+3V3", "IOVDD", "VREG_VIN")),
        notes="RP2040 designs should expose ground and a 3.3 V rail.",
    ),
    ComponentContract(
        key="nrf52840_module",
        category="mcu_module",
        lib_ids=("RF_Module:nRF52840-Dongle", "RF_Module:E73-2G4M08S1C"),
        required_net_groups=(("GND",), ("+3.3V", "+3V3", "VDD")),
        notes="nRF52 modules should expose ground and a 3.3 V rail.",
    ),
    ComponentContract(
        key="w25q_flash",
        category="memory",
        lib_ids=("Memory_Flash:W25Q128JVSIQ", "Memory_Flash:W25Q32JVSS", "Memory_Flash:W25Q64JVSS"),
        footprint_patterns=("Package_SO:*W25Q*",),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "VCC"),
            ("SPI_SCLK", "QSPI_SCK"),
            ("SPI_MOSI", "QSPI_IO0"),
            ("SPI_MISO", "QSPI_IO1"),
        ),
        notes="SPI/QSPI flash devices should expose power plus the core serial bus nets.",
    ),
    ComponentContract(
        key="eeprom_i2c",
        category="memory",
        lib_ids=("Memory_EEPROM:24LC256", "Memory_EEPROM:24LC32", "Memory_EEPROM:AT24CS02"),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "VCC"),
            ("I2C_SDA",),
            ("I2C_SCL",),
        ),
        notes="I2C EEPROMs should expose power plus SDA/SCL.",
    ),
    ComponentContract(
        key="mpu6050",
        category="sensor",
        lib_ids=("Sensor_Motion:MPU-6050",),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "VCC"),
            ("I2C_SDA",),
            ("I2C_SCL",),
        ),
        notes="MPU-6050-class motion sensors should expose power and I2C nets.",
    ),
    ComponentContract(
        key="lis3dh",
        category="sensor",
        lib_ids=("Sensor_Motion:LIS3DH",),
        required_net_groups=(
            ("GND",),
            ("+3.3V", "+3V3", "VDD"),
            ("SPI_SCLK", "I2C_SCL"),
        ),
        notes="LIS3DH should expose power plus at least one clock/control bus.",
    ),
    ComponentContract(
        key="buck_regulator",
        category="regulator",
        lib_ids=(
            "Regulator_Switching:MP1584EN",
            "Regulator_Switching:TPS62172",
            "Regulator_Switching:TPS54331",
        ),
        required_net_groups=(
            ("GND",),
            ("+5V", "VBUS", "VIN"),
            ("+3.3V", "+3V3", "VOUT"),
        ),
        notes="Buck regulators should expose ground plus an input and output rail.",
    ),
    ComponentContract(
        key="opamp_dual",
        category="analog",
        lib_ids=(
            "Amplifier_Operational:MCP6002",
            "Amplifier_Operational:LMV358",
            "Amplifier_Operational:OPA2333",
        ),
        required_net_groups=(("GND", "V-", "VSS"), ("+3.3V", "+5V", "V+", "VDD")),
        notes="Dual op-amps should expose both supply rails before analog review continues.",
    ),
    ComponentContract(
        key="level_shifter",
        category="interface",
        lib_ids=("Level_Shifter:TXS0108EPWR", "Level_Shifter:TXB0108PWR"),
        required_net_groups=(("GND",), ("+1.8V", "+3.3V", "+5V", "VCCA"), ("+3.3V", "+5V", "VCCB")),
        notes="Level shifters should expose ground and both rail domains.",
    ),
)


def find_component_contract(
    *,
    lib_id: str = "",
    footprint: str = "",
) -> ComponentContract | None:
    """Return the first known contract matching a symbol lib ID or footprint."""

    lib_id_text = lib_id.strip()
    footprint_text = footprint.strip()
    for contract in COMPONENT_CONTRACTS:
        if lib_id_text and lib_id_text in contract.lib_ids:
            return contract
        if footprint_text and any(
            fnmatchcase(footprint_text, pattern) for pattern in contract.footprint_patterns
        ):
            return contract
    return None
