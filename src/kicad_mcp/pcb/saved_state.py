"""Opt-in saved PCB graph integration at the existing serialized save boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import structlog

from .. import __version__
from ..config import KiCadMCPConfig
from ..ir.engineering_graph import GraphEntityKind
from ..project import incremental_state as state_api
from ..utils.units import _coord_nm, mm_to_nm
from .board_access import board_footprints
from .footprint_index import FileFootprintIndex, FootprintListRecord

if TYPE_CHECKING:
    from kipy.board import Board

logger = structlog.get_logger(__name__)
_CACHE_NAME = ".kicad-mcp-cache/physical.json"


@dataclass(frozen=True, slots=True)
class SavedPcbScope:
    root: Path
    board_name: str
    schematic_name: str
    project_file: Path
    epoch: object


def _local_scope(config: KiCadMCPConfig, board: Board, epoch: object) -> SavedPcbScope | None:
    if not config.enable_persistent_pcb_state:
        return None
    if (
        config.transport != "stdio"
        or config.headless
        or config.operating_mode not in {"write", "experimental"}
        or config.project_dir is None
        or config.project_file is None
        or config.pcb_file is None
        or config.sch_file is None
    ):
        raise ValueError("saved PCB graph requires an explicit local write project")
    endpoint = str(config.kicad_socket_path or "")
    if "://" in endpoint and not endpoint.startswith("ipc://"):
        raise ValueError("saved PCB graph requires local IPC")
    root = config.project_dir.resolve(strict=True)
    project = config.project_file.resolve(strict=True)
    pcb = config.pcb_file.resolve(strict=True)
    schematic = config.sch_file.resolve(strict=True)
    if not root.is_relative_to(config.workspace) or any(
        not path.is_relative_to(root) for path in (project, pcb, schematic)
    ):
        raise ValueError("saved PCB graph scope escapes the configured project")
    if (
        project.suffix != ".kicad_pro"
        or pcb.suffix != ".kicad_pcb"
        or schematic.suffix != ".kicad_sch"
    ):
        raise ValueError("invalid configured native source")
    # The IPC ProjectSpecifier path may be the project file or its directory.
    live_project = board.get_project()
    live_path = Path(live_project.path)
    if (
        not live_path.is_absolute()
        or live_path.resolve() not in {project, project.parent}
        or live_project.name != project.stem
        or board.name != pcb.name
        or pcb.parent != project.parent
    ):
        raise ValueError("live board and configured project do not match")
    return SavedPcbScope(
        root,
        pcb.relative_to(root).as_posix(),
        schematic.relative_to(root).as_posix(),
        project,
        epoch,
    )


def _sources(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.suffix in state_api.SUPPORTED_SOURCES
        )
    )


def _live_placement_matches(board: Board, row: FootprintListRecord) -> bool:
    matches = [
        item
        for item in board_footprints(board)
        if str(getattr(getattr(item, "id", None), "value", "")).lower() == row.native_uuid
    ]
    if len(matches) != 1:
        return False
    position = getattr(matches[0], "position", None)
    return _coord_nm(position, "x") == mm_to_nm(row.x_mm) and _coord_nm(position, "y") == mm_to_nm(
        row.y_mm
    )


class SavedPcbStateService:
    """Own one opt-in project snapshot per registered PCB tool surface.

    No background writes, no implicit native save, no live-state authority.
    Invoked only inside the existing serialized pcb_save mutation.
    """

    def __init__(self, index: FileFootprintIndex) -> None:
        self.index = index
        self.scope: SavedPcbScope | None = None
        self.state: state_api.PersistentProjectState | None = None

    def clear(self) -> None:
        self.state = None
        self.scope = None
        self.index.clear()

    def _prepare(
        self,
        config: KiCadMCPConfig,
        board: Board,
        epoch: object,
    ) -> tuple[SavedPcbScope | None, state_api.EditToken | None]:
        scope = _local_scope(config, board, epoch)
        if scope != self.scope:
            self.clear()
        if scope is None:
            return None, None
        token = None
        if self.state is not None:
            try:
                token = self.state.prepare_native_edit()
            except state_api.StateRebuildRequiredError:
                self.clear()
        return scope, token

    def _compatibility(self, run_cli: Callable[..., tuple[int, str, str]]) -> str:
        code, version, _ = run_cli("version", timeout=15)
        version = version.strip()
        if code != 0 or not version.startswith("10.") or len(version) > 100:
            raise ValueError("unsupported native CLI version")
        return f"{__version__}:{version}:native-xml-E:physical-graph-v2"

    def _try_delta(
        self,
        token: state_api.EditToken | None,
        after: state_api.NativePcbSnapshot,
        board: Board,
        compatibility: str,
    ) -> str | None:
        current = self.state
        if token is None or current is None or current.compatibility_key != compatibility:
            return None
        if dict(after.source_hashes) == current.source_hashes:
            current.verify_sources()
            return "unchanged"
        old = {
            entity.stable_key: entity.attributes["block_sha256"]
            for entity in current.graph.entities_of_kind(GraphEntityKind.PCB_FOOTPRINT)
        }
        changed = [
            row
            for row in after.records
            if old.get(f"{after.board_name}:{row.native_uuid}") != row.block_sha256
        ]
        if len(changed) != 1:
            return None
        row = changed[0]
        if not _live_placement_matches(board, row):
            raise ValueError("saved and live footprint placement differ")
        try:
            entry = current.apply_pcb_placement(
                token, after, native_uuid=row.native_uuid, x_mm=row.x_mm, y_mm=row.y_mm
            )
        except state_api.StateRebuildRequiredError:
            return None
        return f"{entry.work_units} updated"

    def _rebuild(
        self,
        scope: SavedPcbScope,
        after: state_api.NativePcbSnapshot,
        compatibility: str,
        run_cli: Callable[..., tuple[int, str, str]],
    ) -> str:
        sources = tuple(dict(after.source_hashes))
        hierarchy = state_api.capture_native_hierarchy(
            scope.root, scope.schematic_name, sources, run_cli=run_cli
        )
        if hierarchy.circuit.source_uuid is None:
            raise ValueError("native hierarchy has no identity")
        path = scope.root / _CACHE_NAME
        try:
            self.state = state_api.PersistentProjectState.load_verified(
                scope.root,
                path,
                project_key=hierarchy.circuit.source_uuid,
                native_sources=sources,
                compatibility_key=compatibility,
                native_snapshot=hierarchy,
                pcb_snapshot=after,
            )
            return "reopened"
        except state_api.StateRebuildRequiredError:
            self.state = state_api.PersistentProjectState.rebuild_native(
                hierarchy,
                compatibility_key=compatibility,
                pcb_snapshot=after,
            )
            return "rebuilt"

    def save(
        self,
        board: Board,
        *,
        get_config: Callable[[], KiCadMCPConfig],
        get_board: Callable[[], Board],
        get_epoch: Callable[[], object],
        run_cli: Callable[..., tuple[int, str, str]],
    ) -> str:
        config = get_config()
        if not config.enable_persistent_pcb_state:
            if self.scope is not None:
                self.clear()
            cast(Callable[[], None], board.save)()
            return "Board saved."
        scope, token = None, None
        try:
            scope, token = self._prepare(config, board, get_epoch())
        except Exception as exc:  # noqa: BLE001 - optional cache cannot prevent native save
            self.clear()
            logger.debug("saved_pcb_state_prepare_unavailable", error=type(exc).__name__)
        try:
            cast(Callable[[], None], board.save)()
        except BaseException:
            self.clear()
            raise
        if scope is None:
            return "Board saved. Saved PCB graph unavailable; no cache update."
        try:
            fresh = get_board()
            if _local_scope(get_config(), fresh, get_epoch()) != scope:
                raise ValueError("project or connection changed during save")
            compatibility = self._compatibility(run_cli)
            after = state_api.capture_native_pcb(
                scope.root, scope.board_name, _sources(scope.root), index=self.index
            )
            status = self._try_delta(token, after, fresh, compatibility)
            if status is None:
                status = self._rebuild(scope, after, compatibility, run_cli)
            if _local_scope(get_config(), get_board(), get_epoch()) != scope:
                raise ValueError("project or connection changed during graph update")
            if self.state is None:
                raise ValueError("saved PCB graph was not constructed")
            self.state.save_atomic(scope.root / _CACHE_NAME)
            self.scope = scope
            return f"Board saved. Saved PCB graph: {status}."
        except Exception as exc:  # noqa: BLE001 - native save already completed; never replay it
            self.clear()
            logger.debug("saved_pcb_state_update_unavailable", error=type(exc).__name__)
            return "Board saved. Saved PCB graph unavailable; rebuild required."
