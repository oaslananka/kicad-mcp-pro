from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kicad_mcp.schematic.basic_authoring import SchematicBasicAuthoringService


class _TransactionRecorder:
    def __init__(self, current: str = "(lib_symbols)\n(sheet_instances)") -> None:
        self.current = current
        self.calls: list[tuple[Path, str]] = []
        self.updated: str | None = None

    def __call__(self, mutator: Callable[[str], str], path: Path) -> str:
        self.updated = mutator(self.current)
        self.calls.append((path, self.updated))
        return str(path)


class _ReloadRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return "Reloaded schematic."


def _service(
    *,
    lib_definition: str | None = '(symbol "Device:R")',
    suggestions: list[str] | None = None,
    available_units: set[int] | None = None,
    parsed: dict[str, Any] | None = None,
    transaction: _TransactionRecorder | None = None,
    reload: _ReloadRecorder | None = None,
    uuid_values: list[str] | None = None,
    captured_symbol_blocks: list[dict[str, Any]] | None = None,
) -> tuple[
    SchematicBasicAuthoringService,
    _TransactionRecorder,
    _ReloadRecorder,
    list[dict[str, Any]],
]:
    tx = transaction or _TransactionRecorder()
    reloader = reload or _ReloadRecorder()
    uuids = iter(uuid_values or ["root-uuid", "power-ref"])
    symbol_calls = captured_symbol_blocks if captured_symbol_blocks is not None else []

    def place_symbol_block(
        *,
        lib_id: str,
        x: float,
        y: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        unit: int = 1,
        project_name: str,
        root_uuid: str,
    ) -> str:
        kwargs: dict[str, Any] = {
            "lib_id": lib_id,
            "x": x,
            "y": y,
            "reference": reference,
            "value": value,
            "footprint": footprint,
            "rotation": rotation,
            "unit": unit,
            "project_name": project_name,
            "root_uuid": root_uuid,
        }
        symbol_calls.append(kwargs)
        return f"(placed {lib_id} {reference})"

    service = SchematicBasicAuthoringService(
        resolve_target=lambda sheet=None, sheet_file=None: SimpleNamespace(
            path=Path(sheet_file or sheet or "root.kicad_sch"),
            is_root=not bool(sheet or sheet_file),
            description=sheet or sheet_file or "root",
        ),
        format_target_detail=lambda target: (
            f"Target schematic ({'root' if target.is_root else 'child'}): {target.path}"
        ),
        parse_schematic=lambda _path: (
            parsed
            or {
                "uuid": "existing-root",
                "symbols": [{"x": 1.0, "y": 2.0}],
                "power_symbols": [{"x": 3.0, "y": 4.0}],
            }
        ),
        project_name=lambda: "DemoProject",
        load_lib_symbol=lambda _library, _name: lib_definition,
        suggest_symbol_names=lambda _library, _name: list(suggestions or []),
        symbol_available_units=lambda _library, _name: set(available_units or {1}),
        format_available_units=lambda units: ", ".join(str(unit) for unit in sorted(units)),
        snap_point=lambda x, y, enabled: (10.16, 20.32) if enabled else (x, y),
        snap_line=lambda x1, y1, x2, y2, enabled: (
            (1.27, 2.54, 3.81, 5.08) if enabled else (x1, y1, x2, y2)
        ),
        snap_notice=lambda original, snapped: (
            "" if original == snapped else f"Grid snap: {original} -> {snapped}"
        ),
        point_near_existing=lambda _x, _y, existing: (
            f"Overlap warning: {len(existing)} existing item(s)."
        ),
        validate_footprint=lambda footprint: (
            f"Footprint warning: {footprint}" if footprint else None
        ),
        place_symbol_block=place_symbol_block,
        wire_block=lambda *coords: f"(wire {' '.join(str(value) for value in coords)})",
        label_block=lambda name, x, y, rotation, justify=None: (
            f"(label {name} {x} {y} {rotation} {justify})"
        ),
        append_before_sheet_instances=lambda current, block: current.replace(
            "(sheet_instances)", f"{block}\n(sheet_instances)", 1
        ),
        transactional_write=tx,
        reload_schematic=reloader,
        new_uuid=lambda: next(uuids),
        format_mm=lambda value: f"{value:g}",
    )
    return service, tx, reloader, symbol_calls


