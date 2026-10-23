"""Keep the legacy PCB writer's fail-closed s-expression validation stable."""

from __future__ import annotations

import pytest

from kicad_mcp.tools.pcb import _validate_board_text


@pytest.mark.parametrize(
    "text",
    [
        "(kicad_pcb)",
        '(kicad_pcb (gr_text "( not a real opening bracket )"))',
        '(kicad_pcb (gr_text "( unmatched parenthesis"))',
        r'(kicad_pcb (gr_text "escaped \"quote\" and ( )"))',
        r'(kicad_pcb (gr_text "double backslash \\"))',
        "",  # Preserve existing syntactic-only validator semantics.
    ],
)
def test_board_text_validator_accepts_existing_valid_cases(text: str) -> None:
    _validate_board_text(text)


@pytest.mark.parametrize(
    "text",
    [
        ")(",  # Early closing paren cannot be balanced by later opening.
        "(kicad_pcb",
        "(kicad_pcb))",
        '(kicad_pcb (gr_text "unterminated))',
        '(kicad_pcb (gr_text "escaped quote \\" remains in string))',
    ],
)
def test_board_text_validator_rejects_existing_invalid_cases(text: str) -> None:
    with pytest.raises(ValueError, match="Refusing to write an invalid PCB file"):
        _validate_board_text(text)
