"""Production accessor for the canonical native-live PCB mutation service."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Final

from kipy.board import Board

from ..connection import KiCadConnectionError, get_board, get_connection_epoch
from ..ipc.command_queue import get_command_queue
from .transaction_lifecycle import PcbTransactionLifecycleService, PostconditionVerifier

REVIEWED_LIVE_MUTATIONS: Final[dict[str, bool]] = {
    "pcb_add_track": True,
    "pcb_add_tracks_bulk": False,
    "pcb_add_via": True,
    "pcb_add_blind_via": False,
    "pcb_add_microvia": False,
    "pcb_add_segment": False,
    "pcb_add_circle": False,
    "pcb_add_rectangle": False,
    "pcb_set_board_outline": False,
    "pcb_add_text": False,
    "pcb_delete_items": True,
    "pcb_save": False,
    "pcb_refill_zones": False,
    "pcb_move_footprint": True,
    "pcb_set_footprint_layer": True,
    "pcb_add_zone": False,
    "pcb_set_keepout_zone": False,
    "pcb_add_teardrops": False,
    "route_single_track": False,
    "route_from_pad_to_pad": False,
    "pdn_generate_power_plane": False,
    "pcb_set_origin": False,
    "pcb_set_title_block_info": False,
}

_SERVICE_LOCK = threading.Lock()
_SERVICE: PcbTransactionLifecycleService | None = None


def _run_mutation[T](operation: str, command: Callable[[], T]) -> T:
    """Execute one IPC mutation exactly once through the process-wide queue."""
    return get_command_queue().execute_mutation(
        operation,
        command,
        correlation_id=operation,
    )


def get_live_edit_service() -> PcbTransactionLifecycleService:
    """Return the process-wide board-bound native-live service."""
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = PcbTransactionLifecycleService(
                    get_board=get_board,
                    run_mutation=_run_mutation,
                    connection_errors=(KiCadConnectionError, OSError),
                    get_connection_epoch=get_connection_epoch,
                )
    return _SERVICE


def reset_live_edit_service() -> None:
    """Reset native-live session state after project/session changes and in tests."""
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None


def execute_live_board_mutation[T](
    operation: str,
    command: Callable[[Board], T],
    *,
    verifier: PostconditionVerifier[T] | None,
) -> T:
    """Execute one reviewed board mutation through the canonical service."""
    return get_live_edit_service().execute_board_mutation(
        operation,
        command,
        verifier=verifier,
        participates_in_live_session=REVIEWED_LIVE_MUTATIONS.get(operation, False),
    )


__all__ = [
    "REVIEWED_LIVE_MUTATIONS",
    "execute_live_board_mutation",
    "get_live_edit_service",
    "reset_live_edit_service",
]
