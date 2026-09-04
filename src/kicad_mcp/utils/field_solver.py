"""Field-solver adapter seam for impedance/coupling (work order P3-T1).

The impedance/coupling path uses published quasi-static closed-form formulas
(IPC-2141 / Wheeler-class). Those are first-order estimates — good to a few
percent, **not** a 2D field-solver result. This module is the seam where a real
solver (FEMM, atlc, a boundary-element method, or a hosted service) would plug in.

Until one is wired, :func:`field_solver_available` returns ``False`` and callers
must label results with :func:`impedance_method` so a number never implies more
accuracy than the method that produced it. This is the honest fallback the work
order mandates: surface "no field solver" explicitly rather than passing a
closed-form estimate off as solver-grade.
"""

from __future__ import annotations

from typing import Any

from .solver_seams import solver_verdict_metadata

CLOSED_FORM_METHOD = "closed-form (IPC-2141 / Wheeler quasi-static)"
CLOSED_FORM_ACCURACY = "first-order, typically within ~5-10% of a 2D field solver"


def field_solver_available() -> bool:
    """Return ``True`` only when a real 2D/2.5D field solver is integrated.

    No solver is wired yet, so this is ``False`` and impedance/coupling results
    must be labeled as the closed-form method.
    """
    return False


def impedance_method() -> dict[str, Any]:
    """Describe the active impedance computation method, honestly."""
    return {
        "method": CLOSED_FORM_METHOD,
        "solver_grade": False,
        "accuracy": CLOSED_FORM_ACCURACY,
        **solver_verdict_metadata(solver_grade=False),
        "note": (
            "No 2D field solver is integrated; this is a closed-form estimate, not a "
            "solver-grade or sign-off impedance figure."
        ),
    }
