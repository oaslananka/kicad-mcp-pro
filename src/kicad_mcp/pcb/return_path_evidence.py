"""Bounded observations of stored copper fill, not physical return-current analysis."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from kipy.geometry import PolygonWithHoles, PolyLine
from kipy.proto.board.board_types_pb2 import BoardLayer

from .geometry import SegmentTrack, point_xy_mm

Point = tuple[float, float]
Ring = tuple[Point, ...]
_SAMPLE_STEP_MM = 0.1
_MAX_SAMPLES = 4096
_MAX_EDGES = 100_000
_MAX_EDGE_CHECKS = 2_000_000


def _ring(polyline: PolyLine) -> Ring:
    if not polyline.closed or not all(node.has_point for node in polyline.nodes):
        raise ValueError("unsupported or open filled contour")
    points = tuple(point_xy_mm(node.point) for node in polyline.nodes)
    if len(set(points)) < 3:
        raise ValueError("invalid filled contour")
    return points


def _inside(point: Point, ring: Ring) -> bool:
    # Even/odd crossings also handle KiCad's fractured hole contours.
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(ring, (*ring[1:], ring[0]), strict=True):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


@dataclass(frozen=True)
class _Fill:
    outline: Ring
    holes: tuple[Ring, ...]

    def contains(self, point: Point) -> bool:
        return _inside(point, self.outline) and not any(_inside(point, h) for h in self.holes)


def _read_fill(zones: Iterable[object], layer: BoardLayer.ValueType) -> list[_Fill]:
    fills: list[_Fill] = []
    for zone in zones:
        if not getattr(zone, "filled", False):
            continue
        polygons = getattr(zone, "filled_polygons", None)
        if not isinstance(polygons, dict) or not polygons.get(layer):
            raise ValueError("stored filled polygon geometry unavailable")
        for polygon in polygons[layer]:
            if not isinstance(polygon, PolygonWithHoles):
                raise ValueError("unsupported stored filled polygon geometry")
            fills.append(_Fill(_ring(polygon.outline), tuple(_ring(h) for h in polygon.holes)))
    return fills


def _track_samples(tracks: Iterable[object]) -> list[Point]:
    points: list[Point] = []
    for track in tracks:
        if hasattr(track, "mid"):
            raise ValueError("curved signal geometry unsupported")
        segment = cast(SegmentTrack, track)
        a = point_xy_mm(segment.start)
        b = point_xy_mm(segment.end)
        count = max(1, math.ceil(math.dist(a, b) / _SAMPLE_STEP_MM))
        if len(points) + count + 1 > _MAX_SAMPLES:
            raise ValueError("centerline sample budget exceeded")
        points.extend(
            (a[0] + (b[0] - a[0]) * i / count, a[1] + (b[1] - a[1]) * i / count)
            for i in range(count + 1)
        )
    return points


def describe_stored_plane(
    tracks: Iterable[object], zones: Iterable[object], layer: BoardLayer.ValueType
) -> str:
    """Report only sampled stored fill; no refill, adjacency or electrical certification."""
    try:
        fills = _read_fill(zones, layer)
        if not fills:
            return "No stored filled polygons: GND reference zone is unfilled."
        samples = _track_samples(tracks)
        edges = sum(len(f.outline) + sum(map(len, f.holes)) for f in fills)
        if edges > _MAX_EDGES or len(samples) * edges > _MAX_EDGE_CHECKS:
            raise ValueError("stored geometry work budget exceeded")
        covered = sum(any(f.contains(point) for f in fills) for point in samples)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return f"Stored fill geometry unavailable or unsupported: {exc}."
    return (
        f"Stored fill centerline samples: {covered}/{len(samples)} covered, "
        f"{len(samples) - covered} uncovered (spacing <= 0.1 mm)."
    )
