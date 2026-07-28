"""Footprint rotation persistence regressions for issue #499."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.geometry import Angle

from kicad_mcp.pcb.footprint_transform import (
    FootprintRotationError,
    apply_footprint_rotation,
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
    with pytest.raises(FootprintRotationError, match="must be finite"):
        apply_footprint_rotation(_StrictRotationSurface("orientation"), float("inf"))


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
