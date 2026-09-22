"""Unit tests for net analysis tools (FAZ 6.1–6.3).
Tools: pcb_get_net_statistics, pcb_net_inspector, pcb_export_stats.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.net_analysis import _collect_nets_from_file, _nets
from tests.conftest import call_tool_text


def test_collect_nets_from_file_empty(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A minimal PCB file with no nets should return an empty list."""
    pcb_file = tmp_path / "empty.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20250316))\n", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.tools.net_analysis._get_pcb_file", lambda: pcb_file)
    nets = _collect_nets_from_file()
    assert nets == []


def test_collect_nets_from_file_with_nets(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text(
        '(kicad_pcb (version 20250316) (net 0 "") (net 1 "GND") (net 2 "+3V3"))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.net_analysis._get_pcb_file", lambda: pcb_file)
    nets = _collect_nets_from_file()
    names = {n["name"] for n in nets}
    assert "GND" in names
    assert "+3V3" in names


def test_nets_uses_file_fallback_when_no_board(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text(
        '(kicad_pcb (version 20250316) (net 0 "") (net 1 "CLK") (net 2 "D0"))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.net_analysis._get_pcb_file", lambda: pcb_file)
    result = _nets()
    assert len(result) >= 1


class _DeprecatedCodeNet:
    def __init__(self, name: str) -> None:
        self.name = name
        self.class_name = "Default"

    @property
    def code(self) -> int:  # pragma: no cover - should never be touched
        raise AssertionError("deprecated net code was accessed")


class _NetObject:
    def __init__(self, net_name: str, *, length: int = 0) -> None:
        self.net = type("NetRef", (), {"name": net_name})()
        self.length = length


class _BoardByName:
    def get_nets(self):  # type: ignore[no-untyped-def]
        return [_DeprecatedCodeNet("GND")]

    def get_tracks(self):  # type: ignore[no-untyped-def]
        return [_NetObject("GND", length=1_000_000)]

    def get_vias(self):  # type: ignore[no-untyped-def]
        return [_NetObject("GND")]

    def get_pads(self):  # type: ignore[no-untyped-def]
        return [_NetObject("GND")]

    def get_footprints(self):  # type: ignore[no-untyped-def]
        return []


def test_collect_nets_from_board_uses_net_names_not_deprecated_codes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kicad_mcp.tools.net_analysis import _collect_nets_from_board

    monkeypatch.setattr("kicad_mcp.tools.net_analysis.get_board", lambda: _BoardByName())

    nets = _collect_nets_from_board()

    assert nets == [
        {
            "code": None,
            "name": "GND",
            "class_name": "Default",
            "track_count": 1,
            "via_count": 1,
            "pad_count": 1,
            "total_track_length_mm": 1.0,
        }
    ]


@pytest.mark.anyio
async def test_net_inspector_maps_live_board_pads_through_footprint_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = SimpleNamespace(
        id=SimpleNamespace(value="pad-1"),
        number="1",
        net=SimpleNamespace(name="GND"),
        position=SimpleNamespace(x=1_000_000, y=2_000_000),
        layer=0,
    )
    footprint = SimpleNamespace(
        reference_field=SimpleNamespace(text=SimpleNamespace(value="U1")),
        definition=SimpleNamespace(pads=[SimpleNamespace(id=SimpleNamespace(value="pad-1"))]),
    )
    board = SimpleNamespace(
        get_nets=lambda: [SimpleNamespace(name="GND", class_name="Default")],
        get_tracks=lambda: [],
        get_vias=lambda: [],
        get_pads=lambda: [pad],
        get_footprints=lambda: [footprint],
    )
    monkeypatch.setattr("kicad_mcp.tools.net_analysis.get_board", lambda: board)
    server = build_server("full")

    payload = json.loads(await call_tool_text(server, "pcb_net_inspector", {"net_name": "GND"}))

    assert payload["pad_count"] == 1
    assert payload["footprint_pads"] == [{"reference": "U1", "pad": "1", "layer": "0"}]


@pytest.mark.anyio
async def test_net_inspector_file_fallback_parses_balanced_nested_footprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcb_file = tmp_path / "nested.kicad_pcb"
    pcb_file.write_text(
        """(kicad_pcb
  (version 20250216)
  (net 1 "GND")
  (footprint "Example:Nested"
    (layer "F.Cu")
    (property "Reference" "U1" (at 1 2) (layer "F.SilkS"))
    (fp_rect (start -1 -1) (end 1 1)
      (stroke (width 0.1) (type solid)) (fill none) (layer "F.CrtYd"))
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "GND"))
  )
)
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.net_analysis._nets",
        lambda: [{"name": "GND", "code": 1, "pad_count": 1}],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.net_analysis.get_board",
        lambda: (_ for _ in ()).throw(OSError("offline")),
    )
    monkeypatch.setattr("kicad_mcp.tools.net_analysis._get_pcb_file", lambda: pcb_file)
    server = build_server("full")

    payload = json.loads(await call_tool_text(server, "pcb_net_inspector", {"net_name": "GND"}))

    assert payload["footprint_pads"] == [{"reference": "U1", "pad": "1", "layer": "F.Cu"}]


def test_nets_uses_file_fallback_when_live_via_access_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text(
        '(kicad_pcb (version 20250316) (net 1 "GND"))\n',
        encoding="utf-8",
    )

    class PartiallyReadableBoard:
        def get_nets(self) -> list[object]:
            return [SimpleNamespace(name="GND", class_name="Default")]

        def get_tracks(self) -> list[object]:
            return []

        def get_vias(self) -> list[object]:
            raise OSError("via IPC read failed")

        def get_footprints(self) -> list[object]:
            return []

        def get_pads(self) -> list[object]:
            return []

    monkeypatch.setattr(
        "kicad_mcp.tools.net_analysis.get_board",
        lambda: PartiallyReadableBoard(),
    )
    monkeypatch.setattr("kicad_mcp.tools.net_analysis._get_pcb_file", lambda: pcb_file)

    assert _nets() == [{"code": 1, "name": "GND", "class_name": ""}]


class _KipyStyleTrack:
    """Track whose ``length`` is a method, as ``kipy.board_types.Track`` defines it.

    Every other geometry accessor on that class (``start``, ``end``, ``width``)
    is a ``@property``; ``length`` is not, so reading it without calling it
    yields a bound method rather than a number.
    """

    def __init__(self, net_name: str, *, length_nm: float) -> None:
        self.net = SimpleNamespace(name=net_name)
        self._length_nm = length_nm

    def length(self) -> float:
        """Calculates track length in nanometers."""
        return self._length_nm


class _BoardWithCallableTrackLength:
    def get_nets(self):  # type: ignore[no-untyped-def]
        return [SimpleNamespace(name="GND", class_name="Default")]

    def get_tracks(self):  # type: ignore[no-untyped-def]
        return [_KipyStyleTrack("GND", length_nm=2_500_000)]

    def get_vias(self):  # type: ignore[no-untyped-def]
        return []

    def get_pads(self):  # type: ignore[no-untyped-def]
        return []

    def get_footprints(self):  # type: ignore[no-untyped-def]
        return []


def test_collect_nets_from_board_calls_track_length_when_it_is_a_method(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A live kipy track exposes ``length()``; reading the attribute is not enough.

    Regression test: dividing the bound method by 1_000_000 raised
    ``TypeError: unsupported operand type(s) for /: 'method' and 'int'``, which
    ``_nets`` does not catch, so both ``pcb_get_net_statistics`` and
    ``pcb_net_inspector`` failed outright on any routed board read over IPC.
    """
    from kicad_mcp.tools.net_analysis import _collect_nets_from_board

    monkeypatch.setattr(
        "kicad_mcp.tools.net_analysis.get_board",
        lambda: _BoardWithCallableTrackLength(),
    )

    nets = _collect_nets_from_board()

    assert nets[0]["track_count"] == 1
    assert nets[0]["total_track_length_mm"] == 2.5


def test_track_length_nm_returns_none_when_length_call_raises() -> None:
    """A track that cannot measure itself contributes no length, not a crash.

    ``kipy`` can hand back a track whose geometry is not fully resolved; calling
    ``length()`` on it raises rather than returning a number. That must be
    treated the same as "no length available", never propagate to the caller.
    """
    from kicad_mcp.tools.net_analysis import _track_length_nm

    class _UnmeasurableTrack:
        def length(self) -> float:
            raise RuntimeError("track geometry is not resolved")

    assert _track_length_nm(_UnmeasurableTrack()) is None


def test_track_length_nm_returns_none_for_non_numeric_length() -> None:
    """A track with no usable ``length`` (missing, or neither callable nor numeric) yields None."""
    from kicad_mcp.tools.net_analysis import _track_length_nm

    assert _track_length_nm(SimpleNamespace()) is None
    assert _track_length_nm(SimpleNamespace(length="unknown")) is None
