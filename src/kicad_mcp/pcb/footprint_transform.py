"""Footprint transform helpers shared by live PCB mutation tools."""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any, Literal, cast

from google.protobuf.descriptor import FieldDescriptor  # type: ignore[import-untyped]
from google.protobuf.message import Message  # type: ignore[import-untyped]
from kipy.board_types import (
    BoardPolygon,
    BoardRectangle,
    BoardShape,
    BoardText,
    Field,
    Footprint3DModel,
    FootprintInstance,
    Pad,
    Zone,
    to_concrete_board_shape,
)
from kipy.geometry import Angle
from kipy.proto.common import types as common_types
from kipy.proto.common.types.base_types_pb2 import Vector2 as VectorProto

RotationAttribute = Literal["angle", "orientation"]
_SUPPORTED_ROTATION_ATTRIBUTES: tuple[RotationAttribute, ...] = ("angle", "orientation")


class FootprintRotationError(RuntimeError):
    """Raised when a requested footprint rotation cannot be applied or verified."""


def _rotation_degrees(value: object) -> float:
    if isinstance(value, Angle):
        return float(value.degrees)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    degrees = getattr(value, "degrees", None)
    if isinstance(degrees, int | float) and not isinstance(degrees, bool):
        return float(degrees)
    raise FootprintRotationError("Footprint rotation value does not expose numeric degrees.")


def _restore_missing_3d_models(definition: object | None, original_models: list[object]) -> None:
    """Work around kicad-python 0.7/0.8 orientation setter dropping 3D models."""
    if definition is None or not original_models:
        return
    existing = getattr(definition, "models", ())
    missing = [model for model in original_models if not any(model is item for item in existing)]
    if missing:
        preserved = cast(Any, definition)
        preserved.items = [*preserved.items, *missing]


def _geometry_vectors(message: Message) -> Iterator[VectorProto]:
    """Traverse geometry-only messages, never padstack offsets or 3D models."""
    if isinstance(message, VectorProto):
        yield message
        return
    for descriptor, value in message.ListFields():
        if descriptor.message_type is None:
            continue
        if descriptor.label == FieldDescriptor.LABEL_REPEATED:
            for child in value:
                yield from _geometry_vectors(child)
        else:
            yield from _geometry_vectors(value)


def _world_vectors(footprint: FootprintInstance) -> Iterator[VectorProto]:
    for field in (
        footprint.reference_field,
        footprint.value_field,
        footprint.datasheet_field,
        footprint.description_field,
    ):
        yield field.proto.text.text.position
    for item in footprint.definition.items:
        yield from _item_world_vectors(item)


def _item_world_vectors(item: object) -> Iterator[VectorProto]:
    if isinstance(item, Field):
        yield item.proto.text.text.position
    elif isinstance(item, BoardText):
        yield item.proto.text.position
    elif isinstance(item, Pad):
        yield item.proto.position
    elif isinstance(item, Zone):
        yield from _geometry_vectors(item.proto.outline)
        for filled in item.proto.filled_polygons:
            yield from _geometry_vectors(filled)
    elif isinstance(item, BoardPolygon):
        # The SDK concrete-shape conversion reads the packed proto.
        # Synchronize cached polygons before that conversion.
        _ = item.proto
        for polygon in item.polygons:
            yield from _geometry_vectors(polygon.proto)
    elif isinstance(item, BoardShape):
        shape = item.proto.shape
        geometry = shape.WhichOneof("geometry")
        if geometry is not None:
            yield from _geometry_vectors(getattr(shape, geometry))


def _cardinal_world_positions(
    footprint: FootprintInstance, quarter_turns: int
) -> list[tuple[int, int]]:
    """KiCad's orthogonal rotations are exact integer nanometer transforms."""
    cx, cy = footprint.position.x, footprint.position.y
    result: list[tuple[int, int]] = []
    for vector in _world_vectors(footprint):
        x, y = vector.x_nm - cx, vector.y_nm - cy
        for _ in range(quarter_turns % 4):
            x, y = y, -x
        result.append((x + cx, y + cy))
    return result


_GEOMETRY_STRUCTURE_CHANGED = "Footprint geometry changed structure during rotation."


def _restore_cardinal_world_positions(
    footprint: FootprintInstance, expected: list[tuple[int, int]]
) -> None:
    vectors = list(_world_vectors(footprint))
    if len(vectors) != len(expected):
        raise FootprintRotationError(_GEOMETRY_STRUCTURE_CHANGED)
    for vector, (x, y) in zip(vectors, expected, strict=True):
        vector.x_nm, vector.y_nm = x, y


def _native_round(value: float) -> int:
    """KiCad KiROUND uses nearest integer, with halves away from zero."""
    magnitude = abs(value)
    integral = math.floor(magnitude)
    rounded = integral + int(magnitude - integral >= 0.5)
    return rounded if value >= 0 else -rounded


