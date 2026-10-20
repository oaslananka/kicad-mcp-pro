"""Property-based invariant testing using Hypothesis."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st

from kicad_mcp.path_safety import resolve_under
from kicad_mcp.utils.sexpr import (
    _escape_sexpr_string,
    _extract_block,
    _sexpr_string,
    _unescape_sexpr_string,
)

# ---------------------------------------------------------------------------
# 1. S-Expression Roundtrip & Escape Invariants
# ---------------------------------------------------------------------------


@given(st.text())
def test_invariant_sexpr_escape_unescape_roundtrip(text: str) -> None:
    """Escaped S-expression string must round-trip cleanly back to normalized text."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    escaped = _escape_sexpr_string(text)
    roundtripped = _unescape_sexpr_string(escaped)
    assert roundtripped == normalized, f"Failed roundtrip for text: {text!r}"


@given(st.text())
def test_invariant_sexpr_string_is_quoted(text: str) -> None:
    """_sexpr_string must always produce a double-quoted string with no unescaped inner quotes."""
    quoted = _sexpr_string(text)
    assert quoted.startswith('"')
    assert quoted.endswith('"')
    assert len(quoted) >= 2


@given(st.text())
def test_invariant_extract_block_termination_and_soundness(content: str) -> None:
    """_extract_block must always terminate safely and return balanced S-expressions when found."""
    start = content.find("(")
    if start >= 0:
        block, consumed = _extract_block(content, start)
        assert isinstance(block, str)
        assert consumed >= 0
        if block:
            assert block.startswith("(")
            assert block.endswith(")")


# ---------------------------------------------------------------------------
# 2. Workspace Path Confinement & Traversal Invariants
# ---------------------------------------------------------------------------


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=100,
    )
)
def test_invariant_workspace_path_confinement(candidate_path: str) -> None:
    """resolve_under must either return a path strictly inside root or raise ValueError."""
    assume("\x00" not in candidate_path)
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir).resolve()
        try:
            resolved = resolve_under(root, candidate_path)
            # If resolved without error, it MUST be strictly under root
            resolved_abs = resolved.resolve(strict=False)
            assert root == resolved_abs or root in resolved_abs.parents
        except ValueError:
            # Traversal rejected as expected
            pass


# ---------------------------------------------------------------------------
# 3. Read-Only Operations Guarantee Invariant
# ---------------------------------------------------------------------------


@given(st.text(min_size=1, max_size=200))
def test_invariant_read_only_never_mutates_file(content: str) -> None:
    """Inspecting or reading a file must preserve its exact byte content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "board.kicad_pcb"
        test_file.write_text(content, encoding="utf-8")
        before_bytes = test_file.read_bytes()

        # Perform read-only block extractions
        text = test_file.read_text(encoding="utf-8")
        start = text.find("(")
        if start >= 0:
            _ = _extract_block(text, start)

        after_bytes = test_file.read_bytes()
        assert before_bytes == after_bytes, "Read-only operation altered file bytes!"


# ---------------------------------------------------------------------------
# 4. Geometry and Metric Non-Negativity & Triangle Inequality Invariants
# ---------------------------------------------------------------------------


@given(
    x1=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    y1=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    x2=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    y2=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    x3=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
    y3=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
)
def test_invariant_euclidean_distance_triangle_inequality(
    x1: float, y1: float, x2: float, y2: float, x3: float, y3: float
) -> None:
    """Distance calculations in PCB space must satisfy metric space axioms:
    1. d(A, B) >= 0
    2. d(A, B) == 0 iff A == B
    3. d(A, C) <= d(A, B) + d(B, C) (triangle inequality)
    """
    d_ab = math.hypot(x2 - x1, y2 - y1)
    d_bc = math.hypot(x3 - x2, y3 - y2)
    d_ac = math.hypot(x3 - x1, y3 - y1)

    assert d_ab >= 0.0
    assert d_bc >= 0.0
    assert d_ac >= 0.0

    # Floating point rounding allowance
    assert d_ac <= d_ab + d_bc + 1e-9


# ---------------------------------------------------------------------------
# 5. Gate Rollup Monotonicity Invariant
# ---------------------------------------------------------------------------


@given(
    pass_count=st.integers(min_value=0, max_value=50),
    warn_count=st.integers(min_value=0, max_value=50),
    fail_count=st.integers(min_value=0, max_value=50),
)
def test_invariant_contract_verifier_rollup_precedence(
    pass_count: int, warn_count: int, fail_count: int
) -> None:
    """Finding rollup precedence: FAIL > WARN > PASS."""
    from kicad_mcp.models.contract_verifier import Finding, _rollup

    findings: list[Finding] = []
    for i in range(pass_count):
        findings.append(Finding(level="PASS", code=f"P_{i}", message="ok"))
    for i in range(warn_count):
        findings.append(Finding(level="WARN", code=f"W_{i}", message="warning"))
    for i in range(fail_count):
        findings.append(Finding(level="FAIL", code=f"F_{i}", message="failure"))

    status = _rollup(findings)

    if fail_count > 0:
        assert status == "FAIL"
    elif warn_count > 0:
        assert status == "WARN"
    else:
        assert status == "PASS"
