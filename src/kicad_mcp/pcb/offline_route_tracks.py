"""Pure S-expression adapter for DRC-only PCB candidate snapshots.

The caller writes the result exclusively inside a disposable temporary directory.
No KiCad GUI, SWIG runtime, or on-disk user project is mutated here. The real
KiCad CLI parses the candidate and provides independent DRC acceptance.
"""

from __future__ import annotations

import math
import re
import uuid

from sexpdata import loads  # type: ignore[import-untyped]

from ..routing.manual_tracks import TrackSpec, ViaSpec
from ..utils.sexpr import _sexpr_string

_COPPER_LAYER = re.compile(r"(?:F|B|In(?:[1-9]|[12]\d|30))_Cu\Z", re.ASCII)


def _named_board_nets(board: list[object]) -> set[str]:
    """Only an existing named net may be used by a generated candidate."""
    found: set[str] = set()
    pending: list[object] = list(board)
    while pending:
        item = pending.pop()
        if not isinstance(item, list) or not item:
            continue
        if str(item[0]) == "net":
            # KiCad 10 uses (net "NAME"); older files also carry numeric IDs.
            value = item[-1]
            if isinstance(value, str) and value:
                found.add(value)
        pending.extend(item[1:])
    return found


def _number(value: float) -> str:
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Candidate geometry must be finite")
    return f"{value:.6f}".rstrip("0").rstrip(".") if value else "0"


def _track_expression(spec: TrackSpec, nets: set[str]) -> str:
    if spec.net_name not in nets:
        raise ValueError("Candidate net is not present on the original board")
    if not _COPPER_LAYER.fullmatch(spec.layer):
        raise ValueError("Candidate uses an unsupported copper layer")
    if not 0 < spec.width_mm <= 5:
        raise ValueError("Candidate geometry contains invalid copper width")
    layer = _sexpr_string(spec.layer.replace("_", "."))
    net = _sexpr_string(spec.net_name)
    return (
        "\t(segment"
        f" (start {_number(spec.x1_mm)} {_number(spec.y1_mm)})"
        f" (end {_number(spec.x2_mm)} {_number(spec.y2_mm)})"
        f" (width {_number(spec.width_mm)})"
        f" (layer {layer}) (net {net})"
        f" (uuid {_sexpr_string(str(uuid.uuid4()))}))"
    )


def _via_expression(via: ViaSpec, nets: set[str]) -> str:
    if via.net_name not in nets:
        raise ValueError("Through-via net is not on the original board")
    if not all(
        math.isfinite(value) for value in (via.x_mm, via.y_mm, via.diameter_mm, via.drill_mm)
    ):
        raise ValueError("Through-via geometry must be finite")
    if not (0.4 <= via.diameter_mm <= 5 and 0.2 <= via.drill_mm <= via.diameter_mm - 0.2):
        raise ValueError("Through-via geometry is invalid")
    return (
        "\t(via"
        f" (at {_number(via.x_mm)} {_number(via.y_mm)})"
        f" (size {_number(via.diameter_mm)}) (drill {_number(via.drill_mm)})"
        f' (layers "F.Cu" "B.Cu") (net {_sexpr_string(via.net_name)})'
        f" (uuid {_sexpr_string(str(uuid.uuid4()))}))"
    )


def render_candidate_board(
    board_snapshot: str,
    segments: list[TrackSpec],
    through_via: ViaSpec | None = None,
) -> str:
    """Append a bounded, verified route to a *copy* of an IPC board snapshot."""
    if not isinstance(board_snapshot, str) or not board_snapshot.startswith("(kicad_pcb"):
        raise ValueError("Invalid native board snapshot")
    if not board_snapshot.rstrip().endswith(")"):
        raise ValueError("Malformed native board snapshot")
    try:
        board = loads(board_snapshot)
    except Exception as exc:
        raise ValueError("Malformed native board snapshot") from exc
    if not isinstance(board, list) or not board or str(board[0]) != "kicad_pcb":
        raise ValueError("Invalid native board root")
    if not 1 <= len(segments) <= 128:
        raise ValueError("Invalid candidate segment count")

    nets = _named_board_nets(board)
    additions = [_track_expression(spec, nets) for spec in segments]
    if through_via is not None:
        if (
            len(segments) != 2
            or (segments[0].layer, segments[1].layer) not in {("F_Cu", "B_Cu"), ("B_Cu", "F_Cu")}
            or any(segment.net_name != through_via.net_name for segment in segments)
            or math.hypot(
                segments[0].x2_mm - through_via.x_mm,
                segments[0].y2_mm - through_via.y_mm,
            )
            > 1e-5
            or math.hypot(
                segments[1].x1_mm - through_via.x_mm,
                segments[1].y1_mm - through_via.y_mm,
            )
            > 1e-5
        ):
            raise ValueError("Through-via geometry must join both outer-layer segments")
        additions.append(_via_expression(through_via, nets))
    return board_snapshot.rstrip()[:-1] + "\n" + "\n".join(additions) + "\n)\n"
