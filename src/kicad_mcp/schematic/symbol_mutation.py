"""Pure orchestration for non-destructive schematic symbol mutations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

type SymbolMatch = tuple[str, int, int, Mapping[str, Any]]
type UpdateSymbolProperty = Callable[[str, str, str], str]
type SetSymbolDnp = Callable[[str, bool, str | None], str]
type ReloadSchematic = Callable[[], str]
type SnapPoint = Callable[[float, float, bool], tuple[float, float]]
type SnapNotice = Callable[[tuple[float, ...], tuple[float, ...]], str]
type FindPlacedSymbolBlock = Callable[[str, str], SymbolMatch | None]


class TransactionalWrite(Protocol):
    """Transaction boundary used by symbol move orchestration."""

    def __call__(
        self,
        mutator: Callable[[str], str],
        *,
        allow_node_loss: bool = False,
    ) -> str: ...


class ShiftSymbolBlock(Protocol):
    """Callable contract for moving one placed-symbol block."""

    def __call__(
        self,
        block: str,
        *,
        dx_mm: float,
        dy_mm: float,
    ) -> str: ...


@dataclass(frozen=True)
class SchematicSymbolMutationService:
    """Compose symbol property and placement mutations from injected operations."""

    update_symbol_property: UpdateSymbolProperty
    set_symbol_dnp: SetSymbolDnp
    reload_schematic: ReloadSchematic
    snap_point: SnapPoint
    snap_notice: SnapNotice
    transactional_write: TransactionalWrite
    find_placed_symbol_block: FindPlacedSymbolBlock
    shift_symbol_block: ShiftSymbolBlock

    def update_properties(self, reference: str, field: str, value: str) -> str:
        """Update one symbol property and reload the schematic."""
        result = self.update_symbol_property(reference, field, value)
        return f"{result}\n{self.reload_schematic()}"

    def set_dnp(self, reference: str, enabled: bool, reason: str | None) -> str:
        """Update native DNP state and reload the schematic."""
        result = self.set_symbol_dnp(reference, enabled, reason)
        return f"{result}\n{self.reload_schematic()}"

    def move_symbol(
        self,
        reference: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool,
    ) -> str:
        """Move one placed symbol while preserving transaction and result behavior."""
        target_x, target_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (target_x, target_y))

        def mutator(current: str) -> str:
            match = self.find_placed_symbol_block(current, reference)
            if match is None:
                raise ValueError(f"Reference '{reference}' was not found in the schematic.")
            block, start, end, parsed = match
            shifted = self.shift_symbol_block(
                block,
                dx_mm=target_x - float(parsed["x"]),
                dy_mm=target_y - float(parsed["y"]),
            )
            return current[:start] + shifted + current[end:]

        try:
            self.transactional_write(mutator)
        except ValueError as exc:
            return str(exc)

        result = self.reload_schematic()
        lines = [
            result,
            f"Moved symbol '{reference}' to ({target_x:.2f}, {target_y:.2f}) mm.",
        ]
        if snap_note:
            lines.append(snap_note)
        return "\n".join(lines)
