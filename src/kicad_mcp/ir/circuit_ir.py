"""Core data model for the semantic EDA intermediate representation.

The IR decouples "what the circuit *is*" from "how KiCad stores
it".  Wiring is expressed in terms of pin names and roles, not
geometry coordinates or file-level UUIDs.

Design principles
-----------------
* **Pin-name / role based** — a connection is ``(U1.VCC, 3V3)``,
  not ``(10000001, 10000002)`` with geometry lookups.
* **Immutable data classes** — once built, an ``IRCircuit`` is
  hashable and safe to cache, diff, and version.
* **Single source of truth** for tools that need to reason about
  circuit meaning: connectivity, power domains, interfaces, and
  constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PinElectricalType(Enum):
    """Electrical type matching KiCad's ``(pin ... etype)`` values."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    POWER_INPUT = "power_input"
    POWER_OUTPUT = "power_output"
    OPEN_COLLECTOR = "open_collector"
    OPEN_EMITTER = "open_emitter"
    PASSIVE = "passive"
    NOT_CONNECTED = "not_connected"
    FREE = "free"
    UNSPECIFIED = "unspecified"

    @classmethod
    def _missing_(cls, value: object) -> PinElectricalType:
        return cls.UNSPECIFIED


class PinRole(Enum):
    """Semantic role of a pin, usually inferred from name or context."""

    UNKNOWN = "unknown"
    POWER = "power"
    GROUND = "ground"
    CLOCK = "clock"
    DATA = "data"
    CONTROL = "control"
    CONFIG = "config"
    ANALOG = "analog"
    RESET = "reset"
    INTERRUPT = "interrupt"
    DEBUG = "debug"

    @classmethod
    def infer_from_name(cls, name: str) -> PinRole:
        """Guess a pin role from its name."""
        upper = name.upper()
        if upper in ("VCC", "VDD", "VSS", "VEE", "VPP", "AVCC", "AVDD"):
            return cls.POWER
        if upper in ("GND", "AGND", "DGND", "VSS", "PWR_FLAG"):
            return cls.GROUND
        if any(keyword in upper for keyword in ("CLK", "CK", "XTAL", "OSC")):
            return cls.CLOCK
        if any(keyword in upper for keyword in ("RST", "RESET", "NRST")):
            return cls.RESET
        if any(keyword in upper for keyword in ("INT", "IRQ", "NMI")):
            return cls.INTERRUPT
        if any(keyword in upper for keyword in ("ADC", "DAC", "AIN", "AOUT")):
            return cls.ANALOG
        if any(keyword in upper for keyword in ("SWD", "SWCLK", "SWDIO", "JTAG", "TMS", "TCK")):
            return cls.DEBUG
        return cls.UNKNOWN


@dataclass(frozen=True)
class IRPin:
    """A single pin on a component."""

    number: str
    name: str
    electrical_type: PinElectricalType = PinElectricalType.UNSPECIFIED
    role: PinRole = PinRole.UNKNOWN


@dataclass(frozen=True)
class IRComponent:
    """A symbol instance placed on the schematic."""

    reference: str
    lib_id: str
    value: str
    footprint: str
    pins: tuple[IRPin, ...] = ()
    dnp: bool = False
    in_bom: bool = True


@dataclass(frozen=True)
class IRNet:
    """A named (or auto-generated) electrical net.

    ``connections`` is a frozenset of ``(reference, pin_number)`` tuples
    so that nets are directly comparable and hashable.
    """

    name: str
    connections: frozenset[tuple[str, str]] = frozenset()
    is_power: bool = False
    voltage: float | None = None
    net_class: str | None = None


@dataclass(frozen=True)
class IRPowerRail:
    """A power / ground rail at a specific voltage."""

    name: str
    voltage: float
    net_names: frozenset[str] = frozenset()
    source_ref: str | None = None
    source_pin: str | None = None


@dataclass(frozen=True)
class IRInterface:
    """A named protocol interface composed of multiple nets.

    ``kind`` is a short protocol name such as ``"i2c"``, ``"spi"``,
    ``"uart"``, ``"usb"``, ``"ethernet"``, or ``"other"``.

    ``net_roles`` maps semantic role within the interface to net
    name, e.g. ``{"scl": "I2C1_SCL", "sda": "I2C1_SDA"}``.
    """

    name: str
    kind: str = "other"
    net_roles: dict[str, str] = field(default_factory=dict)
    refs: tuple[str, ...] = ()  # component references involved


@dataclass(frozen=True)
class IRConstraint:
    """A design constraint derived or declared for the circuit."""

    kind: str  # e.g. "impedance", "length", "differential", "spacing"
    net_names: frozenset[str] = frozenset()
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeSymbolInstance:
    """Native sheet identity and all placed unit UUIDs for an annotated reference."""

    sheet_path: str
    sheet_name: str
    symbol_uuids: tuple[str, ...]


@dataclass
class IRCircuit:
    """Top-level semantic circuit description.

    This is deliberately **not** frozen so that builders can populate
    fields incrementally.  Freeze before hashing if needed.
    """

    # -- Metadata ------------------------------------------------
    source_path: str | None = None
    source_uuid: str | None = None
    title: str = ""

    # -- Circuit elements ----------------------------------------
    components: dict[str, IRComponent] = field(default_factory=dict)
    """Component reference → IRComponent."""
    nets: dict[str, IRNet] = field(default_factory=dict)
    """Net name → IRNet (includes unnamed nets as ``~N<counter>``)."""
    power_rails: dict[str, IRPowerRail] = field(default_factory=dict)
    interfaces: dict[str, IRInterface] = field(default_factory=dict)
    constraints: dict[str, IRConstraint] = field(default_factory=dict)

    # -- Structural hierarchy ------------------------------------
    sheet_hierarchy: tuple[str, ...] = ()
    native_instances: dict[str, NativeSymbolInstance] = field(default_factory=dict)

    # -- Derived / memoized --------------------------------------
    _component_pin_count: int = 0
    _net_count: int = 0

    # -- Convenience helpers -------------------------------------

    def component_count(self) -> int:
        """Return the number of components (excluding power symbols)."""
        return len(self.components)

    def net_count(self) -> int:
        """Return the number of nets."""
        return len(self.nets)

    def interface_count(self) -> int:
        return len(self.interfaces)

    def pin_count(self) -> int:
        """Total pins across all components."""
        return sum(len(c.pins) for c in self.components.values())

    def find_net_by_pin(self, reference: str, pin_number: str) -> IRNet | None:
        """Return the net connected to *reference*'s *pin_number*, or ``None``."""
        for net in self.nets.values():
            if (reference, pin_number) in net.connections:
                return net
        return None

    def component(self, reference: str) -> IRComponent | None:
        return self.components.get(reference)

    def net(self, name: str) -> IRNet | None:
        return self.nets.get(name)

    def summary(self) -> str:
        """One-line summary of the circuit."""
        return (
            f"IRCircuit({self.title!r}, "
            f"{self.component_count()} components, "
            f"{self.pin_count()} pins, "
            f"{self.net_count()} nets, "
            f"{len(self.power_rails)} rails, "
            f"{self.interface_count()} interfaces)"
        )
