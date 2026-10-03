from __future__ import annotations

import importlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from kicad_mcp.manufacturing.test_plan import ManufacturingTestPlanService


def _service_module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.test_plan")
    assert spec is not None, "Manufacturing test-plan service module must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.test_plan")


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        power_rails=[
            SimpleNamespace(
                name="+3V3",
                voltage_v=3.3,
                current_max_a=1.0,
                tolerance_pct=5.0,
                source_ref="U1",
            )
        ],
        critical_nets=["USB_DP"],
        interfaces=[SimpleNamespace(kind="usb2", refs=["J1"])],
        compliance=[SimpleNamespace(kind="ce_emc", notes="pre-scan")],
    )


@pytest.fixture
def service(tmp_path: Path) -> ManufacturingTestPlanService:
    module = _service_module()
    return module.ManufacturingTestPlanService(
        resolve_output_path=lambda path: (tmp_path / path).resolve(),
        now=lambda: datetime(2026, 10, 3, 0, 0, tzinfo=UTC),
    )


def test_render_preserves_design_intent_sections_and_deterministic_timestamp(service) -> None:  # type: ignore[no-untyped-def]
    text = service.create(_intent())

    assert "Generated: 2026-10-03 00:00 UTC" in text
    assert "| 1 | +3V3 | 3.30V | 1.0A | [3.135, 3.465]V | Measure at U1" in text
    assert "Probe `USB_DP`" in text
    assert "Verify USB enumeration" in text
    assert "Prepare for **CE_EMC** certification." in text
    assert "Note: pre-scan" in text


def test_render_preserves_empty_intent_fallbacks(service) -> None:  # type: ignore[no-untyped-def]
    intent = SimpleNamespace(power_rails=[], critical_nets=[], interfaces=[], compliance=[])

    text = service.create(intent)

    assert "Apply primary supply" in text
    assert "No critical nets defined in design intent" in text
    assert "No interfaces defined in design intent" in text
    assert "## 5. Compliance Pre-Checks" not in text


def test_output_path_write_and_overwrite_policy_are_preserved(service, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    intent = SimpleNamespace(power_rails=[], critical_nets=[], interfaces=[], compliance=[])

    first = service.create(intent, output_path="bringup/test_plan.md")
    out_file = tmp_path / "bringup" / "test_plan.md"
    assert first.startswith(f"Test plan saved to {out_file}\n\n")
    assert out_file.exists()

    refused = service.create(intent, output_path="bringup/test_plan.md")
    assert refused == (
        "Refusing to overwrite an existing test plan without confirmation.\n"
        f"- Existing file: {out_file}\n"
        "Rerun with confirm_overwrite=true or choose a different output_path."
    )

    overwritten = service.create(
        intent,
        output_path="bringup/test_plan.md",
        confirm_overwrite=True,
    )
    assert overwritten.startswith(f"Test plan saved to {out_file}\n\n")
