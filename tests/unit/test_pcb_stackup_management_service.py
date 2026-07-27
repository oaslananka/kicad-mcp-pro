from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from kicad_mcp.models.pcb import StackupLayerSpec
from kicad_mcp.pcb.stackup_management import PcbStackupManagementService


def _layers() -> list[StackupLayerSpec]:
    return [
        StackupLayerSpec(
            name="F_Cu",
            type="signal",
            thickness_mm=0.035,
            material="Copper",
        ),
        StackupLayerSpec(
            name="dielectric_1",
            type="core",
            thickness_mm=1.5,
            material="FR4",
            epsilon_r=4.2,
            loss_tangent=0.018,
        ),
        StackupLayerSpec(
            name="B_Cu",
            type="signal",
            thickness_mm=0.035,
            material="Copper",
        ),
    ]


def _total(layers: list[StackupLayerSpec]) -> float:
    return round(sum(layer.thickness_mm for layer in layers), 4)


def _diagnostics(*, board_file: Path | None, status: str) -> list[str]:
    return [f"board={board_file}", f"status={status}"]


def _no_diagnostics(*, board_file: Path | None, status: str) -> list[str]:
    del board_file, status
    return []


def test_get_stackup_preserves_rendering_and_optional_fields() -> None:
    service = PcbStackupManagementService(
        current_stackup_specs=_layers,
        total_stackup_thickness_mm=_total,
        configured_board_file=lambda: Path("demo.kicad_pcb"),
        board_file_diagnostics=_diagnostics,
        is_copper_stackup_layer=lambda layer: layer.material == "Copper",
        write_stackup_state=lambda _layers: Path("stackup.json"),
        transactional_board_write=lambda mutator: mutator("board"),
        apply_stackup_to_board=lambda current, _layers: current + "::updated",
        reload_board_after_file_sync=lambda: "reloaded",
    )

    assert service.get_stackup() == "\n".join(
        [
            "Board stackup (3 layers):",
            "- 1. F_Cu | type=signal | thickness=0.0350 mm | material=Copper",
            (
                "- 2. dielectric_1 | type=core | thickness=1.5000 mm | "
                "material=FR4 | Er=4.200 | loss=0.0180"
            ),
            "- 3. B_Cu | type=signal | thickness=0.0350 mm | material=Copper",
            "- Total thickness: 1.5700 mm",
        ]
    )


def test_get_stackup_preserves_value_error_diagnostics() -> None:
    def unavailable() -> list[StackupLayerSpec]:
        raise ValueError("No stackup data is available.")

    service = PcbStackupManagementService(
        current_stackup_specs=unavailable,
        total_stackup_thickness_mm=_total,
        configured_board_file=lambda: Path("demo.kicad_pcb"),
        board_file_diagnostics=_diagnostics,
        is_copper_stackup_layer=lambda layer: layer.material == "Copper",
        write_stackup_state=lambda _layers: Path("stackup.json"),
        transactional_board_write=lambda mutator: mutator("board"),
        apply_stackup_to_board=lambda current, _layers: current,
        reload_board_after_file_sync=lambda: "reloaded",
    )

    assert service.get_stackup() == "\n".join(
        [
            "No stackup data is available.",
            "board=demo.kicad_pcb",
            "status=stackup data unavailable in active board context",
        ]
    )


def test_set_stackup_preserves_state_transaction_reload_and_message() -> None:
    events: list[object] = []

    def write_state(layers: list[StackupLayerSpec]) -> Path:
        events.append(("state", [layer.name for layer in layers]))
        return Path("stackup.json")

    def apply(current: str, layers: list[StackupLayerSpec]) -> str:
        events.append(("apply", current, [layer.name for layer in layers]))
        return current + "::updated"

    def transaction(mutator: Callable[[str], str]) -> str:
        updated = mutator("board")
        events.append(("transaction", updated))
        return "demo.kicad_pcb"

    def reload() -> str:
        events.append("reload")
        return "The PCB file was updated and KiCad was asked to reload it."

    service = PcbStackupManagementService(
        current_stackup_specs=_layers,
        total_stackup_thickness_mm=_total,
        configured_board_file=lambda: None,
        board_file_diagnostics=_no_diagnostics,
        is_copper_stackup_layer=lambda layer: layer.material.casefold() == "copper",
        write_stackup_state=write_state,
        transactional_board_write=transaction,
        apply_stackup_to_board=apply,
        reload_board_after_file_sync=reload,
    )
    raw_layers = [layer.model_dump() for layer in _layers()]

    assert service.set_stackup(raw_layers) == "\n".join(
        [
            "Configured stackup with 3 layers.",
            "- Copper layers: 2",
            "- Total thickness: 1.5700 mm",
            "- Saved stackup state: stackup.json",
            "- The PCB file was updated and KiCad was asked to reload it.",
        ]
    )
    assert events == [
        ("state", ["F_Cu", "dielectric_1", "B_Cu"]),
        ("apply", "board", ["F_Cu", "dielectric_1", "B_Cu"]),
        ("transaction", "board::updated"),
        "reload",
    ]


def test_set_stackup_rejects_profiles_without_two_copper_layers() -> None:
    service = PcbStackupManagementService(
        current_stackup_specs=_layers,
        total_stackup_thickness_mm=_total,
        configured_board_file=lambda: None,
        board_file_diagnostics=_no_diagnostics,
        is_copper_stackup_layer=lambda layer: layer.material.casefold() == "copper",
        write_stackup_state=lambda _layers: Path("stackup.json"),
        transactional_board_write=lambda mutator: mutator("board"),
        apply_stackup_to_board=lambda current, _layers: current,
        reload_board_after_file_sync=lambda: "reloaded",
    )
    invalid = [
        StackupLayerSpec(
            name="dielectric_1",
            type="core",
            thickness_mm=0.8,
            material="FR4",
        ).model_dump(),
        StackupLayerSpec(
            name="dielectric_2",
            type="core",
            thickness_mm=0.8,
            material="FR4",
        ).model_dump(),
    ]

    with pytest.raises(ValueError, match="at least two copper layers"):
        service.set_stackup(invalid)
