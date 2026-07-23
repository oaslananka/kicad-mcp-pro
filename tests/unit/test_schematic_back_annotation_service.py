from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.schematic.back_annotation import SchematicBackAnnotationService


class _StateRecorder:
    def __init__(self) -> None:
        self.loaded: dict[str, dict[str, Any]] = {}
        self.saved: list[tuple[str, dict[str, Any]]] = []

    def load(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        payload = self.loaded.get(filename, default)
        return json.loads(json.dumps(payload))

    def save(self, filename: str, payload: dict[str, Any]) -> Path:
        self.saved.append((filename, json.loads(json.dumps(payload))))
        return Path(".kicad-mcp") / filename


def _service(
    *,
    project_file: Path | None = None,
    symbol: dict[str, Any] | None = None,
    aliases: dict[str, tuple[float, float]] | None = None,
    symbol_library_file: Path | None = None,
    units: set[int] | None = None,
    state: _StateRecorder | None = None,
) -> tuple[SchematicBackAnnotationService, _StateRecorder]:
    recorder = state or _StateRecorder()
    service = SchematicBackAnnotationService(
        project_file=lambda: project_file,
        symbol_by_reference=lambda reference: (
            symbol
            or {
                "reference": reference,
                "lib_id": "Device:R",
                "x": 10.0,
                "y": 20.0,
                "rotation": 90,
                "unit": 1,
            }
        ),
        split_lib_id=lambda lib_id: tuple(lib_id.split(":", 1)),  # type: ignore[return-value]
        pin_alias_positions=lambda *_args: (
            aliases
            or {
                "10": (1.0, 1.0),
                "2": (2.0, 2.0),
                "A": (3.0, 3.0),
                "": (4.0, 4.0),
            }
        ),
        symbol_library_file=lambda _library: symbol_library_file,
        collect_symbol_blocks=lambda _content, _symbol_name: ["unit-1", "unit-2"],
        available_units_from_blocks=lambda _blocks: set(units or {2, 1}),
        load_state=recorder.load,
        save_state=recorder.save,
    )
    return service, recorder


def test_set_hop_over_requires_configured_existing_project(tmp_path: Path) -> None:
    missing, _state = _service(project_file=None)
    with pytest.raises(
        ValueError,
        match="No project file is configured. Call kicad_set_project",
    ):
        missing.set_hop_over(True)

    absent_path, _state = _service(project_file=tmp_path / "missing.kicad_pro")
    with pytest.raises(ValueError, match="No project file is configured"):
        absent_path.set_hop_over(False)


def test_set_hop_over_preserves_json_errors_and_object_requirement(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.kicad_pro"
    invalid.write_text("{not-json", encoding="utf-8")
    service, _state = _service(project_file=invalid)
    with pytest.raises(ValueError, match="does not contain valid JSON"):
        service.set_hop_over(True)

    non_object = tmp_path / "list.kicad_pro"
    non_object.write_text("[]", encoding="utf-8")
    service, _state = _service(project_file=non_object)
    with pytest.raises(ValueError, match="must contain a JSON object"):
        service.set_hop_over(True)


def test_set_hop_over_updates_project_payload_and_result(tmp_path: Path) -> None:
    project = tmp_path / "demo.kicad_pro"
    project.write_text(json.dumps({"board": {}, "schematic": {"legacy": True}}), encoding="utf-8")
    service, _state = _service(project_file=project)

    assert service.set_hop_over(False) == f"Hop-over display set to disabled in {project}."
    payload = json.loads(project.read_text(encoding="utf-8"))
    assert payload == {
        "board": {},
        "schematic": {"legacy": True, "hop_over_display": False},
    }
    assert project.read_text(encoding="utf-8").startswith("{\n  ")


def test_list_swappable_pins_filters_numeric_aliases_and_sorts_units(tmp_path: Path) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text("symbol library", encoding="utf-8")
    service, _state = _service(symbol_library_file=library, units={3, 1, 2})

    result = json.loads(service.list_swappable_pins("R1"))

    assert result == {
        "reference": "R1",
        "pins": ["2", "10"],
        "gates": [1, 2, 3],
        "note": "Recorded swaps are stored as back-annotation intents in .kicad-mcp.",
    }


def test_list_swappable_pins_omits_gate_discovery_without_library_file() -> None:
    service, _state = _service(symbol_library_file=None)

    result = json.loads(service.list_swappable_pins("R1"))

    assert result["pins"] == ["2", "10"]
    assert result["gates"] == []


def test_swap_pins_rejects_invalid_candidates_without_state_write() -> None:
    service, state = _service(aliases={"1": (0.0, 0.0), "2": (1.0, 1.0)})

    assert service.swap_pins("R1", "1", "3") == (
        "Pins '1' and/or '3' are not swappable candidates for 'R1'."
    )
    assert state.saved == []


def test_swap_pins_appends_intent_and_preserves_same_pin_behavior() -> None:
    state = _StateRecorder()
    state.loaded["pin_swaps.json"] = {"swaps": [{"reference": "U1", "pin_a": "1", "pin_b": "2"}]}
    service, state = _service(
        aliases={"1": (0.0, 0.0), "2": (1.0, 1.0)},
        state=state,
    )

    saved_path = Path(".kicad-mcp") / "pin_swaps.json"
    assert service.swap_pins("R1", "1", "1") == (f"Recorded pin swap R1:1<->1 in {saved_path}.")
    assert state.saved == [
        (
            "pin_swaps.json",
            {
                "swaps": [
                    {"reference": "U1", "pin_a": "1", "pin_b": "2"},
                    {"reference": "R1", "pin_a": "1", "pin_b": "1"},
                ]
            },
        )
    ]


def test_swap_gates_rejects_invalid_candidates_without_state_write(tmp_path: Path) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text("symbol library", encoding="utf-8")
    service, state = _service(symbol_library_file=library, units={1})

    assert service.swap_gates("R1", 1, 2) == ("Gates '1' and/or '2' are not available on 'R1'.")
    assert state.saved == []


def test_swap_gates_appends_intent(tmp_path: Path) -> None:
    library = tmp_path / "Device.kicad_sym"
    library.write_text("symbol library", encoding="utf-8")
    state = _StateRecorder()
    state.loaded["gate_swaps.json"] = {"swaps": []}
    service, state = _service(symbol_library_file=library, units={1, 2}, state=state)

    saved_path = Path(".kicad-mcp") / "gate_swaps.json"
    assert service.swap_gates("U1", 1, 2) == (f"Recorded gate swap U1:1<->2 in {saved_path}.")
    assert state.saved == [
        (
            "gate_swaps.json",
            {"swaps": [{"reference": "U1", "gate_a": 1, "gate_b": 2}]},
        )
    ]