def _rotation_children(footprint: FootprintInstance) -> Iterator[object]:
    yield footprint.reference_field
    yield footprint.value_field
    yield footprint.datasheet_field
    yield footprint.description_field
    for item in footprint.definition.items:
        if not isinstance(item, Footprint3DModel):
            yield item


def _geometry_topology(message: Message) -> bytes:
    """Compare geometry structure independently of the coordinate values."""
    copy = type(message)()
    copy.CopyFrom(message)
    for vector in _geometry_vectors(copy):
        vector.x_nm = 0
        vector.y_nm = 0
    return cast(bytes, copy.SerializeToString(deterministic=True))


_RotationChildKey = tuple[str, bytes, str | None, tuple[bytes, ...]]


def _rotation_child_key(item: object) -> _RotationChildKey:
    if not isinstance(item, (Field, BoardText, Pad, Zone, BoardShape)):
        raise FootprintRotationError("Unsupported footprint child during rotation.")
    proto = item.proto
    kind = None
    topology: tuple[bytes, ...] = ()
    if isinstance(item, BoardShape):
        kind = proto.shape.WhichOneof("geometry")
        if kind is not None:
            topology = (_geometry_topology(getattr(proto.shape, kind)),)
    elif isinstance(item, Zone):
        topology = (
            _geometry_topology(proto.outline),
            *(_geometry_topology(filled) for filled in proto.filled_polygons),
        )
    return proto.DESCRIPTOR.full_name, proto.id.SerializeToString(), kind, topology


_RotationPlan = list[tuple[_RotationChildKey, list[tuple[int, int]]]]


def _noncardinal_rotation_plan(footprint: FootprintInstance, delta: float) -> _RotationPlan:
    cx, cy = footprint.position.x, footprint.position.y
    sine, cosine = math.sin(math.radians(delta)), math.cos(math.radians(delta))
    result: _RotationPlan = []
    for item in _rotation_children(footprint):
        if isinstance(item, BoardShape):
            # Match the SDK's deliberate rectangle-to-polygon conversion without
            # altering the original footprint or replacing library geometry.
            _ = item.proto
            shape = to_concrete_board_shape(item)
            if isinstance(shape, BoardRectangle):
                item = BoardPolygon.from_rectangle(shape)
        key = _rotation_child_key(item)
        positions = []
        for vector in _item_world_vectors(item):
            x, y = vector.x_nm - cx, vector.y_nm - cy
            positions.append(
                (
                    _native_round(y * sine + x * cosine) + cx,
                    _native_round(y * cosine - x * sine) + cy,
                )
            )
        result.append((key, positions))
    return result


def _restore_noncardinal_positions(footprint: FootprintInstance, plan: _RotationPlan) -> None:
    children = list(_rotation_children(footprint))
    if len(children) != len(plan):
        raise FootprintRotationError(_GEOMETRY_STRUCTURE_CHANGED)
    pending: list[tuple[VectorProto, tuple[int, int]]] = []
    for item, (key, positions) in zip(children, plan, strict=True):
        actual_key = _rotation_child_key(item)
        vectors = list(_item_world_vectors(item))
        if actual_key != key or len(vectors) != len(positions):
            raise FootprintRotationError(_GEOMETRY_STRUCTURE_CHANGED)
        pending.extend(zip(vectors, positions, strict=True))
    # Verify every child before modifying any coordinates.
    for vector, (x, y) in pending:
        vector.x_nm, vector.y_nm = x, y


def get_current_footprint_rotation(footprint: object) -> tuple[RotationAttribute, float]:
    """Read the existing writable rotation surface without assigning a new angle."""
    failures: list[str] = []
    available: list[RotationAttribute] = []
    for attribute in _SUPPORTED_ROTATION_ATTRIBUTES:
        try:
            value = getattr(footprint, attribute)
        except AttributeError:
            continue
        available.append(attribute)
        try:
            return attribute, _rotation_degrees(value)
        except FootprintRotationError as exc:
            failures.append(f"{attribute}: {exc}")
    if not available:
        raise FootprintRotationError(
            "Footprint does not expose a supported angle or orientation surface."
        )
    detail = ", ".join(failures) if failures else ", ".join(available)
    raise FootprintRotationError(f"Current footprint rotation could not be read ({detail}).")


def apply_footprint_rotation(footprint: object, rotation_deg: float) -> RotationAttribute:
    """Assign a KiCad ``Angle`` through the first writable rotation surface."""
    if not math.isfinite(rotation_deg):
        raise FootprintRotationError("Requested footprint rotation must be finite.")

    requested = Angle.from_degrees(rotation_deg)
    available: list[RotationAttribute] = []
    failures: list[str] = []
    for attribute in _SUPPORTED_ROTATION_ATTRIBUTES:
        try:
            getattr(footprint, attribute)
        except AttributeError:
            continue
        available.append(attribute)
        failure = _apply_rotation_attribute(footprint, attribute, requested, rotation_deg)
        if failure is None:
            return attribute
        failures.append(failure)

    if not available:
        raise FootprintRotationError(
            "Footprint does not expose a supported angle or orientation surface."
        )
    detail = ", ".join(failures) if failures else ", ".join(available)
    raise FootprintRotationError(f"Requested footprint rotation could not be applied ({detail}).")


