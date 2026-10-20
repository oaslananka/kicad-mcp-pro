"""Compatibility exports for the shared validation gate domain."""

from ..validation.gates import (
    GateOutcome as GateOutcome,
)
from ..validation.gates import (
    GateStatus as GateStatus,
)
from ..validation.gates import (
    combined_status as _combined_status,
)

__all__ = ["GateOutcome", "GateStatus", "_combined_status"]
