"""Net analysis tools: net statistics, net inspector, and board stats CLI wrapper.

FAZ 6.1 — pcb_get_net_statistics
FAZ 6.2 — pcb_net_inspector
FAZ 6.3 — pcb_export_stats
"""

from __future__ import annotations

import json
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from ..connection import KiCadConnectionError, get_board
from ..pcb.pad_mapping import MappedPad, footprint_pads, map_pads_to_footprints
from ..utils.units import nm_to_mm
from .export_support import _get_pcb_file
from .metadata import headless_compatible


def _object_net_name(obj: object) -> str:
    """Return the stable net name for a board object without reading net codes."""
    return str(getattr(getattr(obj, "net", None), "name", "") or "")


def _board_tracks(board: object) -> list[Any]:
    try:
        return list(cast(Any, board).get_tracks())
    except (AttributeError, TypeError, OSError):
        return []


def _board_vias(board: object) -> list[Any]:
    try:
        return list(cast(Any, board).get_vias())
    except (AttributeError, TypeError, OSError):
        return []


def _board_footprints(board: object) -> list[Any]:
    try:
        return list(cast(Any, board).get_footprints())
    except (AttributeError, TypeError, OSError):
        return []


def _mapped_board_pads(board: object) -> list[MappedPad]:
    footprints = _board_footprints(board)
    try:
        pads = list(cast(Any, board).get_pads())
    except (AttributeError, TypeError, OSError):
        pads = [pad for footprint in footprints for pad in footprint_pads(footprint)]
    return map_pads_to_footprints(pads, footprints)


def _collect_nets_from_board() -> list[dict[str, Any]]:
    """Collect net data from a live KiCad IPC connection using net names."""
    try:
        board = get_board()
        nets = board.get_nets()
    except (KiCadConnectionError, OSError, AttributeError) as exc:
        raise RuntimeError(f"Could not retrieve nets from live board: {exc}") from exc

    tracks = _board_tracks(board)
    vias = _board_vias(board)
    mapped_pads = _mapped_board_pads(board)
    pads = [mapped.pad for mapped in mapped_pads]

    result: list[dict[str, Any]] = []
    for net in nets:
        name = str(getattr(net, "name", "") or "")
        net_tracks = [track for track in tracks if _object_net_name(track) == name]
        net_vias = [via for via in vias if _object_net_name(via) == name]
        net_pads = [pad for pad in pads if _object_net_name(pad) == name]
        total_length_mm = 0.0
        for track in net_tracks:
            length = getattr(track, "length", None)
            if length is not None:
                total_length_mm += nm_to_mm(length)
        result.append(
            {
                "code": None,
                "name": name,
                "class_name": getattr(net, "class_name", "") or "",
                "track_count": len(net_tracks),
                "via_count": len(net_vias),
                "pad_count": len(net_pads),
                "total_track_length_mm": round(total_length_mm, 4),
            }
        )
    return result


def _collect_nets_from_file() -> list[dict[str, Any]]:
    """Collect net data by parsing the PCB file as S-expression text."""
    from .board_file import _normalize_board_content

    content = _normalize_board_content(_get_pcb_file().read_text(encoding="utf-8", errors="ignore"))
    nets: list[dict[str, Any]] = []
    seen_codes: set[int] = set()
    for match in __import__("re").finditer(r'\(net\s+(\d+)\s+"((?:\\.|[^"\\])*)"', content):
        code = int(match.group(1))
        name = match.group(2)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        nets.append({"code": code, "name": name, "class_name": ""})
    return nets


def _nets() -> list[dict[str, Any]]:
    try:
        return _collect_nets_from_board()
    except (RuntimeError, KiCadConnectionError):
        return _collect_nets_from_file()


def _file_pad_details(net_name: str) -> list[dict[str, object]]:
    """Return footprint pad details from balanced PCB S-expression blocks."""
    from .board_file import _normalize_board_content, _parse_board_footprint_blocks

    content = _normalize_board_content(_get_pcb_file().read_text(encoding="utf-8", errors="ignore"))
    footprints = _parse_board_footprint_blocks(content)
    details: list[dict[str, object]] = []
    for reference, entry in footprints.items():
        pad_nets = cast(dict[str, str], entry.get("pad_nets", {}))
        layer = str(entry.get("layer_name", "unknown"))
        for pad_number, mapped_net_name in pad_nets.items():
            if mapped_net_name != net_name:
                continue
            details.append(
                {
                    "reference": reference,
                    "pad": pad_number,
                    "layer": layer,
                }
            )
    return details


def register(mcp: FastMCP) -> None:
    """Register net analysis tools."""

    @mcp.tool()
    @headless_compatible
    def pcb_get_net_statistics() -> str:
        """Return statistical data about all nets in the active PCB.

        Includes per-net counts of tracks, vias, pads, and total track length
        (mm).  Uses an active KiCad IPC connection when available; falls back
        to file-level net enumeration.
        """
        nets = _nets()
        if not nets:
            return json.dumps({"nets": [], "count": 0, "summary": {}}, indent=2)

        lengths = [
            float(net.get("total_track_length_mm", 0))
            for net in nets
            if "total_track_length_mm" in net
        ]
        summary: dict[str, object] = {
            "total_nets": len(nets),
            "nets_with_tracks": sum(1 for net in nets if net.get("track_count", 0) > 0),
            "nets_with_vias": sum(1 for net in nets if net.get("via_count", 0) > 0),
            "nets_with_pads": sum(1 for net in nets if net.get("pad_count", 0) > 0),
        }
        if lengths:
            summary["min_track_length_mm"] = round(min(lengths), 4)
            summary["max_track_length_mm"] = round(max(lengths), 4)
            summary["total_track_length_mm"] = round(sum(lengths), 4)

        return json.dumps(
            {"nets": nets[:200], "count": len(nets), "summary": summary},
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def pcb_net_inspector(net_name: str) -> str:
        """Inspect every detail about a specific net in the PCB.

        Parameters
        ----------
        net_name : str
            The exact net name to inspect (e.g. ``GND``, ``+3V3``, ``USB_DP``).
        """
        nets = _nets()
        matches = [n for n in nets if n.get("name", "") == net_name]
        if not matches:
            available = ", ".join(sorted(set(n.get("name", "") for n in nets[:100])))
            return f"Net '{net_name}' was not found in the PCB. Sample nets: {available}"

        net = matches[0]
        net_code = net.get("code")

        # Collect authoritative board pads and enrich them with containing references.
        try:
            board = get_board()
            pads_on_net = [
                {
                    "reference": mapped.reference or "(unmapped)",
                    "pad": getattr(mapped.pad, "number", ""),
                    "layer": str(getattr(mapped.pad, "layer", "unknown")),
                }
                for mapped in _mapped_board_pads(board)
                if _object_net_name(mapped.pad) == net_name
            ]
        except (KiCadConnectionError, OSError, AttributeError, TypeError):
            pads_on_net = _file_pad_details(net_name)

        payload: dict[str, object] = {
            "net_name": net_name,
            "net_code": net_code,
            "class_name": net.get("class_name", ""),
            "track_count": net.get("track_count", 0),
            "via_count": net.get("via_count", 0),
            "pad_count": net.get("pad_count", 0),
            "total_track_length_mm": net.get("total_track_length_mm", 0),
            "footprint_pads": pads_on_net[:100],
        }
        return json.dumps(payload, indent=2)