def native_text_rotation(angle: float, *, keep_upright: bool) -> tuple[float, bool]:
    """Match KiCad footprint Rotate/KeepUpright after applying the child angle delta."""
    normalized = angle % 360
    if keep_upright and normalized >= 180:
        return normalized - 180, True
    return normalized, False


def _footprint_texts(footprint: FootprintInstance) -> Iterator[BoardText]:
    for field in (
        footprint.reference_field,
        footprint.value_field,
        footprint.datasheet_field,
        footprint.description_field,
    ):
        yield field.text
    for item in footprint.definition.items:
        if isinstance(item, Field):
            yield item.text
        elif isinstance(item, BoardText):
            yield item


def _normalize_footprint_text(footprint: FootprintInstance) -> None:
    horizontal = {
        common_types.HA_LEFT: common_types.HA_RIGHT,
        common_types.HA_RIGHT: common_types.HA_LEFT,
    }
    vertical = {
        common_types.VA_TOP: common_types.VA_BOTTOM,
        common_types.VA_BOTTOM: common_types.VA_TOP,
    }
    for text in _footprint_texts(footprint):
        attrs = text.attributes
        angle, flipped = native_text_rotation(attrs.angle, keep_upright=attrs.keep_upright)
        attrs.angle = angle
        if flipped:
            attrs.horizontal_alignment = horizontal.get(
                attrs.horizontal_alignment, attrs.horizontal_alignment
            )
            attrs.vertical_alignment = vertical.get(
                attrs.vertical_alignment, attrs.vertical_alignment
            )


def _expected_cardinal_positions(
    footprint: object, current_deg: float | None, rotation_deg: float
) -> list[tuple[int, int]] | None:
    if not isinstance(footprint, FootprintInstance) or current_deg is None:
        return None
    delta = (rotation_deg - current_deg) % 360
    if delta % 90 == 0:
        return _cardinal_world_positions(footprint, int(delta // 90))
    return None


def _apply_rotation_attribute(
    footprint: object, attribute: RotationAttribute, requested: Angle, rotation_deg: float
) -> str | None:
    # kicad-python <= 0.8.0 reconstructs definition.items when orientation
    # is assigned and silently drops 3D models. Avoid a no-op assignment
    # altogether, then restore only lost models after an actual rotation.
    try:
        current_deg = _rotation_degrees(getattr(footprint, attribute))
    except FootprintRotationError:
        current_deg = None
    if current_deg is not None and abs((current_deg - rotation_deg + 180) % 360 - 180) < 1e-9:
        return None
    definition = getattr(footprint, "definition", None)
    models_before = list(getattr(definition, "models", ()))
    expected_positions = _expected_cardinal_positions(footprint, current_deg, rotation_deg)
    noncardinal_plan = None
    if (
        isinstance(footprint, FootprintInstance)
        and current_deg is not None
        and expected_positions is None
    ):
        noncardinal_plan = _noncardinal_rotation_plan(footprint, (rotation_deg - current_deg) % 360)
    try:
        setattr(footprint, attribute, requested)
    except Exception as exc:  # KiCad IPC surfaces raise generated transport/type errors.
        return f"{attribute}: {type(exc).__name__}"
    _restore_missing_3d_models(definition, models_before)
    if isinstance(footprint, FootprintInstance):
        if expected_positions is not None:
            _restore_cardinal_world_positions(footprint, expected_positions)
        elif noncardinal_plan is not None:
            _restore_noncardinal_positions(footprint, noncardinal_plan)
        _normalize_footprint_text(footprint)
    return None


def verify_footprint_rotation(
    footprint: object,
    attribute: RotationAttribute,
    requested_deg: float,
    *,
    tolerance_deg: float = 1e-3,
) -> float:
    """Read back and verify a footprint rotation using wrapped angular distance."""
    try:
        actual = _rotation_degrees(getattr(footprint, attribute))
    except AttributeError as exc:
        raise FootprintRotationError(
            f"Footprint rotation verification failed: '{attribute}' is unavailable."
        ) from exc

    delta = (actual - requested_deg + 180.0) % 360.0 - 180.0
    if abs(delta) > tolerance_deg:
        raise FootprintRotationError(
            "Footprint rotation verification failed: "
            f"requested {requested_deg:.6f} degrees, observed {actual:.6f} degrees."
        )
    return actual