def test_add_symbol_preserves_target_write_warnings_and_result_order() -> None:
    service, transaction, reload, symbol_calls = _service(available_units={1, 2})

    result = service.add_symbol(
        library="Device",
        symbol_name="R",
        x_mm=10.0,
        y_mm=20.0,
        reference="R1",
        value="10k",
        footprint="Resistor_SMD:R_0603",
        rotation=90,
        snap_to_grid=True,
        unit=2,
        sheet="Power",
        sheet_file=None,
    )

    assert result == (
        "Reloaded schematic.\n"
        "Target schematic (child): Power\n"
        "Grid snap: (10.0, 20.0) -> (10.16, 20.32)\n"
        "Overlap warning: 2 existing item(s).\n"
        "Footprint warning: Resistor_SMD:R_0603"
    )
    assert reload.calls == 1
    assert transaction.calls[0][0] == Path("Power")
    assert '(symbol "Device:R")' in str(transaction.updated)
    assert "(placed Device:R R1)" in str(transaction.updated)
    assert symbol_calls == [
        {
            "lib_id": "Device:R",
            "x": 10.16,
            "y": 20.32,
            "reference": "R1",
            "value": "10k",
            "footprint": "Resistor_SMD:R_0603",
            "rotation": 90,
            "unit": 2,
            "project_name": "DemoProject",
            "root_uuid": "existing-root",
        }
    ]


def test_add_symbol_preserves_missing_symbol_suggestions_without_write() -> None:
    service, transaction, reload, _calls = _service(
        lib_definition=None,
        suggestions=["R", "R_Small"],
    )

    assert (
        service.add_symbol(
            "Device",
            "RX",
            1.0,
            2.0,
            "R1",
            "10k",
            "",
            0,
            True,
            1,
            None,
            None,
        )
        == "Symbol 'Device:RX' was not found. Did you mean: R, R_Small?"
    )
    assert transaction.calls == []
    assert reload.calls == 0


def test_add_symbol_preserves_invalid_unit_result_without_write() -> None:
    service, transaction, reload, _calls = _service(available_units={1, 3})

    assert service.add_symbol(
        "Amplifier_Operational",
        "LM358",
        1.0,
        2.0,
        "U1",
        "LM358",
        "",
        0,
        True,
        2,
        None,
        None,
    ) == ("Symbol 'Amplifier_Operational:LM358' does not support unit 2. Available units: 1, 3.")
    assert transaction.calls == []
    assert reload.calls == 0


def test_add_symbol_uses_generated_root_uuid_when_parser_has_none() -> None:
    service, _transaction, _reload, symbol_calls = _service(
        parsed={"uuid": None, "symbols": [], "power_symbols": []},
        uuid_values=["generated-root"],
    )

    service.add_symbol(
        "Device",
        "R",
        1.0,
        2.0,
        "R1",
        "10k",
        "",
        0,
        False,
        1,
        None,
        None,
    )

    assert symbol_calls[0]["root_uuid"] == "generated-root"


def test_add_wire_preserves_snapping_target_and_result_order() -> None:
    service, transaction, reload, _calls = _service()

    assert service.add_wire(1.0, 2.0, 4.0, 5.0, True, None, "child.kicad_sch") == (
        "Reloaded schematic.\n"
        "Target schematic (child): child.kicad_sch\n"
        "Grid snap: (1.0, 2.0, 4.0, 5.0) -> (1.27, 2.54, 3.81, 5.08)"
    )
    assert reload.calls == 1
    assert transaction.calls[0][0] == Path("child.kicad_sch")
    assert "(wire 1.27 2.54 3.81 5.08)" in str(transaction.updated)


def test_add_label_preserves_justify_target_and_result_order() -> None:
    service, transaction, reload, _calls = _service()

    assert service.add_label("VCC", 10.0, 20.0, 90, True, "left", "Power", None) == (
        "Reloaded schematic.\n"
        "Target schematic (child): Power\n"
        "Grid snap: (10.0, 20.0) -> (10.16, 20.32)"
    )
    assert reload.calls == 1
    assert transaction.calls[0][0] == Path("Power")
    assert "(label VCC 10.16 20.32 90 left)" in str(transaction.updated)


def test_add_power_symbol_preserves_generated_reference_and_placement_message() -> None:
    symbol_calls: list[dict[str, Any]] = []
    service, _transaction, reload, _calls = _service(
        uuid_values=["abcd1234"],
        captured_symbol_blocks=symbol_calls,
    )

    result = service.add_power_symbol("VCC", 10.0, 20.0, 180, True, None, None)

    assert result.endswith("\nPower symbol VCC placed at (10.16, 20.32)")
    assert reload.calls == 1
    assert symbol_calls[0]["reference"] == "#PWRabcd"
    assert symbol_calls[0]["lib_id"] == "power:VCC"
    assert symbol_calls[0]["rotation"] == 180


def test_add_power_symbol_returns_missing_symbol_result_unchanged() -> None:
    service, transaction, reload, _calls = _service(lib_definition=None)

    result = service.add_power_symbol("NO_SUCH_POWER", 1.0, 2.0, 0, True, None, None)

    assert result == "Symbol 'power:NO_SUCH_POWER' was not found."
    assert transaction.calls == []
    assert reload.calls == 0
