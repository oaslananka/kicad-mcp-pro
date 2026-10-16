"""Force-directed placement utilities for PCB components.

Implements a spring-embedder algorithm where:
- Connected components attract each other (spring force).
- All components repel each other (Coulomb force).
- Boundary walls push components inward.

The algorithm is unit-free; callers supply coordinates in mm and receive mm back.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Point(NamedTuple):
    x: float
    y: float


@dataclass
class PlacementComponent:
    ref: str
    x: float
    y: float
    # width / height in mm (bounding box)
    w: float = 2.0
    h: float = 2.0
    fixed: bool = False


@dataclass
class PlacementNet:
    """A net connects a set of component refs."""

    name: str
    refs: list[str] = field(default_factory=list)
    # weight controls spring stiffness (higher = pulled closer)
    weight: float = 1.0


@dataclass
class ForceDirectedConfig:
    iterations: int = 300
    k_spring: float = 0.4  # spring attraction coefficient
    k_repel: float = 80.0  # Coulomb repulsion coefficient
    k_wall: float = 5.0  # boundary wall coefficient
    damping: float = 0.85  # velocity damping per step
    min_dist: float = 0.5  # minimum distance to avoid div/0
    board_w: float = 100.0  # board width (mm) — soft boundary
    board_h: float = 80.0  # board height (mm) — soft boundary
    seed: int = 42
    grid_mm: float = 0.5
    # Deterministic early stop: iteration halts once the grid-snapped layout —
    # the actual deliverable — stays unchanged for this many consecutive
    # iterations. Because it depends only on geometry (never on wall-clock) the
    # result is reproducible bit-for-bit across machines, and snapping makes it
    # robust to the sub-grid jitter the cooling floor leaves behind. Set it to
    # <= 0 to always run the full ``iterations`` count.
    convergence_patience: int = 4
    # Optional wall-clock safety valve (seconds). 0 (the default) disables it so
    # placement stays deterministic. A positive value bounds runtime on
    # pathologically large boards but makes the result depend on host speed —
    # i.e. NOT reproducible — so use it only as a last resort.
    max_seconds: float = 0.0
    keepout_regions: list[tuple[float, float, float, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def _centroid(comps: list[PlacementComponent], refs: list[str]) -> Point:
    xs = [c.x for c in comps if c.ref in refs]
    ys = [c.y for c in comps if c.ref in refs]
    if not xs:
        return Point(0.0, 0.0)
    return Point(sum(xs) / len(xs), sum(ys) / len(ys))


def _snap(value: float, grid_mm: float) -> float:
    if grid_mm <= 0:
        return value
    return round(round(value / grid_mm) * grid_mm, 4)


def _component_bounds(
    x: float,
    y: float,
    component: PlacementComponent,
) -> tuple[float, float, float, float]:
    return (
        x - (component.w / 2.0),
        y - (component.h / 2.0),
        x + (component.w / 2.0),
        y + (component.h / 2.0),
    )


def _inside_board(
    x: float,
    y: float,
    component: PlacementComponent,
    cfg: ForceDirectedConfig,
) -> bool:
    left, top, right, bottom = _component_bounds(x, y, component)
    return left >= 0.0 and top >= 0.0 and right <= cfg.board_w and bottom <= cfg.board_h


def _hits_keepout(
    x: float,
    y: float,
    component: PlacementComponent,
    cfg: ForceDirectedConfig,
) -> bool:
    left, top, right, bottom = _component_bounds(x, y, component)
    for x1, y1, x2, y2 in cfg.keepout_regions:
        keepout_left = min(x1, x2)
        keepout_top = min(y1, y2)
        keepout_right = max(x1, x2)
        keepout_bottom = max(y1, y2)
        if not (
            right <= keepout_left
            or left >= keepout_right
            or bottom <= keepout_top
            or top >= keepout_bottom
        ):
            return True
    return False


def _resolve_candidate_position(
    x: float,
    y: float,
    component: PlacementComponent,
    cfg: ForceDirectedConfig,
    *,
    snap_to_grid: bool,
) -> tuple[float, float]:
    def normalize(candidate_x: float, candidate_y: float) -> tuple[float, float]:
        resolved_x = candidate_x
        resolved_y = candidate_y
        if snap_to_grid:
            resolved_x = _snap(resolved_x, cfg.grid_mm)
            resolved_y = _snap(resolved_y, cfg.grid_mm)
        return resolved_x, resolved_y

    candidate = normalize(x, y)
    if _inside_board(*candidate, component, cfg) and not _hits_keepout(*candidate, component, cfg):
        return candidate

    search_step = max(cfg.grid_mm / 2.0, 0.25)
    phase = cfg.seed % 4
    directions = [
        (1, 0),
        (0, 1),
        (-1, 0),
        (0, -1),
    ]
    directions = directions[phase:] + directions[:phase]
    for ring in range(1, 33):
        for dx, dy in directions:
            for offset in range(-ring, ring + 1):
                if dx == 0:
                    candidate = normalize(x + (offset * search_step), y + (dy * ring * search_step))
                else:
                    candidate = normalize(x + (dx * ring * search_step), y + (offset * search_step))
                if _inside_board(*candidate, component, cfg) and not _hits_keepout(
                    *candidate,
                    component,
                    cfg,
                ):
                    return candidate

    safe_x = min(max(component.w / 2.0, x), cfg.board_w - component.w / 2.0)
    safe_y = min(max(component.h / 2.0, y), cfg.board_h - component.h / 2.0)
    return normalize(safe_x, safe_y)


def force_directed_placement(
    components: list[PlacementComponent],
    nets: list[PlacementNet],
    cfg: ForceDirectedConfig | None = None,
    *,
    stats: dict[str, object] | None = None,
) -> list[PlacementComponent]:
    """Run force-directed placement and return updated component list (copies).

    Fixed components are not moved but still exert forces on others.

    Stopping is deterministic by default: iteration halts once the grid-snapped
    layout is stable for ``cfg.convergence_patience`` consecutive iterations (or
    the ``cfg.iterations`` ceiling is reached), so identical inputs yield
    bit-for-bit identical output on any machine regardless of CPU speed.
    ``cfg.max_seconds`` is an opt-in, off-by-default wall-clock safety valve only
    and, when set, sacrifices that cross-machine reproducibility.

    When ``stats`` is provided it is populated with ``iterations_run``,
    ``converged`` (bool) and ``max_displacement_mm`` so callers can report the
    convergence rationale.
    """
    if cfg is None:
        cfg = ForceDirectedConfig()

    comps = [PlacementComponent(**c.__dict__) for c in components]
    ref_idx: dict[str, int] = {c.ref: i for i, c in enumerate(comps)}

    # Velocity storage (for momentum)
    vx: list[float] = [0.0] * len(comps)
    vy: list[float] = [0.0] * len(comps)
    start_time = time.perf_counter()
    converged = False
    iterations_run = 0
    final_max_disp = 0.0
    stable_count = 0
    prev_snapshot: tuple[tuple[float, float], ...] | None = None

    # Build adjacency: for each component, which other components are connected?
    adjacency: dict[str, list[tuple[str, float]]] = {c.ref: [] for c in comps}
    for net in nets:
        for r1 in net.refs:
            for r2 in net.refs:
                if r1 != r2:
                    adjacency[r1].append((r2, net.weight))

    step_size = min(cfg.board_w, cfg.board_h) * 0.05  # initial max displacement

    for iteration in range(cfg.iterations):
        iterations_run = iteration + 1
        # Cooling: reduce step size over time
        temperature = step_size * (1.0 - iteration / cfg.iterations) + 0.1

        fx: list[float] = [0.0] * len(comps)
        fy: list[float] = [0.0] * len(comps)

        # --- Repulsion: all pairs ---
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                dx = comps[i].x - comps[j].x
                dy = comps[i].y - comps[j].y
                dist = max(math.hypot(dx, dy), cfg.min_dist)
                # Overlap clearance: if bounding boxes overlap, push harder
                min_clear = (comps[i].w + comps[j].w) * 0.5 + 1.0
                effective_k = cfg.k_repel
                if dist < min_clear:
                    effective_k *= (min_clear / dist) ** 2
                force = effective_k / (dist * dist)
                nx, ny = dx / dist, dy / dist
                fx[i] += force * nx
                fy[i] += force * ny
                fx[j] -= force * nx
                fy[j] -= force * ny

        # --- Attraction: connected pairs (spring) ---
        for i, comp in enumerate(comps):
            for neighbor_ref, weight in adjacency[comp.ref]:
                neighbor_index = ref_idx.get(neighbor_ref)
                if neighbor_index is None:
                    continue
                dx = comps[neighbor_index].x - comp.x
                dy = comps[neighbor_index].y - comp.y
                dist = max(math.hypot(dx, dy), cfg.min_dist)
                force = cfg.k_spring * weight * dist
                nx, ny = dx / dist, dy / dist
                fx[i] += force * nx
                fy[i] += force * ny

        # --- Wall repulsion (soft boundary) ---
        for i, comp in enumerate(comps):
            # Left wall
            if comp.x < comp.w:
                fx[i] += cfg.k_wall / max(comp.x, 0.01)
            # Right wall
            right_gap = cfg.board_w - comp.x - comp.w
            if right_gap < comp.w:
                fx[i] -= cfg.k_wall / max(right_gap, 0.01)
            # Top wall
            if comp.y < comp.h:
                fy[i] += cfg.k_wall / max(comp.y, 0.01)
            # Bottom wall
            bottom_gap = cfg.board_h - comp.y - comp.h
            if bottom_gap < comp.h:
                fy[i] -= cfg.k_wall / max(bottom_gap, 0.01)

        # --- Integrate ---
        max_disp = 0.0
        for i, comp in enumerate(comps):
            if comp.fixed:
                vx[i] = 0.0
                vy[i] = 0.0
                continue
            vx[i] = (vx[i] + fx[i]) * cfg.damping
            vy[i] = (vy[i] + fy[i]) * cfg.damping
            # Clamp displacement by temperature
            speed = math.hypot(vx[i], vy[i])
            if speed > temperature:
                vx[i] = vx[i] / speed * temperature
                vy[i] = vy[i] / speed * temperature
            new_x, new_y = _resolve_candidate_position(
                comp.x + vx[i],
                comp.y + vy[i],
                comp,
                cfg,
                snap_to_grid=False,
            )
            disp = math.hypot(new_x - comp.x, new_y - comp.y)
            if disp > max_disp:
                max_disp = disp
            comp.x, comp.y = new_x, new_y

        final_max_disp = max_disp
        # Deterministic convergence stop: halt once the grid-snapped layout (the
        # deliverable) is unchanged for ``convergence_patience`` consecutive
        # iterations. Snapping makes this robust to the sub-grid jitter the
        # cooling floor leaves behind, and it depends only on geometry — never on
        # wall-clock — so the result is reproducible across machines.
        if cfg.convergence_patience > 0:
            snapshot = tuple(
                (_snap(comp.x, cfg.grid_mm), _snap(comp.y, cfg.grid_mm)) for comp in comps
            )
            if snapshot == prev_snapshot:
                stable_count += 1
                if stable_count >= cfg.convergence_patience:
                    converged = True
                    break
            else:
                stable_count = 0
            prev_snapshot = snapshot
        # Opt-in, off-by-default wall-clock safety valve (breaks determinism).
        if cfg.max_seconds > 0.0 and time.perf_counter() - start_time >= cfg.max_seconds:
            break

    for component in comps:
        if component.fixed:
            continue
        component.x, component.y = _resolve_candidate_position(
            component.x,
            component.y,
            component,
            cfg,
            snap_to_grid=True,
        )

    if stats is not None:
        stats["iterations_run"] = iterations_run
        stats["converged"] = converged
        stats["max_displacement_mm"] = round(final_max_disp, 6)

    return comps


# ---------------------------------------------------------------------------
# BGA fanout geometry helpers
# ---------------------------------------------------------------------------


@dataclass
class BGABall:
    row: str  # A, B, C … (IPC row letter)
    col: int  # 1-based column index
    net: str
    x_mm: float = 0.0
    y_mm: float = 0.0


def generate_bga_fanout_plan(
    balls: list[BGABall],
    pitch_mm: float,
    via_drill_mm: float = 0.2,
    via_annular_mm: float = 0.1,
    escape_layer: str = "In1.Cu",
    strategy: str = "dog_ear",
) -> list[dict[str, object]]:
    """Return a list of via-placement descriptors for BGA fanout.

    Each descriptor has:
      ref: ball reference (e.g. "A1")
      net: net name
      ball_x, ball_y: ball center in mm
      via_x, via_y: via center in mm
      escape_layer: inner layer to fan out to
      track_width_mm: suggested track width (0.1 mm for 0.5mm pitch, 0.15 for 0.8mm+)
      dog_ear_dir: (dx, dy) unit direction of the short stub

    Strategies:
      dog_ear   — via offset diagonally ~0.5*pitch from ball center (most common)
      inline    — via directly below ball on adjacent row (for 1mm+ pitch)
    """
    track_w = 0.1 if pitch_mm <= 0.65 else 0.15

    vias: list[dict[str, object]] = []
    for ball in balls:
        bx, by = ball.x_mm, ball.y_mm

        if strategy == "dog_ear":
            # Diagonal escape direction depends on quadrant — use simple alternating pattern
            # For a real layout this would be quadrant-aware; here we use a hash-based approach
            col_odd = ball.col % 2
            row_ord = ord(ball.row[0]) - ord("A")
            row_odd = row_ord % 2
            dx = 1.0 if (col_odd ^ row_odd) == 0 else -1.0
            dy = 1.0 if row_odd == 0 else -1.0
            # Normalize diagonal
            magnitude = math.hypot(dx, dy)
            dx /= magnitude
            dy /= magnitude
            offset = pitch_mm * 0.55
            vx = bx + dx * offset
            vy = by + dy * offset
        else:  # inline
            # Place via directly to the right/left alternating by column
            dx = 1.0 if ball.col % 2 == 0 else -1.0
            dy = 0.0
            vx = bx + dx * pitch_mm
            vy = by

        vias.append(
            {
                "ref": f"{ball.row}{ball.col}",
                "net": ball.net,
                "ball_x": round(bx, 4),
                "ball_y": round(by, 4),
                "via_x": round(vx, 4),
                "via_y": round(vy, 4),
                "via_drill_mm": via_drill_mm,
                "via_annular_mm": via_annular_mm,
                "escape_layer": escape_layer,
                "track_width_mm": track_w,
                "dog_ear_dx": round(dx if strategy == "dog_ear" else 0.0, 4),
                "dog_ear_dy": round(dy if strategy == "dog_ear" else 0.0, 4),
            }
        )

    return vias
