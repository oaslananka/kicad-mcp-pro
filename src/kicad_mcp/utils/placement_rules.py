"""Constraint-driven placement critic for KiCad PCB layouts (issue #203).

Pure-domain engine: takes the footprint map produced by ``_parse_board_footprint_blocks``
and returns structured findings with no KiCad dependency, making it fully unit-testable.

Rules implemented
-----------------
PLR-001  Decoupling-cap-to-power-pin distance: each bypass cap should be ≤ 5 mm from
         the nearest IC it serves.
PLR-002  Crystal-to-IC distance: oscillator crystals should be ≤ 8 mm from the
         companion MCU/IC to minimise parasitic trace inductance.
PLR-003  SMPS hot-loop area: switch, input cap, and output cap should form a tight
         loop; if the bounding box of those parts exceeds the threshold, EMI risk rises.
PLR-004  Analog / digital region mixing: components that carry AGND / AVCC nets should
         be separated from components that carry only digital VCC / DVDD nets.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

FootprintMap = dict[str, dict[str, Any]]

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

_CAP_RE = re.compile(r"^C\d", re.IGNORECASE)
_IC_RE = re.compile(r"^(?:U|IC)\d", re.IGNORECASE)
_CRYSTAL_RE = re.compile(r"^(?:Y|X)\d", re.IGNORECASE)
_INDUCTOR_RE = re.compile(r"^L\d", re.IGNORECASE)

_DECAP_VALUE_RE = re.compile(
    r"(?:100n|0\.1[uµ]|1[uµ]|10[uµ]|4[,.]7u|0\.01u|(?:10|22|47)nF|bypass|decoup)",
    re.IGNORECASE,
)
_CRYSTAL_VALUE_RE = re.compile(r"\d+\s*[mk]hz", re.IGNORECASE)

_SMPS_VALUE_RE = re.compile(
    r"(?:LM25\d\d|MP2\d{3}|XL\d{4}|TPS\d{4}|LT\d{4}|MAX\d{4}|"
    r"buck|boost|flyback|converter|switcher|regul)",
    re.IGNORECASE,
)

_ANALOG_NET_RE = re.compile(r"(?:^|[^A-Z])(AGND|AVCC|AVDD|AVSS|AREF|VREF|VDDA|GNDA)(?:[^A-Z]|$)")
_DIGITAL_SUPPLY_RE = re.compile(
    r"(?:^|[^A-Z])(DVDD|DVCC|VCORE|VDD_CORE|VCC_CORE|VCC_DIG|VDD_DIG)(?:[^A-Z]|$)"
)


@dataclass(frozen=True)
class PlacementThresholds:
    decap_max_distance_mm: float = 5.0
    crystal_max_distance_mm: float = 8.0
    smps_hotloop_max_area_mm2: float = 200.0
    analog_digital_min_separation_mm: float = 5.0


@dataclass(frozen=True)
class PlacementFinding:
    rule_id: str
    severity: str
    message: str
    refs: tuple[str, ...] = field(default_factory=tuple)
    detail: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[int, str, str]:
        return (_SEVERITY_ORDER.get(self.severity, 9), self.rule_id, self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "refs": list(self.refs),
            **self.detail,
        }


def _dist(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax: float | None = a.get("x_mm")
    ay: float | None = a.get("y_mm")
    bx: float | None = b.get("x_mm")
    by: float | None = b.get("y_mm")
    if ax is None or ay is None or bx is None or by is None:
        return float("inf")
    return math.hypot(ax - bx, ay - by)


def _has_any_net(fp: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    return any(pattern.search(n) for n in fp.get("net_names", []))


def _is_decap(ref: str, fp: dict[str, Any]) -> bool:
    return bool(_CAP_RE.match(ref) and _DECAP_VALUE_RE.search(fp.get("value", "")))


def _is_crystal(ref: str, fp: dict[str, Any]) -> bool:
    return bool(
        _CRYSTAL_RE.match(ref)
        or (not _CAP_RE.match(ref) and _CRYSTAL_VALUE_RE.search(fp.get("value", "")))
    )


def _is_ic(ref: str) -> bool:
    return bool(_IC_RE.match(ref))


def _is_smps_ic(ref: str, fp: dict[str, Any]) -> bool:
    return bool(_IC_RE.match(ref) and _SMPS_VALUE_RE.search(fp.get("value", "")))


def _is_inductor(ref: str) -> bool:
    return bool(_INDUCTOR_RE.match(ref))


def _check_decap_distance(
    footprints: FootprintMap, cfg: PlacementThresholds
) -> list[PlacementFinding]:
    findings: list[PlacementFinding] = []
    decaps = {r: fp for r, fp in footprints.items() if _is_decap(r, fp)}
    ics = {r: fp for r, fp in footprints.items() if _is_ic(r)}
    if not decaps or not ics:
        return findings
    for cap_ref, cap_fp in decaps.items():
        nearest_ref = min(ics, key=lambda r: _dist(cap_fp, ics[r]))
        d = _dist(cap_fp, ics[nearest_ref])
        if d > cfg.decap_max_distance_mm:
            findings.append(
                PlacementFinding(
                    rule_id="PLR-001",
                    severity="warning",
                    message=(
                        f"Decoupling cap {cap_ref} is {d:.1f} mm from nearest IC {nearest_ref} "
                        f"(threshold {cfg.decap_max_distance_mm} mm). "
                        "Move closer to reduce power-rail noise."
                    ),
                    refs=(cap_ref, nearest_ref),
                    detail={
                        "distance_mm": round(d, 3),
                        "threshold_mm": cfg.decap_max_distance_mm,
                    },
                )
            )
    return findings


def _check_crystal_distance(
    footprints: FootprintMap, cfg: PlacementThresholds
) -> list[PlacementFinding]:
    findings: list[PlacementFinding] = []
    crystals = {r: fp for r, fp in footprints.items() if _is_crystal(r, fp)}
    ics = {r: fp for r, fp in footprints.items() if _is_ic(r)}
    if not crystals or not ics:
        return findings
    for xtal_ref, xtal_fp in crystals.items():
        nearest_ref = min(ics, key=lambda r: _dist(xtal_fp, ics[r]))
        d = _dist(xtal_fp, ics[nearest_ref])
        if d > cfg.crystal_max_distance_mm:
            findings.append(
                PlacementFinding(
                    rule_id="PLR-002",
                    severity="warning",
                    message=(
                        f"Crystal {xtal_ref} is {d:.1f} mm from nearest IC {nearest_ref} "
                        f"(threshold {cfg.crystal_max_distance_mm} mm). "
                        "Long crystal traces add parasitic inductance"
                        " and hurt oscillator stability."
                    ),
                    refs=(xtal_ref, nearest_ref),
                    detail={
                        "distance_mm": round(d, 3),
                        "threshold_mm": cfg.crystal_max_distance_mm,
                    },
                )
            )
    return findings


def _check_smps_hot_loop(
    footprints: FootprintMap, cfg: PlacementThresholds
) -> list[PlacementFinding]:
    findings: list[PlacementFinding] = []
    smps_ics = {r: fp for r, fp in footprints.items() if _is_smps_ic(r, fp)}
    inductors = {r: fp for r, fp in footprints.items() if _is_inductor(r)}
    caps = {
        r: fp for r, fp in footprints.items() if _CAP_RE.match(r) and fp.get("x_mm") is not None
    }
    for ic_ref, ic_fp in smps_ics.items():
        nearby: list[dict[str, Any]] = [ic_fp]
        nearby_refs = [ic_ref]
        for l_ref, l_fp in inductors.items():
            if _dist(ic_fp, l_fp) <= 30.0:
                nearby.append(l_fp)
                nearby_refs.append(l_ref)
        for c_ref, c_fp in caps.items():
            if _dist(ic_fp, c_fp) <= 20.0:
                nearby.append(c_fp)
                nearby_refs.append(c_ref)
        if len(nearby) < 3:
            continue
        xs = [float(fp["x_mm"]) for fp in nearby]
        ys = [float(fp["y_mm"]) for fp in nearby]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if area > cfg.smps_hotloop_max_area_mm2:
            findings.append(
                PlacementFinding(
                    rule_id="PLR-003",
                    severity="warning",
                    message=(
                        f"SMPS hot-loop around {ic_ref} spans {area:.0f} mm² "
                        f"(threshold {cfg.smps_hotloop_max_area_mm2} mm²). "
                        "Tighten the switch IC / inductor / input-cap cluster to reduce EMI."
                    ),
                    refs=tuple(nearby_refs),
                    detail={
                        "hot_loop_area_mm2": round(area, 1),
                        "threshold_mm2": cfg.smps_hotloop_max_area_mm2,
                    },
                )
            )
    return findings


def _check_analog_digital_mixing(
    footprints: FootprintMap, cfg: PlacementThresholds
) -> list[PlacementFinding]:
    findings: list[PlacementFinding] = []
    analog_fps = {r: fp for r, fp in footprints.items() if _has_any_net(fp, _ANALOG_NET_RE)}
    digital_fps = {r: fp for r, fp in footprints.items() if _has_any_net(fp, _DIGITAL_SUPPLY_RE)}
    if not analog_fps or not digital_fps:
        return findings
    close_pairs: list[tuple[str, str, float]] = []
    for a_ref, a_fp in analog_fps.items():
        for d_ref, d_fp in digital_fps.items():
            d = _dist(a_fp, d_fp)
            if d < cfg.analog_digital_min_separation_mm:
                close_pairs.append((a_ref, d_ref, d))
    if close_pairs:
        closest = min(close_pairs, key=lambda t: t[2])
        refs = tuple(sorted({r for t in close_pairs for r in (t[0], t[1])}))
        findings.append(
            PlacementFinding(
                rule_id="PLR-004",
                severity="warning",
                message=(
                    f"Analog and digital components are mixed: {len(close_pairs)} pair(s) within "
                    f"{cfg.analog_digital_min_separation_mm} mm. "
                    f"Closest: {closest[0]} ↔ {closest[1]} at {closest[2]:.1f} mm. "
                    "Separate analog and digital regions to reduce noise coupling."
                ),
                refs=refs,
                detail={
                    "mixing_pair_count": len(close_pairs),
                    "closest_pair": [closest[0], closest[1]],
                    "closest_distance_mm": round(closest[2], 3),
                    "threshold_mm": cfg.analog_digital_min_separation_mm,
                },
            )
        )
    return findings


def critique_placement(
    footprints: FootprintMap,
    thresholds: PlacementThresholds | None = None,
) -> list[PlacementFinding]:
    """Run all placement rules and return findings sorted by severity."""
    cfg = thresholds or PlacementThresholds()
    all_findings: list[PlacementFinding] = []
    all_findings.extend(_check_decap_distance(footprints, cfg))
    all_findings.extend(_check_crystal_distance(footprints, cfg))
    all_findings.extend(_check_smps_hot_loop(footprints, cfg))
    all_findings.extend(_check_analog_digital_mixing(footprints, cfg))
    return sorted(all_findings, key=lambda f: f.sort_key())
