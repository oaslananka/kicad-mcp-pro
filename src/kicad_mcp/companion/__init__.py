"""KiCad companion-plugin support (issue #157).

Pure, stdlib-only helpers shared by the KiCad Action Plugin in
``packages/kicad-plugin``: building the studio context payload from a live board
and pushing it to a running kicad-mcp-pro server. Kept free of ``pcbnew`` and of any
third-party dependency so it imports inside KiCad's bundled Python and is unit
testable without KiCad.
"""

from .context import (
    SAFE_APPLY_ACTIONS,
    BoardInfo,
    StudioContextClient,
    build_studio_context,
    requires_confirmation,
)

__all__ = [
    "SAFE_APPLY_ACTIONS",
    "BoardInfo",
    "StudioContextClient",
    "build_studio_context",
    "requires_confirmation",
]
