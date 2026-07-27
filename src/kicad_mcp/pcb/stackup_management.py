"""FastMCP-free PCB stackup inspection and file-backed programming."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models.pcb import SetStackupInput, StackupLayerSpec


class BoardFileDiagnostics(Protocol):
    """Render the established board-file diagnostic lines."""

    def __call__(
        self,
        *,
        board_file: Path | None,
        status: str,
    ) -> list[str]: ...


class TransactionalBoardWrite(Protocol):
    """Apply one validated board-text mutation transactionally."""

    def __call__(self, mutator: Callable[[str], str]) -> str: ...


type CurrentStackupSpecs = Callable[[], list[StackupLayerSpec]]
type TotalStackupThickness = Callable[[list[StackupLayerSpec]], float]
type ConfiguredBoardFile = Callable[[], Path | None]
type IsCopperStackupLayer = Callable[[StackupLayerSpec], bool]
type WriteStackupState = Callable[[list[StackupLayerSpec]], Path]
type ApplyStackupToBoard = Callable[[str, list[StackupLayerSpec]], str]
type ReloadBoardAfterFileSync = Callable[[], str]


@dataclass(frozen=True)
class PcbStackupManagementService:
    """Inspect and program PCB stackups independently of FastMCP registration."""

    current_stackup_specs: CurrentStackupSpecs
    total_stackup_thickness_mm: TotalStackupThickness
    configured_board_file: ConfiguredBoardFile
    board_file_diagnostics: BoardFileDiagnostics
    is_copper_stackup_layer: IsCopperStackupLayer
    write_stackup_state: WriteStackupState
    transactional_board_write: TransactionalBoardWrite
    apply_stackup_to_board: ApplyStackupToBoard
    reload_board_after_file_sync: ReloadBoardAfterFileSync

    def get_stackup(self) -> str:
        """Render the current stackup or the existing unavailable diagnostics."""
        try:
            layers = self.current_stackup_specs()
        except ValueError as exc:
            return "\n".join(
                [
                    str(exc),
                    *self.board_file_diagnostics(
                        board_file=self.configured_board_file(),
                        status="stackup data unavailable in active board context",
                    ),
                ]
            )

        lines = [f"Board stackup ({len(layers)} layers):"]
        for index, layer in enumerate(layers, start=1):
            extras: list[str] = []
            if layer.epsilon_r is not None:
                extras.append(f"Er={layer.epsilon_r:.3f}")
            if layer.loss_tangent is not None:
                extras.append(f"loss={layer.loss_tangent:.4f}")
            suffix = f" | {' | '.join(extras)}" if extras else ""
            lines.append(
                f"- {index}. {layer.name} | type={layer.type} | "
                f"thickness={layer.thickness_mm:.4f} mm | material={layer.material}{suffix}"
            )
        lines.append(f"- Total thickness: {self.total_stackup_thickness_mm(layers):.4f} mm")
        return "\n".join(lines)

    def set_stackup(self, layers: list[dict[str, object]]) -> str:
        """Validate and persist a file-backed stackup profile transactionally."""
        payload = SetStackupInput.model_validate({"layers": layers})
        copper_count = sum(1 for layer in payload.layers if self.is_copper_stackup_layer(layer))
        if copper_count < 2:
            raise ValueError("A valid stackup needs at least two copper layers.")

        state_path = self.write_stackup_state(payload.layers)
        self.transactional_board_write(
            lambda current: self.apply_stackup_to_board(current, payload.layers)
        )
        reload_message = self.reload_board_after_file_sync()
        return "\n".join(
            [
                f"Configured stackup with {len(payload.layers)} layers.",
                f"- Copper layers: {copper_count}",
                (f"- Total thickness: {self.total_stackup_thickness_mm(payload.layers):.4f} mm"),
                f"- Saved stackup state: {state_path}",
                f"- {reload_message}",
            ]
        )
