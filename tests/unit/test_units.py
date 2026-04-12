from __future__ import annotations

import pytest

from kicad_mcp.utils.units import mm_to_nm, nm_to_mm


def test_mm_to_nm_roundtrip() -> None:
    assert nm_to_mm(mm_to_nm(1.5)) == pytest.approx(1.5)


def test_mm_to_nm_precision() -> None:
    assert mm_to_nm(0.001) == 1000
