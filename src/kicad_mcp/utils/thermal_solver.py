"""2-D finite-difference steady-state thermal spreading solver (work order P3-T4).

Models lateral heat spreading in a copper plane as a thin conducting plate that loses
heat to ambient through its faces. At steady state each node obeys the screened Poisson
equation

    k*t * laplacian(T) + q'' - h*(T - T_ambient) = 0

where ``k`` is the copper thermal conductivity, ``t`` the copper thickness, ``q''`` the
areal power density injected at the source footprint, and ``h`` the combined top+bottom
convective/radiative film coefficient. This is a genuine distributed solve -- heat
conducts laterally through copper and dissipates over the whole plane -- so the peak
temperature reflects copper spreading, unlike a lumped theta_JA rule of thumb. It is not a
3-D FEA with airflow or board-stack conduction; the honest method label says so.

Pure Python (no numpy dependency); solved by successive over-relaxation with reflective
(adiabatic) plate edges.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

COPPER_CONDUCTIVITY_W_PER_M_K = 385.0
OZ_TO_THICKNESS_MM = 0.0348


@dataclass(frozen=True)
class ThermalPlaneSpec:
    """Physical description of a copper spreading plane with a single hot source."""

    power_w: float
    plane_width_mm: float
    plane_height_mm: float
    source_width_mm: float = 5.0
    source_height_mm: float = 5.0
    copper_weight_oz: float = 1.0
    ambient_c: float = 25.0
    film_coefficient_w_per_m2_k: float = 20.0
    conductivity_w_per_m_k: float = COPPER_CONDUCTIVITY_W_PER_M_K

    def validate(self) -> None:
        """Raise ``ValueError`` for non-physical parameters."""
        if self.power_w < 0:
            raise ValueError("power_w must be non-negative.")
        if self.plane_width_mm <= 0 or self.plane_height_mm <= 0:
            raise ValueError("plane dimensions must be positive.")
        if self.source_width_mm <= 0 or self.source_height_mm <= 0:
            raise ValueError("source dimensions must be positive.")
        if (
            self.source_width_mm > self.plane_width_mm
            or self.source_height_mm > self.plane_height_mm
        ):
            raise ValueError("source must fit inside the plane.")
        if self.copper_weight_oz <= 0:
            raise ValueError("copper_weight_oz must be positive.")
        if self.film_coefficient_w_per_m2_k <= 0:
            raise ValueError("film_coefficient_w_per_m2_k must be positive.")
        if self.conductivity_w_per_m_k <= 0:
            raise ValueError("conductivity_w_per_m_k must be positive.")


@dataclass(frozen=True)
class ThermalFieldResult:
    """Result of a 2-D steady-state thermal spreading solve."""

    peak_temp_c: float
    peak_rise_c: float
    average_rise_c: float
    ambient_c: float
    grid_rows: int
    grid_cols: int
    iterations: int
    converged: bool
    spreading_length_mm: float


def _grid_dim(length_mm: float, target_cells: int, span_mm: float) -> int:
    cells = round(length_mm / span_mm * target_cells)
    return max(8, min(target_cells, int(cells)))


def _build_source_grid(spec: ThermalPlaneSpec, cols: int, rows: int) -> list[list[float]]:
    src_cols = max(1, round(spec.source_width_mm / spec.plane_width_mm * cols))
    src_rows = max(1, round(spec.source_height_mm / spec.plane_height_mm * rows))
    col_start = (cols - src_cols) // 2
    row_start = (rows - src_rows) // 2
    power_per_cell = spec.power_w / (src_cols * src_rows)
    source = [[0.0 for _ in range(cols)] for _ in range(rows)]
    for r in range(row_start, row_start + src_rows):
        for c in range(col_start, col_start + src_cols):
            source[r][c] = power_per_cell
    return source


def _cell_stencil(
    r: int,
    c: int,
    rows: int,
    cols: int,
    rise: list[list[float]],
    cond_x: float,
    cond_y: float,
    sink: float,
) -> tuple[float, float]:
    neighbour_sum = 0.0
    diag = sink
    if c > 0:
        neighbour_sum += cond_x * rise[r][c - 1]
        diag += cond_x
    if c < cols - 1:
        neighbour_sum += cond_x * rise[r][c + 1]
        diag += cond_x
    if r > 0:
        neighbour_sum += cond_y * rise[r - 1][c]
        diag += cond_y
    if r < rows - 1:
        neighbour_sum += cond_y * rise[r + 1][c]
        diag += cond_y
    return neighbour_sum, diag


def solve_plane_temperature(
    spec: ThermalPlaneSpec,
    *,
    max_cells_per_side: int = 32,
    max_iterations: int = 20000,
    tolerance_c: float = 1.0e-3,
) -> ThermalFieldResult:
    """Solve steady-state copper-plane temperatures by successive over-relaxation."""
    spec.validate()
    longest = max(spec.plane_width_mm, spec.plane_height_mm)
    cols = _grid_dim(spec.plane_width_mm, max_cells_per_side, longest)
    rows = _grid_dim(spec.plane_height_mm, max_cells_per_side, longest)

    dx_m = (spec.plane_width_mm / 1000.0) / cols
    dy_m = (spec.plane_height_mm / 1000.0) / rows
    cell_area_m2 = dx_m * dy_m
    thickness_m = spec.copper_weight_oz * OZ_TO_THICKNESS_MM / 1000.0
    sheet_conductance = spec.conductivity_w_per_m_k * thickness_m  # W/K (k*t)

    # Conductance to each orthogonal neighbour and the convective sink per cell.
    cond_x = sheet_conductance * dy_m / dx_m
    cond_y = sheet_conductance * dx_m / dy_m
    sink = spec.film_coefficient_w_per_m2_k * cell_area_m2  # W/K to ambient per cell

    source = _build_source_grid(spec, cols, rows)
    rise = [[0.0 for _ in range(cols)] for _ in range(rows)]
    omega = 1.8
    iterations = 0
    converged = False
    while iterations < max_iterations:
        iterations += 1
        max_delta = 0.0
        for r in range(rows):
            for c in range(cols):
                neighbour_sum, diag = _cell_stencil(r, c, rows, cols, rise, cond_x, cond_y, sink)
                updated = (source[r][c] + neighbour_sum) / diag
                delta = updated - rise[r][c]
                rise[r][c] += omega * delta
                max_delta = max(max_delta, abs(omega * delta))
        if max_delta < tolerance_c:
            converged = True
            break

    flat = [value for row in rise for value in row]
    peak_rise = max(flat)
    average_rise = sum(flat) / len(flat)
    spreading_length_mm = math.sqrt(sheet_conductance / spec.film_coefficient_w_per_m2_k) * 1000.0
    return ThermalFieldResult(
        peak_temp_c=spec.ambient_c + peak_rise,
        peak_rise_c=peak_rise,
        average_rise_c=average_rise,
        ambient_c=spec.ambient_c,
        grid_rows=rows,
        grid_cols=cols,
        iterations=iterations,
        converged=converged,
        spreading_length_mm=spreading_length_mm,
    )
