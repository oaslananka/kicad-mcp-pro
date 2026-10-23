"""Electrical-design-correctness rules for schematics (issue #197).

KiCad's ERC verifies *connectivity* and pin-type conflicts; it does not verify
*design intent* such as "every supply rail that feeds an IC has a decoupling
capacitor" or "an I2C bus has pull-up resistors". This module is the pure-domain
engine for those professional-practice checks. It takes a connectivity net model
(the structure produced by ``_build_connectivity_groups``) and returns structured
findings, with no KiCad dependency so it is fully unit-testable.

Each net is a mapping with at least::

    {"names": ["VCC", ...], "pins": [{"reference": "U1", "pin": "1", "value": "MCU"}, ...]}

Rules are intentionally conservative (they only fire on strong signals) to keep
false positives low; severities are advisory by default. Add new rules to
``DESIGN_RULES`` — each is a pure function ``(list[NetView]) -> list[Finding]``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# A net as produced by _build_connectivity_groups: names + connected pins.
NetView = Mapping[str, Any]

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# Ground / return nets are supply-adjacent but never need their own decoupling.
_GROUND_NAMES = frozenset(
    {"GND", "AGND", "DGND", "PGND", "GNDA", "GNDD", "VSS", "VSSA", "EARTH", "0V"}
)

# Tokens that mark a positive supply rail.
_SUPPLY_TOKENS = (
    "VCC",
    "VDD",
    "VBAT",
    "VBUS",
    "VSYS",
    "VIN",
    "AVDD",
    "VDDA",
    "VCCIO",
    "VAUX",
    "VREF",
)

# e.g. +3V3, 3V3, +5V, 5V, +1V8, +12V, 3.3V
_VOLTAGE_RAIL_RE = re.compile(r"^\+?\d+(?:[V.]\d+)?V?$", re.IGNORECASE)

# A voltage token embedded in a suffixed/compound rail name: the ``3V3`` in
# ``3V3_DIG``/``3V3_ANA``, the ``5V`` in ``5V_SYS``/``VBUS_5V``/``VPOE_5V``. The
# ``V`` is required so plain numeric domain suffixes (``BANK_12``, ``GPIO_5``) are
# not mistaken for rails.
_VOLTAGE_TOKEN_RE = re.compile(r"^\d+V\d*$", re.IGNORECASE)


def _has_voltage_token(token: str) -> bool:
    """Whether any ``_``/``-`` delimited part of ``token`` encodes a voltage."""
    return any(_VOLTAGE_TOKEN_RE.match(part) for part in re.split(r"[_-]", token) if part)


_I2C_TOKEN_RE = re.compile(r"(?:^|[^A-Z])(SDA|SCL)(?:[^A-Z]|\d|$)")


@dataclass(frozen=True)
class Finding:
    """A single design-rule observation."""

    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str
    refs: tuple[str, ...] = field(default_factory=tuple)

    def sort_key(self) -> tuple[int, str, str]:
        return (_SEVERITY_ORDER.get(self.severity, 9), self.rule_id, self.message)


def _net_names(net: NetView) -> list[str]:
    return [str(name) for name in net.get("names", []) if str(name).strip()]


def _net_refs(net: NetView, prefix_re: re.Pattern[str]) -> list[str]:
    """Distinct component references on a net whose designator matches ``prefix_re``."""
    seen: list[str] = []
    for pin in net.get("pins", []):
        ref = str(pin.get("reference", ""))
        if prefix_re.match(ref) and ref not in seen:
            seen.append(ref)
    return seen


_RESISTOR_RE = re.compile(r"^R\d")
_CAP_RE = re.compile(r"^C\d")
_IC_RE = re.compile(r"^(?:U|IC)\d")
_CRYSTAL_RE = re.compile(r"^[YX]\d")
_CONNECTOR_RE = re.compile(r"^(?:J|CN|CON)\d")
_RESET_TOKENS = frozenset({"RST", "NRST", "RSTN", "POR"})
_EXTERNAL_PORT_TOKEN_RE = re.compile(
    r"(?:^|[^A-Z0-9])(?:VBUS|VIN|VBAT|RS[ _-]?485|UART|TXD|RXD|GPIO|IO)(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)
_PROTECTION_REF_RE = re.compile(r"^(?:ESD|TVS|F|PTC|RV)\d", re.IGNORECASE)
_PROTECTION_VALUE_RE = re.compile(
    r"(?:TVS|ESD|PESD|TPD|USBLC|SP[0-9]|SMF|SMAJ|SMBJ|SMCJ|ESDA|"
    r"PROTECT|POLYFUSE|PTC|FUSE|SCHOTTKY|REVERSE|VARISTOR|MOV|SS[0-9]|1N581)",
    re.IGNORECASE,
)


def is_ground_name(name: str) -> bool:
    return name.strip().upper() in _GROUND_NAMES


def is_supply_rail_name(name: str) -> bool:
    """Return whether a net name denotes a positive supply rail (not ground)."""
    token = name.strip().upper()
    if not token or is_ground_name(token):
        return False
    if token.startswith("+"):
        return True
    if any(supply in token for supply in _SUPPLY_TOKENS):
        return True
    if _has_voltage_token(token):
        return True
    return bool(_VOLTAGE_RAIL_RE.match(token)) and token not in {"0V"}


# A rail whose name encodes an explicit voltage: +3V3, 3V3, +5V, 3.3V, +1V8, +12V.
_RAIL_VOLTAGE_RE = re.compile(r"^\+?(\d+)(?:[V.](\d+))?V?$", re.IGNORECASE)


def rail_voltage(name: str) -> float | None:
    """Return the nominal voltage a rail name encodes, or ``None`` if it has none.

    ``+3V3`` / ``3V3`` / ``3.3V`` -> 3.3, ``+5V`` -> 5.0, ``+1V8`` -> 1.8. Named
    rails without an explicit number (``VCC``, ``VDD``, ``VBUS``) return ``None``
    so they are never compared by value.
    """
    token = name.strip().upper()
    match = _RAIL_VOLTAGE_RE.match(token)
    if match is None:
        # Suffixed/compound names (3V3_DIG, 5V_SYS, VBUS_5V): parse the embedded
        # voltage token so value-conflict checks still apply.
        for part in re.split(r"[_-]", token):
            if _VOLTAGE_TOKEN_RE.match(part):
                match = _RAIL_VOLTAGE_RE.match(part)
                break
    if match is None:
        return None
    whole, frac = match.group(1), match.group(2)
    return float(whole) if frac is None else float(f"{whole}.{frac}")


def is_i2c_name(name: str) -> bool:
    return bool(_I2C_TOKEN_RE.search(name.strip().upper()))


def is_reset_name(name: str) -> bool:
    """Return whether a net name denotes a reset line (typically active-low)."""
    upper = name.strip().upper()
    if "RESET" in upper or "MCLR" in upper:
        return True
    return any(token in _RESET_TOKENS for token in re.split(r"[^A-Z0-9]+", upper))


_CAN_BUS_RE = re.compile(r"\bCAN[_ -]?[HL]\b")
_INTERRUPT_TOKENS = frozenset({"INT", "IRQ", "NINT", "NIRQ", "INTN", "IRQN"})
_ACTIVE_LOW_INTERRUPT_TOKENS = frozenset({"NINT", "NIRQ", "INTN", "IRQN"})


def is_can_name(name: str) -> bool:
    """Return whether a net name denotes a CAN differential bus line (CANH/CANL)."""
    return bool(_CAN_BUS_RE.search(name.strip().upper()))


def is_active_low_interrupt_name(name: str) -> bool:
    """Return whether a net name denotes an active-low (open-drain) interrupt line."""
    raw = name.strip()
    tokens = set(re.split(r"[^A-Z0-9]+", raw.upper()))
    if not (tokens & _INTERRUPT_TOKENS):
        return False
    if raw.startswith(("~", "/")):
        return True
    if tokens & _ACTIVE_LOW_INTERRUPT_TOKENS:
        return True
    return raw.upper().endswith("_N")


# --- USB interface (issue #205, domain rule pack) ---------------------------
# Sign forms (D+/D-) are unambiguous and matched anywhere. Letter forms
# (DP/DM/D_P/D_N) require a USB prefix so DDR data-mask lines (DM/DQM) and the
# like do not trip the diff-pair rule.
_USB_DP_SIGN_RE = re.compile(r"(?:^|[^A-Z0-9])D\+", re.IGNORECASE)
_USB_DM_SIGN_RE = re.compile(r"(?:^|[^A-Z0-9])D-(?![A-Z0-9])", re.IGNORECASE)
_USB_DP_LETTER_RE = re.compile(
    r"(?:^|[^A-Z0-9])USB[ _-]*D[ _-]*(?:P|PLUS)(?![A-Z0-9])", re.IGNORECASE
)
_USB_DM_LETTER_RE = re.compile(
    r"(?:^|[^A-Z0-9])USB[ _-]*D[ _-]*(?:M|N|MINUS)(?![A-Z0-9])", re.IGNORECASE
)
# USB-C configuration channel: CC, CC1, CC2 (optionally USB-prefixed). The
# leading boundary keeps VCC/AVCC/ACC out.
_USB_CC_RE = re.compile(r"(?:^|[^A-Z0-9])(?:USB[ _-]*)?CC[12]?(?![A-Z0-9])", re.IGNORECASE)


def usb_data_polarity(name: str) -> str | None:
    """Return ``"+"``/``"-"`` if the net is a USB D+/D- data line, else ``None``."""
    raw = name.strip()
    if _USB_DP_SIGN_RE.search(raw) or _USB_DP_LETTER_RE.search(raw):
        return "+"
    if _USB_DM_SIGN_RE.search(raw) or _USB_DM_LETTER_RE.search(raw):
        return "-"
    return None


def is_usb_cc_name(name: str) -> bool:
    """Return whether a net name denotes a USB-C CC (configuration channel) line."""
    return bool(_USB_CC_RE.search(name.strip()))


# --- Switching regulator / SMPS (issue #205, domain rule pack) ---------------
# Explicit [^A-Z0-9] boundaries are used (not \b) because regex word boundaries
# treat "_" as a word char, and KiCad net names are underscore-heavy
# (e.g. "SW_BST", "BUCK_FB"). Bare "BOOT" is intentionally excluded so MCU
# boot-mode straps (BOOT0/BOOT1/BOOTSEL) do not trip the bootstrap rule.
_SMPS_BOOTSTRAP_RE = re.compile(r"(?:^|[^A-Z0-9])(?:V?BST|BOOTSTRAP)(?:[^A-Z0-9]|$)", re.IGNORECASE)
_SMPS_FEEDBACK_RE = re.compile(r"(?:^|[^A-Z0-9])(?:V?FB|FEEDBACK)(?:[^A-Z0-9]|$)", re.IGNORECASE)


def is_bootstrap_name(name: str) -> bool:
    """Return whether a net name denotes a switching-regulator bootstrap (BST) node."""
    return bool(_SMPS_BOOTSTRAP_RE.search(name.strip()))


def is_feedback_name(name: str) -> bool:
    """Return whether a net name denotes a regulator feedback (FB) node."""
    return bool(_SMPS_FEEDBACK_RE.search(name.strip()))


# --- Ethernet / MII differential pairs (issue #205, domain rule pack) --------
# An Ethernet/MDI lane base (TX/RX/TD/RD/MDI/TRD/MX, with optional lane digits)
# carrying an explicit polarity (+/-, _P/_N, trailing P/N). The required polarity
# is what excludes single-ended UART TX/RX and MII control lines (TXEN, RXDV).
_ETH_PAIR_RE = re.compile(
    r"^(?:ETH(?:ERNET)?[ _-]*)?(?:PHY[ _-]*)?((?:MDI|MX|TRD|TX|RX|TD|RD)\d*)[ _-]*([+\-PN])$",
    re.IGNORECASE,
)


def ethernet_pair_key(name: str) -> tuple[str, str] | None:
    """Return ``(base, polarity)`` for an Ethernet diff-pair net, else ``None``.

    ``polarity`` is canonicalized to ``"P"``/``"N"`` (so ``TX+`` and ``TX_P`` are
    the same half). ``base`` is upper-cased and keeps any lane digit, e.g.
    ``("MDI0", "P")`` for ``MDI0_P``.
    """
    match = _ETH_PAIR_RE.match(name.strip())
    if match is None:
        return None
    base = match.group(1).upper()
    raw = match.group(2).upper()
    return base, ("P" if raw in {"+", "P"} else "N")


def is_external_port_name(name: str) -> bool:
    """Return whether a net name strongly implies an externally exposed port."""
    return bool(
        usb_data_polarity(name)
        or is_usb_cc_name(name)
        or is_can_name(name)
        or ethernet_pair_key(name)
        or _EXTERNAL_PORT_TOKEN_RE.search(name.strip())
    )


def _pin_value(pin: Mapping[str, Any]) -> str:
    return str(pin.get("value", "") or "")


def _net_has_protection_evidence(net: NetView) -> bool:
    """Return whether a net carries ESD/TVS/fuse/reverse-protection evidence."""
    for pin in net.get("pins", []):
        ref = str(pin.get("reference", ""))
        value = _pin_value(pin)
        if _PROTECTION_REF_RE.match(ref):
            return True
        if _PROTECTION_VALUE_RE.search(value):
            return True
    return False


def merge_nets_by_name(nets: Iterable[NetView]) -> list[dict[str, Any]]:
    """Union nets that share a name so cross-sheet named rails analyze as one net.

    Named nets (power symbols, global/hierarchical labels) are electrically the
    same net across sheets even when they appear as separate connectivity groups
    per page. Unnamed groups are passed through unchanged.
    """
    merged: dict[str, dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for net in nets:
        names = _net_names(net)
        pins = [dict(pin) for pin in net.get("pins", [])]
        if not names:
            passthrough.append({"names": [], "pins": pins})
            continue
        key = min(name.upper() for name in names)
        bucket = merged.setdefault(key, {"names": set(), "pins": []})
        bucket["names"].update(names)
        bucket["pins"].extend(pins)
    result = [{"names": sorted(b["names"]), "pins": b["pins"]} for b in merged.values()]
    result.extend(passthrough)
    return result


def _rule_i2c_pullups(nets: Sequence[NetView]) -> list[Finding]:
    findings: list[Finding] = []
    for net in nets:
        names = _net_names(net)
        i2c_names = [name for name in names if is_i2c_name(name)]
        if not i2c_names:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        label = i2c_names[0]
        ics = _net_refs(net, _IC_RE)
        findings.append(
            Finding(
                rule_id="i2c_pullups",
                severity="warning",
                message=(
                    f"I2C net '{label}' has no pull-up resistor on it. "
                    "I2C SDA/SCL are open-drain and require pull-ups (typically 2.2k-10k) "
                    "to the bus voltage."
                ),
                refs=tuple(ics) or (label,),
            )
        )
    return findings


def _rule_power_rail_decoupling(nets: Sequence[NetView]) -> list[Finding]:
    findings: list[Finding] = []
    for net in nets:
        names = _net_names(net)
        rail_names = [name for name in names if is_supply_rail_name(name)]
        if not rail_names:
            continue
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_refs(net, _CAP_RE):
            continue
        label = rail_names[0]
        findings.append(
            Finding(
                rule_id="power_rail_decoupling",
                severity="warning",
                message=(
                    f"Supply rail '{label}' feeds {', '.join(ics)} but has no decoupling "
                    "capacitor on the rail. Every IC supply pin should have a local "
                    "decoupling capacitor (typically 100nF per pin)."
                ),
                refs=tuple(ics),
            )
        )
    return findings


def _rule_reset_pullup(nets: Sequence[NetView]) -> list[Finding]:
    findings: list[Finding] = []
    for net in nets:
        names = _net_names(net)
        reset_names = [name for name in names if is_reset_name(name)]
        if not reset_names:
            continue
        # Only flag reset lines that actually reach an IC; ignore stray test points.
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        label = reset_names[0]
        findings.append(
            Finding(
                rule_id="reset_pullup",
                severity="warning",
                message=(
                    f"Reset net '{label}' on {', '.join(ics)} has no pull resistor. "
                    "A reset line needs a defined idle level (active-low resets typically "
                    "use a pull-up, often with an RC for noise immunity)."
                ),
                refs=tuple(ics),
            )
        )
    return findings


def _rule_crystal_load_caps(nets: Sequence[NetView]) -> list[Finding]:
    # Collect, per crystal reference, whether any net it touches carries a capacitor.
    crystal_nets: dict[str, bool] = {}
    for net in nets:
        crystals = _net_refs(net, _CRYSTAL_RE)
        if not crystals:
            continue
        has_cap = bool(_net_refs(net, _CAP_RE))
        for crystal in crystals:
            crystal_nets[crystal] = crystal_nets.get(crystal, False) or has_cap
    findings: list[Finding] = []
    for crystal, has_cap in sorted(crystal_nets.items()):
        if has_cap:
            continue
        findings.append(
            Finding(
                rule_id="crystal_load_caps",
                severity="warning",
                message=(
                    f"Crystal/resonator '{crystal}' has no load capacitors on its pins. "
                    "A quartz crystal needs matched load capacitors (value per the crystal's "
                    "specified load capacitance) to oscillate reliably."
                ),
                refs=(crystal,),
            )
        )
    return findings


def _rule_decoupling_count(nets: Sequence[NetView]) -> list[Finding]:
    """Flag ICs with fewer decoupling caps than power pins (partial decoupling).

    Uses pin electrical type: counts ``power_in`` pins that sit on a positive
    supply rail per IC, and the distinct capacitors on those rails. The fully
    undecoupled case (zero caps) is left to ``power_rail_decoupling`` so the two
    rules never double-report; this one catches the 0 < caps < power-pins gap.
    """
    power_pins: dict[str, int] = {}
    rail_caps: dict[str, set[str]] = {}
    for net in nets:
        if not any(is_supply_rail_name(name) for name in _net_names(net)):
            continue
        caps_on_net = set(_net_refs(net, _CAP_RE))
        ics_on_net: set[str] = set()
        for pin in net.get("pins", []):
            ref = str(pin.get("reference", ""))
            if _IC_RE.match(ref) and str(pin.get("etype", "")) == "power_in":
                power_pins[ref] = power_pins.get(ref, 0) + 1
                ics_on_net.add(ref)
        for ic in ics_on_net:
            rail_caps.setdefault(ic, set()).update(caps_on_net)

    findings: list[Finding] = []
    for ic in sorted(power_pins):
        pins = power_pins[ic]
        caps = len(rail_caps.get(ic, set()))
        if 0 < caps < pins:
            findings.append(
                Finding(
                    rule_id="decoupling_count",
                    severity="warning",
                    message=(
                        f"{ic} has {pins} supply pin(s) but only {caps} decoupling "
                        "capacitor(s) on its rails. Aim for roughly one ~100nF "
                        "capacitor per power pin, placed close to the pin."
                    ),
                    refs=(ic,),
                )
            )
    return findings


def _rule_nc_pin_connected(nets: Sequence[NetView]) -> list[Finding]:
    """Flag pins whose symbol marks them no-connect but which are wired to a net."""
    findings: list[Finding] = []
    for net in nets:
        pins = net.get("pins", [])
        if len(pins) < 2:
            continue
        for pin in pins:
            if str(pin.get("etype", "")) != "no_connect":
                continue
            ref = str(pin.get("reference", ""))
            number = str(pin.get("pin", ""))
            findings.append(
                Finding(
                    rule_id="nc_pin_connected",
                    severity="warning",
                    message=(
                        f"{ref} pin {number} is a no-connect (NC) pin but is wired to "
                        "other pins. NC pins must be left unconnected."
                    ),
                    refs=(ref,),
                )
            )
    return findings


def _rule_can_bus_termination(nets: Sequence[NetView]) -> list[Finding]:
    findings: list[Finding] = []
    for net in nets:
        can_names = [name for name in _net_names(net) if is_can_name(name)]
        if not can_names:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        findings.append(
            Finding(
                rule_id="can_bus_termination",
                severity="warning",
                message=(
                    f"CAN bus net '{can_names[0]}' has no termination resistor. A CAN bus "
                    "needs 120-ohm termination at both physical ends of the bus."
                ),
                refs=(can_names[0],),
            )
        )
    return findings


def _rule_interrupt_pullup(nets: Sequence[NetView]) -> list[Finding]:
    findings: list[Finding] = []
    for net in nets:
        int_names = [name for name in _net_names(net) if is_active_low_interrupt_name(name)]
        if not int_names:
            continue
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        findings.append(
            Finding(
                rule_id="interrupt_pullup",
                severity="warning",
                message=(
                    f"Active-low interrupt net '{int_names[0]}' on {', '.join(ics)} has no "
                    "pull-up resistor. Open-drain interrupt lines need a pull-up to their rail."
                ),
                refs=tuple(ics),
            )
        )
    return findings


def _rule_conflicting_supply_rails(nets: Sequence[NetView]) -> list[Finding]:
    """Flag a single net carrying two different supply voltages (rails shorted).

    Power-rail naming consistency (Rule 13/14): when one connectivity group holds
    more than one explicit rail voltage — e.g. both ``+3V3`` and ``+5V`` — the
    rails are electrically tied together, which is a short. Only rails with a
    parseable numeric voltage are compared, so value-less aliases like ``VCC`` or
    ``VBUS`` never trip this rule.
    """
    findings: list[Finding] = []
    for net in nets:
        by_voltage: dict[float, str] = {}
        for name in _net_names(net):
            if not is_supply_rail_name(name):
                continue
            voltage = rail_voltage(name)
            if voltage is None:
                continue
            by_voltage.setdefault(round(voltage, 3), name)
        if len(by_voltage) < 2:
            continue
        ordered = sorted(by_voltage.items())
        rail_names = [name for _, name in ordered]
        ics = _net_refs(net, _IC_RE)
        findings.append(
            Finding(
                rule_id="conflicting_supply_rails",
                severity="error",
                message=(
                    f"One net carries conflicting supply rails {', '.join(rail_names)} "
                    f"({', '.join(format(v, 'g') + 'V' for v, _ in ordered)}). These rails "
                    "are on the same net and are shorted together — give each rail its own net."
                ),
                refs=tuple(ics) or tuple(rail_names),
            )
        )
    return findings


def _collect_usb_diff_pair_nets(
    nets: Sequence[NetView],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    present: dict[str, str] = {}
    refs_by_polarity: dict[str, list[str]] = {"+": [], "-": []}
    for net in nets:
        for name in _net_names(net):
            polarity = usb_data_polarity(name)
            if polarity is None:
                continue
            present.setdefault(polarity, name)
            for ref in _net_refs(net, _IC_RE) + _net_refs(net, _CONNECTOR_RE):
                if ref not in refs_by_polarity[polarity]:
                    refs_by_polarity[polarity].append(ref)
    return present, refs_by_polarity


def _rule_usb_diff_pair_complete(nets: Sequence[NetView]) -> list[Finding]:
    """Flag a USB design that wires only one half of the D+/D- data pair.

    USB data is a differential pair: D+ and D- must both be present. When the
    design carries one polarity but not its complement, the other half is missing
    (or mis-named), which breaks the link. Fires once per missing polarity.
    """
    present, refs_by_polarity = _collect_usb_diff_pair_nets(nets)
    if len(present) != 1:
        return []  # neither half, or both halves present -> nothing to flag
    have = next(iter(present))
    missing = "-" if have == "+" else "+"
    label = present[have]
    return [
        Finding(
            rule_id="usb_diff_pair_complete",
            severity="warning",
            message=(
                f"USB data net '{label}' (D{have}) has no matching D{missing} half. "
                "USB D+/D- form a differential pair and must both be routed; check the "
                "complement net is present and named consistently."
            ),
            refs=tuple(refs_by_polarity[have]) or (label,),
        )
    ]


def _rule_usbc_cc_resistors(nets: Sequence[NetView]) -> list[Finding]:
    """Flag a USB-C CC line that reaches a part but carries no configuration resistor.

    CC1/CC2 need a configuration resistor — Rd (5.1k to GND) on a sink/UFP, or Rp
    on a source — for the port to be detected and to advertise current. A CC net
    that touches a connector or IC but has no resistor is almost always missing it.
    """
    findings: list[Finding] = []
    for net in nets:
        cc_names = [name for name in _net_names(net) if is_usb_cc_name(name)]
        if not cc_names:
            continue
        parts = _net_refs(net, _IC_RE) + _net_refs(net, _CONNECTOR_RE)
        if not parts:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        findings.append(
            Finding(
                rule_id="usbc_cc_resistors",
                severity="warning",
                message=(
                    f"USB-C CC net '{cc_names[0]}' on {', '.join(parts)} has no configuration "
                    "resistor. CC pins need Rd (5.1k to GND, sink) or Rp (source) — without it "
                    "the port will not be detected."
                ),
                refs=tuple(parts),
            )
        )
    return findings


def _collect_ethernet_lanes(nets: Sequence[NetView]) -> dict[str, dict[str, Any]]:
    lanes: dict[str, dict[str, Any]] = {}
    for net in nets:
        for name in _net_names(net):
            key = ethernet_pair_key(name)
            if key is None:
                continue
            base, polarity = key
            lane = lanes.setdefault(base, {"polarities": set(), "labels": {}, "refs": []})
            lane["polarities"].add(polarity)
            lane["labels"].setdefault(polarity, name)
            for ref in _net_refs(net, _IC_RE) + _net_refs(net, _CONNECTOR_RE):
                if ref not in lane["refs"]:
                    lane["refs"].append(ref)

    return lanes


def _rule_ethernet_diff_pairs(nets: Sequence[NetView]) -> list[Finding]:
    """Flag an Ethernet/MDI differential lane wired with only one polarity half.

    Each lane base (e.g. ``TX``, ``MDI0``, ``TRD1``) must carry both a P and an N
    half. When only one polarity is present across the design, the complement is
    missing or mis-named. Single-ended UART ``TX``/``RX`` carry no polarity and so
    are never considered. Fires once per incomplete lane.
    """
    lanes = _collect_ethernet_lanes(nets)

    findings: list[Finding] = []
    for base in sorted(lanes):
        lane = lanes[base]
        if len(lane["polarities"]) != 1:
            continue
        have = next(iter(lane["polarities"]))
        have_sign, missing_sign = ("+", "-") if have == "P" else ("-", "+")
        label = lane["labels"][have]
        findings.append(
            Finding(
                rule_id="ethernet_diff_pair",
                severity="warning",
                message=(
                    f"Differential net '{label}' ({base}{have_sign}) has no matching "
                    f"{base}{missing_sign} half. Ethernet/MDI lanes (TX±, RX±, MDI±) must be "
                    "wired as complete differential pairs."
                ),
                refs=tuple(lane["refs"]) or (label,),
            )
        )
    return findings


def _rule_smps_bootstrap_cap(nets: Sequence[NetView]) -> list[Finding]:
    """Flag a switching-regulator bootstrap (BST) node with no bootstrap capacitor."""
    findings: list[Finding] = []
    for net in nets:
        bst_names = [name for name in _net_names(net) if is_bootstrap_name(name)]
        if not bst_names:
            continue
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_refs(net, _CAP_RE):
            continue
        findings.append(
            Finding(
                rule_id="smps_bootstrap_cap",
                severity="warning",
                message=(
                    f"Bootstrap net '{bst_names[0]}' on {', '.join(ics)} has no bootstrap "
                    "capacitor. A switching regulator's BST pin needs a small capacitor "
                    "(often 100nF) to the switch node to drive the high-side gate."
                ),
                refs=tuple(ics),
            )
        )
    return findings


def _rule_smps_feedback_divider(nets: Sequence[NetView]) -> list[Finding]:
    """Flag a regulator feedback (FB) node that reaches an IC with no resistor divider."""
    findings: list[Finding] = []
    for net in nets:
        fb_names = [name for name in _net_names(net) if is_feedback_name(name)]
        if not fb_names:
            continue
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_refs(net, _RESISTOR_RE):
            continue
        findings.append(
            Finding(
                rule_id="smps_feedback_divider",
                severity="warning",
                message=(
                    f"Feedback net '{fb_names[0]}' on {', '.join(ics)} has no resistor. An "
                    "adjustable regulator sets its output with a feedback resistor divider; "
                    "check the divider is present (a fixed-output part can ignore this)."
                ),
                refs=tuple(ics),
            )
        )
    return findings


def _rule_external_port_protection(nets: Sequence[NetView]) -> list[Finding]:
    """Flag externally exposed connector nets with no ESD/TVS/reverse-protection evidence."""
    findings: list[Finding] = []
    for net in nets:
        external_names = [name for name in _net_names(net) if is_external_port_name(name)]
        if not external_names:
            continue
        connectors = _net_refs(net, _CONNECTOR_RE)
        if not connectors:
            continue
        ics = _net_refs(net, _IC_RE)
        if not ics:
            continue
        if _net_has_protection_evidence(net):
            continue
        findings.append(
            Finding(
                rule_id="external_port_protection",
                severity="warning",
                message=(
                    f"External port net '{external_names[0]}' reaches connector "
                    f"{', '.join(connectors)} and IC {', '.join(ics)} with no ESD/TVS, "
                    "fuse, or reverse-polarity protection evidence. Add appropriate "
                    "protection at the connector or document why the port is internal."
                ),
                refs=(*connectors, *ics),
            )
        )
    return findings


# Registry of active rules. Append new pure ``(nets) -> [Finding]`` callables here.
DESIGN_RULES: tuple[Callable[[Sequence[NetView]], list[Finding]], ...] = (
    _rule_i2c_pullups,
    _rule_power_rail_decoupling,
    _rule_reset_pullup,
    _rule_crystal_load_caps,
    _rule_decoupling_count,
    _rule_nc_pin_connected,
    _rule_can_bus_termination,
    _rule_interrupt_pullup,
    _rule_conflicting_supply_rails,
    _rule_usb_diff_pair_complete,
    _rule_usbc_cc_resistors,
    _rule_ethernet_diff_pairs,
    _rule_smps_bootstrap_cap,
    _rule_smps_feedback_divider,
    _rule_external_port_protection,
)


def run_schematic_design_rules(nets: Iterable[NetView]) -> list[Finding]:
    """Run every design rule over the (name-merged) net model and return findings."""
    merged = merge_nets_by_name(nets)
    findings: list[Finding] = []
    for rule in DESIGN_RULES:
        findings.extend(rule(merged))
    findings.sort(key=Finding.sort_key)
    return findings
