"""Unit tests for DFM profile loading and validation (FAZ 12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.tools.dfm import _available_profile_names, _load_profile


def test_available_profile_names() -> None:
    names = _available_profile_names()
    assert len(names) >= 3  # at least the bundled profiles


def test_load_profile_contains_required_keys() -> None:
    for name in _available_profile_names():
        manufacturer, tier = name.rsplit("_", 1)
        profile = _load_profile(manufacturer, tier)
        assert isinstance(profile, dict)
        if "entries" in profile:
            # Rotation-correction profiles have a different structure
            assert len(profile["entries"]) >= 1
        else:
            assert "manufacturer" in profile
            assert "tier" in profile
            assert "rules" in profile


def test_load_profile_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown DFM profile"):
        _load_profile("Nonexistent", "standard")


@pytest.mark.anyio
async def test_dfm_load_manufacturer_profile_not_found(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "experimental")
    from kicad_mcp.server import create_server
    from tests.conftest import call_tool_text

    server = create_server()
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_text(
        server, "dfm_load_manufacturer_profile", {"manufacturer": "nonexistent"}
    )
    assert "not found" in result.lower() or "error" in result.lower()


def test_jlcpcb_two_layer_pth_annular_floor_matches_documented_process() -> None:
    profile = _load_profile("JLCPCB", "standard")
    rules = profile["rules"]
    assert rules["min_annular_ring_mm"] == 0.18
    assert rules["min_pth_annular_ring_2layer_1oz_mm"] == 0.18
    assert rules["recommended_pth_annular_ring_2layer_1oz_mm"] == 0.25
    assert profile["pth_process_source"].startswith("https://jlcpcb.com/capabilities/")


def test_jlcpcb_pth_2layer_guard_reports_unverified_not_pass() -> None:
    from kicad_mcp.tools.dfm import _check_jlcpcb_pth_2layer_process_lines

    rules = _load_profile("JLCPCB", "standard")["rules"]
    lines = _check_jlcpcb_pth_2layer_process_lines(
        manufacturer="JLCPCB", rules=rules, copper_layers=2
    )
    assert len(lines) == 1
    assert lines[0].startswith("- WARN:")
    assert "0.180 mm" in lines[0]
    assert "noncircular PTH, plated slots and finished hole tolerances are not measured" in lines[0]
    assert "actual copper weight is not checked" in lines[0]
    assert "written CAM" in lines[0]


def test_jlcpcb_missing_two_layer_pth_spec_fails_closed_with_explicit_warning() -> None:
    from kicad_mcp.tools.dfm import _check_jlcpcb_pth_2layer_process_lines

    rules = dict(_load_profile("JLCPCB", "standard")["rules"])
    rules.pop("min_pth_annular_ring_2layer_1oz_mm")
    lines = _check_jlcpcb_pth_2layer_process_lines(
        manufacturer="JLCPCB", rules=rules, copper_layers=2
    )
    assert len(lines) == 1
    assert lines[0].startswith("- WARN:")
    assert "minimum is not configured" in lines[0]
    assert "written CAM acceptance" in lines[0]
    assert not any(line.startswith("- PASS:") for line in lines)


def test_other_layer_count_does_not_assert_two_layer_pth_acceptance() -> None:
    from kicad_mcp.tools.dfm import _check_jlcpcb_pth_2layer_process_lines

    rules = _load_profile("JLCPCB", "standard")["rules"]
    for layers in (None, 4):
        result = _check_jlcpcb_pth_2layer_process_lines(
            manufacturer="JLCPCB", rules=rules, copper_layers=layers
        )
        assert not any("two-layer/1-oz" in line for line in result)
