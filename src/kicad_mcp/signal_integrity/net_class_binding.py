"""FastMCP-independent interface-to-net-class binding service."""

from __future__ import annotations

from collections.abc import Callable

NetClassRuleWriter = Callable[[str, float, float, float | None], str]

_NET_CLASS_TEMPLATES: dict[str, dict[str, object]] = {
    "usb2": {"clearance": 0.15, "track_width": 0.20, "diff_gap": 0.20},
    "usb3": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.15},
    "usb3_gen2": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.12},
    "pcie_g1": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.18},
    "pcie_g2": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.15},
    "pcie_g3": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.12},
    "pcie_g4": {"clearance": 0.08, "track_width": 0.12, "diff_gap": 0.10},
    "ethernet_100": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.20},
    "ethernet_1000": {"clearance": 0.15, "track_width": 0.20, "diff_gap": 0.15},
    "ethernet_2500": {"clearance": 0.12, "track_width": 0.18, "diff_gap": 0.12},
    "ethernet_10000": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.10},
    "hdmi_1x": {"clearance": 0.12, "track_width": 0.15, "diff_gap": 0.15},
    "hdmi_2x": {"clearance": 0.10, "track_width": 0.12, "diff_gap": 0.12},
    "ddr3": {"clearance": 0.12, "track_width": 0.15, "diff_gap": 0.15},
    "ddr4": {"clearance": 0.10, "track_width": 0.12, "diff_gap": 0.12},
    "ddr5": {"clearance": 0.08, "track_width": 0.10, "diff_gap": 0.10},
    "lvds": {"clearance": 0.10, "track_width": 0.15, "diff_gap": 0.15},
    "can": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.25},
    "canfd": {"clearance": 0.20, "track_width": 0.25, "diff_gap": 0.25},
}


class SignalIntegrityNetClassBindingService:
    """Plan and optionally apply net-class rules for high-speed interfaces."""

    def bind(
        self,
        interfaces: list[dict[str, object]],
        dry_run: bool,
        rule_writer: NetClassRuleWriter,
    ) -> str:
        plan: list[dict[str, object]] = []
        for raw in interfaces:
            kind = str(raw.get("kind", "")).lower()
            template = _NET_CLASS_TEMPLATES.get(kind)
            if template is None:
                continue
            impedance = raw.get("impedance_target_ohm")
            differential = bool(raw.get("differential", False))
            net_prefix = str(raw.get("net_prefix", ""))
            nc_name = f"{kind.upper().replace('_', '_')}"
            plan.append(
                {
                    "net_class": nc_name,
                    "clearance_mm": template["clearance"],
                    "track_width_mm": template["track_width"],
                    "diff_pair_gap_mm": template.get("diff_gap") if differential else None,
                    "impedance_target_ohm": impedance,
                    "net_prefix": net_prefix,
                }
            )

        if not plan:
            return "No high-speed interfaces found that require custom net classes."

        lines = ["## Net Class Binding Plan", ""]
        for entry in plan:
            lines.append(f"### {entry['net_class']}")
            lines.append(f"- Clearance: {entry['clearance_mm']} mm")
            lines.append(f"- Track width: {entry['track_width_mm']} mm")
            if entry.get("diff_pair_gap_mm") is not None:
                lines.append(f"- Diff-pair gap: {entry['diff_pair_gap_mm']} mm")
            if entry.get("impedance_target_ohm") is not None:
                lines.append(f"- Impedance target: {entry['impedance_target_ohm']} ohm")
            if entry.get("net_prefix"):
                lines.append(f"- Net prefix filter: {entry['net_prefix']}")
            lines.append(
                f"  → Call: pcb_set_net_class(net_class={entry['net_class']!r}, "
                f"clearance={entry['clearance_mm']}, "
                f"track_width={entry['track_width_mm']})"
            )
            lines.append("")

        if dry_run:
            lines.append(
                "_Dry-run mode: no changes applied. "
                "Set dry_run=False to write all net class rules to the .kicad_dru file._"
            )
        else:
            written: list[str] = []
            errors: list[str] = []
            rules_file: str = ""
            for entry in plan:
                nc = str(entry["net_class"])
                cl = float(entry["clearance_mm"])  # type: ignore[arg-type]
                tw = float(entry["track_width_mm"])  # type: ignore[arg-type]
                dg = (
                    float(entry["diff_pair_gap_mm"])  # type: ignore[arg-type]
                    if entry.get("diff_pair_gap_mm") is not None
                    else None
                )
                try:
                    rules_file = rule_writer(nc, cl, tw, dg)
                    written.append(nc)
                except Exception as exc:
                    errors.append(f"{nc}: {exc}")

            if written:
                lines.append(f"\n**Applied** {len(written)} net class rule(s) to `{rules_file}`:")
                for nc in written:
                    lines.append(f"  - {nc}")
            if errors:
                lines.append(f"\n**Errors** ({len(errors)}):")
                for error in errors:
                    lines.append(f"  - {error}")
        return "\n".join(lines)
