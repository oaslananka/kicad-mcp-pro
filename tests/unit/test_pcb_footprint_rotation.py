"""Footprint rotation persistence regressions for issue #499."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.board_types import Footprint3DModel, FootprintInstance
from kipy.geometry import Angle
from kipy.proto.board.board_commands_pb2 import BoardFlipDirection
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.pcb.footprint_transform import (
    FootprintRotationError,
    apply_footprint_rotation,
    get_current_footprint_rotation,
    verify_footprint_rotation,
)
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


class _StrictRotationSurface:
    def __init__(
        self,
        attribute: str,
        *,
        reject: bool = False,
        initial_degrees: float = 0.0,
    ) -> None:
        self.attribute = attribute
        self.reject = reject
        self.assigned_values: list[object] = []
        self._value = Angle.from_degrees(initial_degrees)

    def __getattr__(self, name: str) -> object:
        if name == self.attribute:
            return self._value
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_") or name in {"attribute", "reject", "assigned_values"}:
            object.__setattr__(self, name, value)
            return
        if name == self.attribute:
            self.assigned_values.append(value)
            if self.reject:
                raise TypeError(f"{name} is not writable")
            if not isinstance(value, Angle):
                raise TypeError(f"{name} requires Angle")
            object.__setattr__(self, "_value", value)
            return
        object.__setattr__(self, name, value)


class _LiveFootprint(_StrictRotationSurface):
    def __init__(
        self,
        attribute: str = "orientation",
        *,
        reject: bool = False,
        initial_degrees: float = 0.0,
    ) -> None:
        super().__init__(attribute, reject=reject, initial_degrees=initial_degrees)
        self.reference_field = SimpleNamespace(text=SimpleNamespace(value="X2"))
        self.position = None


@pytest.mark.parametrize("attribute", ["angle", "orientation"])
def test_apply_footprint_rotation_assigns_an_angle(attribute: str) -> None:
    footprint = _StrictRotationSurface(attribute)

    selected = apply_footprint_rotation(footprint, 180.0)

    assert selected == attribute
    assert len(footprint.assigned_values) == 1
    assert isinstance(footprint.assigned_values[0], Angle)
    assert footprint.assigned_values[0].degrees == pytest.approx(180.0)


@pytest.mark.parametrize("degrees", [0.0, 90.0, 180.0])
def test_kipy_orientation_preserves_stock_footprint_3d_models(degrees: float) -> None:
    # A real kicad-python 0.7/0.8 FootprintInstance loses models even on a
    # same-angle assignment; using its actual setter catches the regression.
    footprint = FootprintInstance()
    model = Footprint3DModel()
    model.filename = "Resistor_SMD.3dshapes/R_0603_1608Metric.step"
    footprint.definition.items = [model]
    assert len(footprint.definition.models) == 1

    chosen = apply_footprint_rotation(footprint, degrees)

    assert chosen == "orientation"
    assert footprint.orientation.degrees == pytest.approx(degrees)
    assert [item.filename for item in footprint.definition.models] == [model.filename]
    # Regression must survive the proto conversion used by board.update_items.
    round_trip = FootprintInstance(proto=footprint.proto)
    assert [item.filename for item in round_trip.definition.models] == [model.filename]
    assert (
        round_trip.definition.models[0].proto.SerializeToString() == model.proto.SerializeToString()
    )


def test_unchanged_rotation_does_not_call_orientation_setter() -> None:
    footprint = _StrictRotationSurface("orientation", initial_degrees=0.0)
    assert apply_footprint_rotation(footprint, 360.0) == "orientation"
    assert footprint.assigned_values == []


def test_apply_footprint_rotation_fails_when_no_supported_surface_exists() -> None:
    with pytest.raises(FootprintRotationError, match="angle or orientation"):
        apply_footprint_rotation(object(), 90.0)


def test_apply_footprint_rotation_fails_when_setter_rejects_angle() -> None:
    footprint = _StrictRotationSurface("orientation", reject=True)

    with pytest.raises(FootprintRotationError, match="could not be applied"):
        apply_footprint_rotation(footprint, 90.0)


def test_verify_footprint_rotation_accepts_equivalent_wrapped_degrees() -> None:
    footprint = _StrictRotationSurface("orientation", initial_degrees=-180.0)

    assert verify_footprint_rotation(footprint, "orientation", 180.0) == pytest.approx(-180.0)


def test_verify_footprint_rotation_rejects_mismatch() -> None:
    footprint = _StrictRotationSurface("orientation", initial_degrees=90.0)

    with pytest.raises(FootprintRotationError, match="verification failed"):
        verify_footprint_rotation(footprint, "orientation", 180.0)


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_applies_and_reports_verified_rotation(mock_board: object) -> None:
    footprint = _LiveFootprint()
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 180.0},
    )

    assert len(footprint.assigned_values) == 1
    assert isinstance(footprint.assigned_values[0], Angle)
    assert footprint.assigned_values[0].degrees == pytest.approx(180.0)
    assert "verified rotation 180.000 degrees" in result
    mock_board.update_items.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_without_rotation_preserves_existing_angle(mock_board: object) -> None:
    footprint = _LiveFootprint(initial_degrees=90.0)
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0},
    )

    assert footprint.assigned_values == []
    assert footprint.orientation.degrees == pytest.approx(90.0)
    assert "verified rotation 90.000 degrees" in result
    mock_board.update_items.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_explicit_zero_resets_existing_angle(mock_board: object) -> None:
    footprint = _LiveFootprint(initial_degrees=90.0)
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 0.0},
    )

    assert len(footprint.assigned_values) == 1
    assert footprint.orientation.degrees == pytest.approx(0.0)
    assert "verified rotation 0.000 degrees" in result
    mock_board.update_items.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_component_without_rotation_preserves_existing_angle(mock_board: object) -> None:
    footprint = _LiveFootprint(initial_degrees=90.0)
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_component",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0},
    )

    assert footprint.assigned_values == []
    assert footprint.orientation.degrees == pytest.approx(90.0)
    assert "verified rotation 90.000 degrees" in result
    mock_board.update_items.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_fails_when_rotation_setter_rejects_angle(mock_board: object) -> None:
    footprint = _LiveFootprint(reject=True)
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 180.0},
    )

    assert "TOOL_EXECUTION_FAILED" in result
    assert "could not be applied" in result
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_fails_when_post_update_rotation_mismatches(
    mock_board: object,
) -> None:
    initial = _LiveFootprint()
    refreshed = _LiveFootprint(initial_degrees=90.0)
    mock_board.get_footprints.side_effect = [[initial], [refreshed]]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 180.0},
    )

    assert "TOOL_EXECUTION_FAILED" in result
    assert "verification failed" in result
    mock_board.update_items.assert_called_once()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
@pytest.mark.parametrize("tool_name", ["pcb_place_component", "pcb_move_component"])
async def test_component_move_aliases_use_verified_rotation_path(
    mock_board: object,
    tool_name: str,
) -> None:
    footprint = _LiveFootprint()
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        tool_name,
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 180.0},
    )

    assert "verified rotation 180.000 degrees" in result
    assert isinstance(footprint.assigned_values[0], Angle)


class _DualRotationSurface:
    def __init__(self) -> None:
        self._angle = Angle.from_degrees(0.0)
        self._orientation = Angle.from_degrees(0.0)
        self.orientation_assignments: list[object] = []

    @property
    def angle(self) -> Angle:
        return self._angle

    @angle.setter
    def angle(self, _value: object) -> None:
        raise TypeError("angle is read-only")

    @property
    def orientation(self) -> Angle:
        return self._orientation

    @orientation.setter
    def orientation(self, value: object) -> None:
        self.orientation_assignments.append(value)
        if not isinstance(value, Angle):
            raise TypeError("orientation requires Angle")
        self._orientation = value


def test_apply_footprint_rotation_falls_back_to_writable_orientation() -> None:
    footprint = _DualRotationSurface()

    selected = apply_footprint_rotation(footprint, 45.0)

    assert selected == "orientation"
    assert len(footprint.orientation_assignments) == 1
    assert isinstance(footprint.orientation_assignments[0], Angle)
    assert footprint.orientation.degrees == pytest.approx(45.0)


def test_apply_footprint_rotation_rejects_non_finite_degrees() -> None:
    surface = _StrictRotationSurface("orientation")
    degrees = float("inf")
    with pytest.raises(FootprintRotationError, match="must be finite"):
        apply_footprint_rotation(surface, degrees)


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_move_footprint_fails_when_updated_reference_cannot_be_reloaded(
    mock_board: object,
) -> None:
    initial = _LiveFootprint()
    mock_board.get_footprints.side_effect = [[initial], []]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_move_footprint",
        {"reference": "X2", "x_mm": 10.0, "y_mm": 20.0, "rotation_deg": 180.0},
    )

    assert "TOOL_EXECUTION_FAILED" in result
    assert "could not be reloaded" in result
    mock_board.update_items.assert_called_once()


def test_verify_footprint_rotation_allows_ipc_round_trip_tolerance() -> None:
    footprint = _StrictRotationSurface("orientation", initial_degrees=180.0005)

    assert verify_footprint_rotation(footprint, "orientation", 180.0) == pytest.approx(180.0005)


@pytest.mark.parametrize("attribute", ["angle", "orientation"])
def test_get_current_footprint_rotation_reads_without_assigning(attribute: str) -> None:
    footprint = _StrictRotationSurface(attribute, initial_degrees=90.0)
    selected, degrees = get_current_footprint_rotation(footprint)
    assert selected == attribute
    assert degrees == pytest.approx(90.0)
    assert footprint.assigned_values == []


def test_get_current_footprint_rotation_rejects_missing_surfaces() -> None:
    with pytest.raises(FootprintRotationError, match="does not expose"):
        get_current_footprint_rotation(object())


def test_get_current_footprint_rotation_rejects_unreadable_surfaces() -> None:
    footprint = SimpleNamespace(angle=object(), orientation=object())

    with pytest.raises(FootprintRotationError, match="could not be read"):
        get_current_footprint_rotation(footprint)


def test_kicad_10_0_8_symbol_units_unknown_field_survives_rotation_round_trip() -> None:
    # KiCad 10.0.8 adds FootprintInstance.symbol_units as protobuf field 21.
    # kicad-python 0.8.0 does not expose it as a typed attribute, so inject the
    # wire payload and assert it survives wrapper conversion and rotation.
    unit_info = bytes([0x0A, 0x01, ord("A"), 0x12, 0x01, ord("1")])
    symbol_units_field = bytes([0xAA, 0x01, len(unit_info)]) + unit_info

    original = FootprintInstance()
    proto_with_unit_metadata = type(original.proto)()
    proto_with_unit_metadata.ParseFromString(
        original.proto.SerializeToString() + symbol_units_field
    )
    footprint = FootprintInstance(proto=proto_with_unit_metadata)

    assert symbol_units_field in footprint.proto.SerializeToString()
    assert apply_footprint_rotation(footprint, 90.0) == "orientation"

    round_trip = FootprintInstance(proto=footprint.proto)
    assert round_trip.orientation.degrees == pytest.approx(90.0)
    assert symbol_units_field in round_trip.proto.SerializeToString()


def _make_flippable_footprint(source_layer: int) -> _LiveFootprint:
    footprint = _LiveFootprint()
    footprint.layer = source_layer
    front = int(source_layer) == int(BoardLayer.BL_F_Cu)
    copper = BoardLayer.BL_F_Cu if front else BoardLayer.BL_B_Cu
    mask = BoardLayer.BL_F_Mask if front else BoardLayer.BL_B_Mask
    paste = BoardLayer.BL_F_Paste if front else BoardLayer.BL_B_Paste
    silk = BoardLayer.BL_F_SilkS if front else BoardLayer.BL_B_SilkS
    fab = BoardLayer.BL_F_Fab if front else BoardLayer.BL_B_Fab
    courtyard = BoardLayer.BL_F_CrtYd if front else BoardLayer.BL_B_CrtYd
    reference_field = SimpleNamespace(
        name="Reference",
        text=SimpleNamespace(value="X2"),
        layer=silk,
    )
    footprint.reference_field = reference_field
    footprint.texts_and_fields = [
        SimpleNamespace(id=SimpleNamespace(value="silk-text"), layer=silk),
        SimpleNamespace(id=SimpleNamespace(value="fab-text"), layer=fab),
        reference_field,
        SimpleNamespace(name="Value", layer=fab),
    ]
    footprint.definition = SimpleNamespace(
        shapes=[
            SimpleNamespace(id=SimpleNamespace(value="silk-shape"), layer=silk),
            SimpleNamespace(id=SimpleNamespace(value="fab-shape"), layer=fab),
            SimpleNamespace(id=SimpleNamespace(value="courtyard-shape"), layer=courtyard),
        ],
        pads=[
            SimpleNamespace(
                id=SimpleNamespace(value=f"pad-{number}"),
                number=str(number),
                padstack=SimpleNamespace(layers=[copper, mask, paste]),
            )
            for number in (1, 2)
        ],
    )
    return footprint


def _mock_flip_footprint(footprint: _LiveFootprint, target_layer: int) -> list[object]:
    front_to_back = {
        int(BoardLayer.BL_F_Cu): int(BoardLayer.BL_B_Cu),
        int(BoardLayer.BL_F_Adhes): int(BoardLayer.BL_B_Adhes),
        int(BoardLayer.BL_F_Paste): int(BoardLayer.BL_B_Paste),
        int(BoardLayer.BL_F_SilkS): int(BoardLayer.BL_B_SilkS),
        int(BoardLayer.BL_F_Mask): int(BoardLayer.BL_B_Mask),
        int(BoardLayer.BL_F_CrtYd): int(BoardLayer.BL_B_CrtYd),
        int(BoardLayer.BL_F_Fab): int(BoardLayer.BL_B_Fab),
    }
    layer_map = (
        front_to_back
        if int(target_layer) == int(BoardLayer.BL_B_Cu)
        else {back: front for front, back in front_to_back.items()}
    )
    footprint.layer = target_layer
    for item in footprint.texts_and_fields:
        item.layer = layer_map.get(int(item.layer), int(item.layer))
    for shape in footprint.definition.shapes:
        shape.layer = layer_map.get(int(shape.layer), int(shape.layer))
    for pad in footprint.definition.pads:
        pad.padstack.layers = [
            layer_map.get(int(layer), int(layer)) for layer in pad.padstack.layers
        ]
    return [footprint]


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
@pytest.mark.parametrize(
    ("source_layer", "target_layer", "target_name"),
    [
        (BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu, "B_Cu"),
        (BoardLayer.BL_B_Cu, BoardLayer.BL_F_Cu, "F_Cu"),
    ],
)
async def test_set_footprint_layer_uses_native_flip_in_both_directions(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
    source_layer: int,
    target_layer: int,
    target_name: str,
) -> None:
    footprint = _make_flippable_footprint(source_layer)
    mock_board.get_footprints.return_value = [footprint]
    mock_board.flip_items.side_effect = lambda item, direction: _mock_flip_footprint(
        item, target_layer
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: SimpleNamespace(get_version=lambda: SimpleNamespace(major=10, minor=0, patch=7)),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": target_name},
    )

    assert "Flipped footprint 'X2'" in result
    assert footprint.layer == target_layer
    mock_board.flip_items.assert_called_once_with(
        footprint, direction=BoardFlipDirection.BFD_LEFT_RIGHT
    )
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_rejects_layer_only_flip_for_dual_sided_footprint(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    footprint = _make_flippable_footprint(BoardLayer.BL_F_Cu)
    footprint.texts_and_fields.append(
        SimpleNamespace(
            id=SimpleNamespace(value="back-silk-text"),
            layer=BoardLayer.BL_B_SilkS,
        )
    )
    footprint.definition.shapes.append(
        SimpleNamespace(
            id=SimpleNamespace(value="back-fab-shape"),
            layer=BoardLayer.BL_B_Fab,
        )
    )
    footprint.definition.pads.append(
        SimpleNamespace(
            id=SimpleNamespace(value="pad-3"),
            number="3",
            padstack=SimpleNamespace(
                layers=[BoardLayer.BL_B_Cu, BoardLayer.BL_B_Mask, BoardLayer.BL_B_Paste]
            ),
        )
    )
    mock_board.get_footprints.return_value = [footprint]
    mock_board.flip_items.side_effect = lambda item, direction: (
        setattr(item, "layer", BoardLayer.BL_B_Cu) or [item]
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: SimpleNamespace(get_version=lambda: SimpleNamespace(major=10, minor=0, patch=7)),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "B_Cu"},
    )

    assert "TOOL_EXECUTION_FAILED" in result
    assert "verification failed" in result
    assert footprint.layer == BoardLayer.BL_B_Cu
    assert footprint.reference_field.layer == BoardLayer.BL_F_SilkS
    mock_board.flip_items.assert_called_once()
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_same_side_is_a_noop(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    footprint = _LiveFootprint()
    footprint.layer = BoardLayer.BL_B_Cu
    mock_board.get_footprints.return_value = [footprint]
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: pytest.fail("same-side request must not require a native flip"),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "B.Cu"},
    )

    assert "already on" in result
    mock_board.flip_items.assert_not_called()
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_rejects_non_copper_side_layers(
    mock_board: object,
) -> None:
    footprint = _LiveFootprint()
    footprint.layer = BoardLayer.BL_F_Cu
    mock_board.get_footprints.return_value = [footprint]
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "In1.Cu"},
    )

    assert "Only F.Cu and B.Cu" in result
    mock_board.flip_items.assert_not_called()
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_refuses_unsupported_kicad_version(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    footprint = _LiveFootprint()
    footprint.layer = BoardLayer.BL_F_Cu
    mock_board.get_footprints.return_value = [footprint]
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: SimpleNamespace(get_version=lambda: SimpleNamespace(major=10, minor=0, patch=5)),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "B_Cu"},
    )

    assert "KiCad 10.0.6 or newer" in result
    assert "no changes were made" in result.casefold()
    mock_board.flip_items.assert_not_called()
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_fails_when_native_flip_is_not_confirmed(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    footprint = _make_flippable_footprint(BoardLayer.BL_F_Cu)
    mock_board.get_footprints.return_value = [footprint]
    mock_board.flip_items.return_value = []
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: SimpleNamespace(get_version=lambda: SimpleNamespace(major=10, minor=0, patch=7)),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "B_Cu"},
    )

    assert "TOOL_EXECUTION_FAILED" in result
    assert "verification failed" in result
    assert footprint.layer == BoardLayer.BL_F_Cu
    mock_board.flip_items.assert_called_once()
    mock_board.update_items.assert_not_called()


@pytest.mark.anyio
@pytest.mark.mcp_mode("write")
async def test_set_footprint_layer_refuses_when_sdk_has_no_native_flip_api(
    mock_board: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    footprint = _LiveFootprint()
    footprint.layer = BoardLayer.BL_F_Cu
    mock_board.get_footprints.return_value = [footprint]
    mock_board.flip_items = None
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb.get_kicad",
        lambda: SimpleNamespace(get_version=lambda: SimpleNamespace(major=10, minor=0, patch=7)),
        raising=False,
    )
    server = build_server("full")

    result = await call_tool_text(
        server,
        "pcb_set_footprint_layer",
        {"reference": "X2", "layer": "B_Cu"},
    )

    assert "SDK does not expose Board.flip_items" in result
    assert "no changes were made" in result
    mock_board.update_items.assert_not_called()
