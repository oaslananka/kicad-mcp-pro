"""FastMCP-independent manufacturing bring-up test-plan generation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class PowerRailLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def voltage_v(self) -> float: ...

    @property
    def current_max_a(self) -> float: ...

    @property
    def tolerance_pct(self) -> float: ...

    @property
    def source_ref(self) -> str: ...


class InterfaceLike(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def refs(self) -> Sequence[str]: ...


class ComplianceLike(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def notes(self) -> str: ...


class DesignIntentLike(Protocol):
    @property
    def power_rails(self) -> Sequence[PowerRailLike]: ...

    @property
    def critical_nets(self) -> Sequence[str]: ...

    @property
    def interfaces(self) -> Sequence[InterfaceLike]: ...

    @property
    def compliance(self) -> Sequence[ComplianceLike]: ...


PathResolver = Callable[[str], Path]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


_INTERFACE_CHECKS: dict[str, tuple[str, ...]] = {
    "usb2": (
        "Connect USB analyzer or host device.",
        "Verify USB enumeration (lsusb or device manager).",
        "Run USB compliance test tool if available.",
    ),
    "usb3": (
        "Connect USB 3.x SuperSpeed host.",
        "Verify SuperSpeed enumeration and link training.",
        "Measure eye diagram at connector.",
    ),
    "ethernet_1000": (
        "Connect Ethernet cable to link partner.",
        "Verify 1000BASE-T auto-negotiation (link LED).",
        "Run iperf3 bidirectional throughput test.",
    ),
    "pcie_g3": (
        "Install into PCIe x1/x4/x16 slot.",
        "Verify PCIe link training (lspci -vvv).",
        "Check link width and speed negotiation.",
    ),
    "can": (
        "Connect to CAN bus with 120ohm termination.",
        "Send/receive test frames with CAN analyzer.",
        "Verify no error frames at operational baud rate.",
    ),
    "i2c": (
        "Scan I2C bus — verify device ACKs (i2cdetect -y 1).",
        "Read/write device registers to confirm communication.",
    ),
    "uart": (
        "Connect UART terminal (115200 8N1).",
        "Verify TX loopback and receive data.",
    ),
    "swd": (
        "Connect debug probe (J-Link / ST-Link / DAPLink).",
        "Verify MCU detected and halts cleanly.",
        "Flash test firmware and verify execution.",
    ),
}


def _append_power_on_section(lines: list[str], rails: Sequence[PowerRailLike]) -> None:
    lines += [
        "## 1. Power-On Sequence",
        "",
        "**Prerequisites:** Board assembled, no loads connected, current-limited PSU.",
        "",
    ]
    if not rails:
        lines += [
            "- [ ] Apply primary supply — measure and verify voltage within spec.",
            "- [ ] Confirm current draw is within expected range.",
            "- [ ] Verify all power rails reach target voltage.",
        ]
        return

    lines.append("| Step | Rail | Target (V) | Max (A) | Tolerance | Action |")
    lines.append("|------|------|-----------|---------|-----------|--------|")
    for index, rail in enumerate(rails, start=1):
        v_min = rail.voltage_v * (1 - rail.tolerance_pct / 100)
        v_max = rail.voltage_v * (1 + rail.tolerance_pct / 100)
        lines.append(
            f"| {index} | {rail.name} | {rail.voltage_v:.2f}V | "
            f"{rail.current_max_a:.1f}A | "
            f"[{v_min:.3f}, {v_max:.3f}]V | "
            f"Measure at {rail.source_ref or 'source'}, check no smoke |"
        )


def _append_critical_net_section(lines: list[str], critical_nets: Sequence[str]) -> None:
    lines += ["", "## 2. Critical-Net Continuity", ""]
    if not critical_nets:
        lines.append("- [ ] (No critical nets defined in design intent.)")
        return

    for net in critical_nets[:20]:
        lines.append(f"- [ ] Probe `{net}` — verify continuity from source to load.")


def _append_interface_section(lines: list[str], interfaces: Sequence[InterfaceLike]) -> None:
    lines += ["", "## 3. Interface Link-Up Tests", ""]
    if not interfaces:
        lines.append("- [ ] (No interfaces defined in design intent.)")
        return

    for interface in interfaces:
        kind = interface.kind
        refs_str = ", ".join(interface.refs[:5]) if interface.refs else "(see schematic)"
        lines.append(f"### {kind.upper()} ({refs_str})")
        checks = _INTERFACE_CHECKS.get(
            kind.lower(),
            (f"Verify {kind} communication with appropriate test equipment.",),
        )
        lines.extend(f"  - [ ] {check}" for check in checks)
        lines.append("")


def _append_visual_inspection_section(lines: list[str]) -> None:
    lines.extend(
        [
            "",
            "## 4. Visual Inspection",
            "",
            "- [ ] Verify all connectors seated correctly.",
            "- [ ] Inspect for solder bridges on fine-pitch components.",
            "- [ ] Verify correct component orientation (polarised capacitors, diodes, ICs).",
            "- [ ] Check mechanical mounting and keep-out clearances.",
        ]
    )


def _append_compliance_section(lines: list[str], compliance: Sequence[ComplianceLike]) -> None:
    if not compliance:
        return

    lines += ["", "## 5. Compliance Pre-Checks", ""]
    for target in compliance:
        lines.append(f"- [ ] Prepare for **{target.kind.upper()}** certification.")
        if target.notes:
            lines.append(f"  Note: {target.notes}")


@dataclass(frozen=True)
class ManufacturingTestPlanService:
    """Render and optionally persist manufacturing bring-up test plans."""

    resolve_output_path: PathResolver
    now: Clock = _utc_now

    def create(
        self,
        intent: DesignIntentLike,
        *,
        output_path: str = "",
        confirm_overwrite: bool = False,
    ) -> str:
        text = self._render(intent)
        if not output_path:
            return text
        return self._persist(text, output_path, confirm_overwrite=confirm_overwrite)

    def _render(self, intent: DesignIntentLike) -> str:
        lines = [
            "# Bring-Up Test Plan",
            f"Generated: {self.now().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]
        _append_power_on_section(lines, intent.power_rails)
        _append_critical_net_section(lines, intent.critical_nets)
        _append_interface_section(lines, intent.interfaces)
        _append_visual_inspection_section(lines)
        _append_compliance_section(lines, intent.compliance)
        return "\n".join(lines)

    def _persist(self, text: str, output_path: str, *, confirm_overwrite: bool) -> str:
        out_file = self.resolve_output_path(output_path)
        if out_file.exists() and not confirm_overwrite:
            return (
                "Refusing to overwrite an existing test plan without confirmation.\n"
                f"- Existing file: {out_file}\n"
                "Rerun with confirm_overwrite=true or choose a different output_path."
            )
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(text, encoding="utf-8")
        return f"Test plan saved to {out_file}\n\n" + text
