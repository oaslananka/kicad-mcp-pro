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
        lines: list[str] = [
            "# Bring-Up Test Plan",
            f"Generated: {self.now().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]

        lines += [
            "## 1. Power-On Sequence",
            "",
            "**Prerequisites:** Board assembled, no loads connected, current-limited PSU.",
            "",
        ]
        if intent.power_rails:
            lines.append("| Step | Rail | Target (V) | Max (A) | Tolerance | Action |")
            lines.append("|------|------|-----------|---------|-----------|--------|")
            for i, rail in enumerate(intent.power_rails, start=1):
                v_min = rail.voltage_v * (1 - rail.tolerance_pct / 100)
                v_max = rail.voltage_v * (1 + rail.tolerance_pct / 100)
                lines.append(
                    f"| {i} | {rail.name} | {rail.voltage_v:.2f}V | "
                    f"{rail.current_max_a:.1f}A | "
                    f"[{v_min:.3f}, {v_max:.3f}]V | "
                    f"Measure at {rail.source_ref or 'source'}, check no smoke |"
                )
        else:
            lines += [
                "- [ ] Apply primary supply — measure and verify voltage within spec.",
                "- [ ] Confirm current draw is within expected range.",
                "- [ ] Verify all power rails reach target voltage.",
            ]

        lines += ["", "## 2. Critical-Net Continuity", ""]
        if intent.critical_nets:
            for net in intent.critical_nets[:20]:
                lines.append(f"- [ ] Probe `{net}` — verify continuity from source to load.")
        else:
            lines.append("- [ ] (No critical nets defined in design intent.)")

        lines += ["", "## 3. Interface Link-Up Tests", ""]
        if intent.interfaces:
            for iface in intent.interfaces:
                kind = iface.kind
                refs_str = ", ".join(iface.refs[:5]) if iface.refs else "(see schematic)"
                lines.append(f"### {kind.upper()} ({refs_str})")
                interface_checks: dict[str, list[str]] = {
                    "usb2": [
                        "Connect USB analyzer or host device.",
                        "Verify USB enumeration (lsusb or device manager).",
                        "Run USB compliance test tool if available.",
                    ],
                    "usb3": [
                        "Connect USB 3.x SuperSpeed host.",
                        "Verify SuperSpeed enumeration and link training.",
                        "Measure eye diagram at connector.",
                    ],
                    "ethernet_1000": [
                        "Connect Ethernet cable to link partner.",
                        "Verify 1000BASE-T auto-negotiation (link LED).",
                        "Run iperf3 bidirectional throughput test.",
                    ],
                    "pcie_g3": [
                        "Install into PCIe x1/x4/x16 slot.",
                        "Verify PCIe link training (lspci -vvv).",
                        "Check link width and speed negotiation.",
                    ],
                    "can": [
                        "Connect to CAN bus with 120ohm termination.",
                        "Send/receive test frames with CAN analyzer.",
                        "Verify no error frames at operational baud rate.",
                    ],
                    "i2c": [
                        "Scan I2C bus — verify device ACKs (i2cdetect -y 1).",
                        "Read/write device registers to confirm communication.",
                    ],
                    "uart": [
                        "Connect UART terminal (115200 8N1).",
                        "Verify TX loopback and receive data.",
                    ],
                    "swd": [
                        "Connect debug probe (J-Link / ST-Link / DAPLink).",
                        "Verify MCU detected and halts cleanly.",
                        "Flash test firmware and verify execution.",
                    ],
                }
                checks = interface_checks.get(
                    kind,
                    [f"Verify {kind} communication with appropriate test equipment."],
                )
                for check in checks:
                    lines.append(f"  - [ ] {check}")
                lines.append("")
        else:
            lines.append("- [ ] (No interfaces defined in design intent.)")

        lines += [
            "",
            "## 4. Visual Inspection",
            "",
            "- [ ] Verify all connectors seated correctly.",
            "- [ ] Inspect for solder bridges on fine-pitch components.",
            "- [ ] Verify correct component orientation (polarised capacitors, diodes, ICs).",
            "- [ ] Check mechanical mounting and keep-out clearances.",
        ]

        if intent.compliance:
            lines += ["", "## 5. Compliance Pre-Checks", ""]
            for target in intent.compliance:
                lines.append(f"- [ ] Prepare for **{target.kind.upper()}** certification.")
                if target.notes:
                    lines.append(f"  Note: {target.notes}")

        text = "\n".join(lines)
        if not output_path:
            return text

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
