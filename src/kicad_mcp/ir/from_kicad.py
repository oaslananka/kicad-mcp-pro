"""Parse a KiCad ``.kicad_sch`` file into the semantic IR (``IRCircuit``).

The parser reuses existing kicad-mcp schematic infrastructure:
:func:`~kicad_mcp.tools.schematic.parse_schematic_file` for component
listing and :func:`~kicad_mcp.tools.schematic._build_connectivity_groups`
for net extraction.

Library-level pin metadata is loaded when symbol libraries are available
on disk, giving full pin coverage (including unconnected pins).  When a
library file cannot be found, only pins that appear in connectivity
groups (i.e. connected pins) are included.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..tools.schematic import (
    _build_connectivity_groups,
    _get_schematic_file,
    _split_lib_id,
    get_pin_metadata,
    parse_schematic_file,
)
from .circuit_ir import (
    IRCircuit,
    IRComponent,
    IRInterface,
    IRNet,
    IRPin,
    IRPowerRail,
    PinElectricalType,
    PinRole,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KICAD_POWER_PREFIX = "power:"
"""Symbols whose ``lib_id`` starts with this are power / ground symbols."""

_COMMON_POWER_TYPES: dict[str, tuple[str, float]] = {
    "GND": ("GND", 0.0),
    "PWR_FLAG": ("GND", 0.0),
    "VCC": ("VCC", 3.3),
    "VDD": ("VDD", 3.3),
    "VSS": ("GND", 0.0),
    "VEE": ("VEE", -5.0),
    "AVCC": ("AVCC", 3.3),
    "AVDD": ("AVDD", 3.3),
    "AGND": ("GND", 0.0),
    "DGND": ("GND", 0.0),
    "3V3": ("3V3", 3.3),
    "5V": ("5V", 5.0),
    "1V8": ("1V8", 1.8),
    "12V": ("12V", 12.0),
    "VBAT": ("VBAT", 3.0),
    "VREF": ("VREF", 3.0),
    "VPOS": ("VPOS", 5.0),
    "VNEG": ("VNEG", -5.0),
    "+3.3V": ("3V3", 3.3),
    "+5V": ("5V", 5.0),
    "-5V": ("-5V", -5.0),
}
"""Well-known power-net names with canonical rail name and voltage."""

_INTERFACE_PATTERNS: list[tuple[str, str, list[str]]] = [
    # (kind, role_set_name, [name_patterns])
    # I2C
    ("i2c", "i2c_general", ["_SDA", "_SCL", ".SDA", ".SCL"]),
    # SPI
    ("spi", "spi_general", ["_MOSI", "_MISO", "_SCK", "_CS", "_NSS"]),
    # UART
    ("uart", "uart_general", ["_TX", "_RX", "_RTS", "_CTS"]),
    # USB
    ("usb", "usb_general", ["_DP", "_DN", "_VBUS", "_ID", "_S"]),
    # Ethernet
    ("ethernet", "eth_general", ["_TX_P", "_TX_N", "_RX_P", "_RX_N"]),
    # CAN
    ("can", "can_general", ["_CAN_H", "_CAN_L", "_CAN_TX", "_CAN_RX"]),
    # Audio
    ("audio", "audio_general", ["_LRCK", "_BCLK", "_DIN", "_DOUT", "_MCLK"]),
    # SDIO
    ("sdio", "sdio_general", ["_SDIO_D", "_SDIO_CLK", "_SDIO_CMD"]),
    # I2S
    ("i2s", "i2s_general", ["_I2S_", "_BCLK", "_LRCK"]),
]
"""Patterns used to detect interface types from net names."""


def _parse_numeric_rail_voltage(net_name: str) -> float | None:
    for index, ch in enumerate(net_name):
        if ch not in "Vv" or index == 0 or not net_name[index - 1].isdecimal():
            continue
        start = index - 1
        while start > 0 and net_name[start - 1].isdecimal():
            start -= 1
        end = index + 1
        while end < len(net_name) and net_name[end].isdecimal():
            end += 1
        volts = float(f"{net_name[start:index]}.{net_name[index + 1 : end] or '0'}")
        return volts
    return None


def _rail_name_and_voltage(net_name: str) -> tuple[str, float]:
    """Return a canonical (rail_name, voltage) for *net_name*."""
    upper = net_name.upper()
    known = _COMMON_POWER_TYPES.get(upper)
    if known is not None:
        return known
    # Try to parse voltage from name patterns like "3V3", "5V0", "1V8"

    voltage = _parse_numeric_rail_voltage(net_name)
    if voltage is not None:
        return (net_name, voltage)
    # Default — assume a generic rail at 0 V, likely GND derived
    if "GND" in upper or "VSS" in upper:
        return (net_name, 0.0)
    if "VCC" in upper or "VDD" in upper:
        return (net_name, 3.3)
    return (net_name, 0.0)


def _infer_pin_role(name: str, etype: str) -> PinRole:
    """Infer a semantic role from pin name and KiCad electrical type."""
    role = PinRole.infer_from_name(name)
    if role != PinRole.UNKNOWN:
        return role
    # Fall back to etype
    etype_lower = etype.lower()
    if etype_lower in ("power_input", "power_output"):
        return PinRole.POWER
    if etype_lower == "input":
        return PinRole.CONTROL
    if etype_lower == "output":
        return PinRole.DATA
    if etype_lower in ("bidirectional", "tri_state"):
        return PinRole.DATA
    return PinRole.UNKNOWN


def _to_electrical_type(etype_str: str) -> PinElectricalType:
    """Normalize a KiCad etype string to ``PinElectricalType``."""
    normalized = etype_str.lower().replace(" ", "_")
    try:
        return PinElectricalType(normalized)
    except ValueError:
        return PinElectricalType.UNSPECIFIED


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def parse_schematic(
    sch_path: str | Path | None = None,
    *,
    load_pin_metadata: bool = True,
) -> IRCircuit:
    """Parse a KiCad ``.kicad_sch`` file into a semantic ``IRCircuit``.

    Parameters
    ----------
    sch_path:
        Path to a ``.kicad_sch`` file.  When ``None``, the active
        schematic file from the server config is used.
    load_pin_metadata:
        When ``True`` (default), attempt to load full pin metadata from
        symbol library ``.kicad_sym`` files so that every pin (including
        unconnected ones) appears in the IR.
    """
    if sch_path is None:
        sch_file = _get_schematic_file()
    else:
        sch_file = Path(sch_path).expanduser().resolve()

    ir = IRCircuit(source_path=str(sch_file))

    # 1. Parse raw schematic data
    raw_data = parse_schematic_file(sch_file)
    ir.source_uuid = raw_data.get("uuid")
    ir.title = sch_file.stem

    # 2. Build symbol → IRComponent map
    _populate_components(ir, raw_data, sch_file, load_pin_metadata)

    # 3. Build connectivity groups → nets
    connectivity_groups = _build_connectivity_groups(sch_file)
    _populate_nets(ir, connectivity_groups, raw_data)

    # 4. Detect power rails
    _detect_power_rails(ir)

    # 5. Detect interfaces from net naming
    _detect_interfaces(ir)

    # 6. Build sheet hierarchy
    _populate_sheet_hierarchy(ir, sch_file)

    return ir


# ---------------------------------------------------------------------------
# Internal stages
# ---------------------------------------------------------------------------


def _populate_components(
    ir: IRCircuit,
    raw_data: dict[str, Any],
    sch_file: Path,
    load_pin_metadata: bool,
) -> None:
    """Build ``IRComponent`` entries from parsed schematic symbols."""
    for sym in raw_data.get("symbols", []):
        lib_id: str = sym.get("lib_id", "")
        if lib_id.startswith(_KICAD_POWER_PREFIX):
            continue  # power symbols become rails, not components

        reference: str = sym.get("reference", "?")
        value: str = sym.get("value", "")
        footprint: str = sym.get("footprint", "")
        dnp: bool = bool(sym.get("dnp", False))
        in_bom: bool = bool(sym.get("in_bom", True))

        pins: list[IRPin] = []

        if load_pin_metadata:
            library, symbol_name = _split_lib_id(lib_id)
            unit = int(sym.get("unit", 1))
            pin_meta = get_pin_metadata(library, symbol_name, unit, sch_dir=sch_file.parent)
            for pin_num, meta in sorted(pin_meta.items(), key=lambda x: _pin_sort_key(x[0])):
                pname: str = meta.get("name", "")
                etype_str: str = meta.get("etype", "unspecified")
                electrical_type = _to_electrical_type(etype_str)
                role = _infer_pin_role(pname, etype_str)
                pins.append(
                    IRPin(
                        number=str(pin_num),
                        name=pname,
                        electrical_type=electrical_type,
                        role=role,
                    )
                )

        ir.components[reference] = IRComponent(
            reference=reference,
            lib_id=lib_id,
            value=value,
            footprint=footprint,
            pins=tuple(pins),
            dnp=dnp,
            in_bom=in_bom,
        )


def _pin_sort_key(pin_number: str) -> tuple[int, int | str]:
    """Sort pin numbers sensibly: numeric first, then alpha."""
    try:
        return (0, int(pin_number))
    except ValueError:
        return (1, pin_number)


def _populate_nets(
    ir: IRCircuit,
    connectivity_groups: list[dict[str, Any]],
    raw_data: dict[str, Any],
) -> None:
    """Build ``IRNet`` entries from connectivity groups."""
    unnamed_counter = 0
    power_symbol_values: set[str] = {
        sym.get("value", "") for sym in raw_data.get("power_symbols", [])
    }

    for group in connectivity_groups:
        names: list[str] = group.get("names", [])
        pins: list[dict[str, Any]] = group.get("pins", [])

        # Determine net name
        if names:
            net_name = names[0]
        else:
            unnamed_counter += 1
            net_name = f"~N{unnamed_counter}"

        # Build connection tuples (reference, pin_number)
        connections: set[tuple[str, str]] = set()
        for pin_info in pins:
            ref: str = pin_info.get("reference", "")
            pin_num: str = str(pin_info.get("pin", ""))
            if ref and pin_num:
                connections.add((ref, pin_num))

        # Determine if this is a power net
        is_power = bool(power_symbol_values & set(names)) or bool(
            names and names[0].upper() in _COMMON_POWER_TYPES
        )

        # Skip duplicates (same named net appearing in multiple groups is merged
        # by _build_connectivity_groups, but let's be safe)
        if net_name in ir.nets:
            existing = ir.nets[net_name]
            ir.nets[net_name] = IRNet(
                name=net_name,
                connections=existing.connections | frozenset(connections),
                is_power=existing.is_power or is_power,
                voltage=existing.voltage,
                net_class=existing.net_class,
            )
        else:
            ir.nets[net_name] = IRNet(
                name=net_name,
                connections=frozenset(connections),
                is_power=is_power,
                voltage=_rail_name_and_voltage(net_name)[1] if is_power else None,
            )


def _detect_power_rails(
    ir: IRCircuit,
) -> None:
    """Detect power / ground nets and group them into rails."""
    # Collect all nets that carry power names
    rail_map: dict[str, set[str]] = {}
    rail_voltage: dict[str, float] = {}

    for net_name, net in ir.nets.items():
        if not net.is_power:
            upper = net_name.upper()
            if upper not in _COMMON_POWER_TYPES and "V" not in net_name[0:1]:
                continue

        rail_name, voltage = _rail_name_and_voltage(net_name)
        if rail_name not in rail_map:
            rail_map[rail_name] = set()
            rail_voltage[rail_name] = voltage
        rail_map[rail_name].add(net_name)

    ir.power_rails = {
        name: IRPowerRail(
            name=name,
            voltage=rail_voltage[name],
            net_names=frozenset(net_set),
        )
        for name, net_set in rail_map.items()
    }


_ROLE_MAP: dict[str, str] = {
    "sda": "sda",
    "scl": "scl",
    "mosi": "mosi",
    "miso": "miso",
    "sck": "sck",
    "cs": "cs",
    "tx": "tx",
    "rx": "rx",
    "rts": "rts",
    "cts": "cts",
    "dp": "dp",
    "dn": "dn",
    "vbus": "vbus",
    "tx_p": "tx_p",
    "tx_n": "tx_n",
    "rx_p": "rx_p",
    "rx_n": "rx_n",
    "can_h": "can_h",
    "can_l": "can_l",
    "d0": "data0",
    "d1": "data1",
    "d2": "data2",
    "d3": "data3",
    "clk": "clk",
    "cmd": "cmd",
}


def _match_net_interface(net_name: str) -> tuple[str, str, str] | None:
    for kind, _, suffixes in _INTERFACE_PATTERNS:
        for suffix in suffixes:
            if suffix in net_name:
                idx = net_name.index(suffix)
                prefix = net_name[:idx]
                role_str = suffix.lstrip("._").lower()
                role = _ROLE_MAP.get(role_str, role_str)
                return prefix, kind, role
    return None


def _build_interface_entry(
    ir: IRCircuit, prefix: str, kind: str, net_roles: dict[str, str]
) -> IRInterface:
    refs: set[str] = set()
    for net_name in net_roles.values():
        net = ir.nets.get(net_name)
        if net is not None:
            for ref, _ in net.connections:
                refs.add(ref)
    name = f"{prefix}_{kind}" if prefix else kind
    return IRInterface(
        name=name,
        kind=kind,
        net_roles=net_roles,
        refs=tuple(sorted(refs)),
    )


def _detect_interfaces(ir: IRCircuit) -> None:
    """Infer protocol interfaces from net naming patterns.

    Scans every net name for known interface suffixes and groups
    matching nets by a common prefix.
    """
    grouped: dict[str, dict[str, str]] = {}  # prefix -> {role: net_name}
    kind_map: dict[str, str] = {}  # prefix -> kind

    for net_name in ir.nets:
        matched = _match_net_interface(net_name)
        if matched is not None:
            prefix, kind, role = matched
            if prefix not in grouped:
                grouped[prefix] = {}
                kind_map[prefix] = kind
            grouped[prefix][role] = net_name

    for prefix, net_roles in grouped.items():
        entry = _build_interface_entry(ir, prefix, kind_map[prefix], net_roles)
        ir.interfaces[entry.name] = entry


def _populate_sheet_hierarchy(ir: IRCircuit, sch_file: Path) -> None:
    """Walk the sheet hierarchy for the design."""
    from ..tools.schematic import _iter_child_sheet_paths

    try:
        sheets = _iter_child_sheet_paths(sch_file)
        if sheets:
            paths = [str(p) for _, p in sheets]
            ir.sheet_hierarchy = (str(sch_file), *paths)
        else:
            ir.sheet_hierarchy = (str(sch_file),)
    except Exception:
        ir.sheet_hierarchy = (str(sch_file),)
