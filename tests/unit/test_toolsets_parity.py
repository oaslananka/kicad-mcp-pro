"""Toolsets ↔ router profile parity (work order P1-T2).

``integrations/common/toolsets.json`` is generated from the router profile source of
truth. These tests enforce that it never drifts, that every tool it lists is really
registered (no stale/helper names), and that the four names shared with router
profiles map to the identically named profile so "same name, same tools" holds.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import scripts.build_toolsets as builder
from kicad_mcp.tools.router import PROFILE_CATEGORIES

SHARED_NAMES = ("schematic", "manufacturing", "simulation", "high_speed")


@pytest.fixture(scope="module")
def toolsets() -> dict[str, Any]:
    return json.loads(builder.TOOLSETS_PATH.read_text(encoding="utf-8"))


def test_toolsets_not_drifted() -> None:
    assert builder.main(["--check"]) == 0, "Run: uv run python scripts/build_toolsets.py"


def test_every_toolset_tool_is_registered(
    toolsets: dict[str, Any], registered_tool_names: set[str]
) -> None:
    for name, entry in toolsets["toolsets"].items():
        unknown = sorted(set(entry["tools"]) - registered_tool_names)
        assert not unknown, f"toolset '{name}' lists unregistered tools: {unknown}"


def test_toolset_profiles_exist() -> None:
    for name, (profile, *_rest) in builder.TOOLSETS.items():
        assert profile in PROFILE_CATEGORIES, f"toolset '{name}' -> unknown profile '{profile}'"


def test_shared_names_map_to_same_router_profile() -> None:
    for name in SHARED_NAMES:
        assert name in builder.TOOLSETS, f"shared name '{name}' missing from toolsets map"
        assert name in PROFILE_CATEGORIES, f"shared name '{name}' missing from router profiles"
        assert builder.TOOLSETS[name][0] == name, (
            f"toolset '{name}' must map to the identically named router profile"
        )
