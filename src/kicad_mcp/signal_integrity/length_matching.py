"""FastMCP-independent length-matching validation service."""

from __future__ import annotations

from collections.abc import Mapping

from ..verdicts import three_level_verdict, warn_max_from


class SignalIntegrityLengthMatchingService:
    """Validate routed net groups against a length-matching tolerance."""

    def validate(
        self,
        net_groups: list[list[str]],
        tolerance_mm: float,
        lengths: Mapping[str, float],
    ) -> str:
        fail_mm = warn_max_from(tolerance_mm)
        lines = [
            f"Length-matching validation (tolerance {tolerance_mm:.3f} mm; "
            f"PASS <= {tolerance_mm:.3f} mm, WARN <= {fail_mm:.3f} mm, "
            f"FAIL > {fail_mm:.3f} mm):"
        ]

        for index, group in enumerate(net_groups, start=1):
            unique_group = [net for net in group if net]
            if not unique_group:
                lines.append(f"- Group {index}: skipped empty group")
                continue

            missing = [net for net in unique_group if net not in lengths]
            if missing:
                lines.append(f"- Group {index}: missing routed tracks for {', '.join(missing)}")
                continue

            samples = [(net, lengths[net]) for net in unique_group]
            shortest_net, shortest_mm = min(samples, key=lambda item: item[1])
            longest_net, longest_mm = max(samples, key=lambda item: item[1])
            spread_mm = longest_mm - shortest_mm
            verdict = three_level_verdict(
                spread_mm,
                pass_max=tolerance_mm,
                warn_max=fail_mm,
            )
            lines.append(
                f"- Group {index} ({verdict}): shortest {shortest_net}={shortest_mm:.3f} mm, "
                f"longest {longest_net}={longest_mm:.3f} mm, spread={spread_mm:.3f} mm"
            )

        return "\n".join(lines)
