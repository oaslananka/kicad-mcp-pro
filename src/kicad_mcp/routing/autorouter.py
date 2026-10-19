"""FastMCP-independent FreeRouting autorouter orchestration service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anyio

from ..errors import ManualStepRequiredError
from ..models.tool_result import ArtifactRef, StateDelta, ToolResult
from ..utils.freerouting import FreeRoutingResult
from ..utils.router_core import SesRoute, apply_ses_to_pcb


class AutorouteRunner(Protocol):
    """Minimal FreeRouting runner surface needed by the autorouter service."""

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path: ...

    def run_freerouting(
        self,
        dsn_path: Path,
        ses_path: Path,
        *,
        max_passes: int,
        thread_count: int,
        use_docker: bool,
        freerouting_jar_path: Path | None,
        net_classes_to_ignore: list[str] | None,
        exclude_nets: list[str] | None,
        drc_report_path: Path | None,
    ) -> FreeRoutingResult: ...

    def stage_ses(self, ses_path: Path) -> Path: ...


RunnerFactory = Callable[[], AutorouteRunner]
PcbFileProvider = Callable[[], Path]
ProjectPathResolver = Callable[[str | Path], Path]
RelativePathFormatter = Callable[[Path], str]
BoardMutator = Callable[[str], str]
TransactionalBoardWriter = Callable[[BoardMutator], str]
ProgressReporter = Callable[[float, float, str], Awaitable[None]]


class _NoRouteError(ValueError):
    pass


class _AlreadyAppliedError(ValueError):
    pass


async def _execute_freerouting_phase(
    runner: AutorouteRunner,
    pcb_file: Path,
    dsn_target: Path,
    ses_target: Path,
    drc_target: Path | None,
    progress: Callable[[float, float, str], Awaitable[None]],
    *,
    max_passes: int,
    thread_count: int,
    use_docker: bool,
    freerouting_jar_path: str | None,
    net_classes_to_ignore: list[str] | None,
    exclude_nets: list[str] | None,
) -> tuple[Path, FreeRoutingResult] | ToolResult:
    try:
        await progress(10, 100, "Exporting DSN for FreeRouting...")
        dsn_file = await anyio.to_thread.run_sync(lambda: runner.export_dsn(pcb_file, dsn_target))
        await progress(40, 100, "Running FreeRouting...")
        result = await anyio.to_thread.run_sync(
            lambda: runner.run_freerouting(
                dsn_file,
                ses_target,
                max_passes=max_passes,
                thread_count=thread_count,
                use_docker=use_docker,
                freerouting_jar_path=Path(freerouting_jar_path).expanduser()
                if freerouting_jar_path
                else None,
                net_classes_to_ignore=net_classes_to_ignore,
                exclude_nets=exclude_nets,
                drc_report_path=drc_target,
            )
        )
        return dsn_file, result
    except ManualStepRequiredError as exc:
        manual = ToolResult.failure("route_autoroute_freerouting", str(exc))
        manual.human_gate_required = True
        return manual
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return ToolResult.failure(
            "route_autoroute_freerouting",
            f"FreeRouting autoroute failed: {exc}",
        )


def _validate_ses_output(
    result: FreeRoutingResult,
    dsn_file: Path,
    relative_project_path: RelativePathFormatter,
) -> tuple[Path | None, str | None]:
    if result.returncode != 0:
        return None, (
            "FreeRouting autoroute failed.\n"
            f"Mode: {result.mode}\n"
            f"Command: {' '.join(result.command)}\n"
            f"stderr: {result.stderr or 'unknown error'}"
        )
    ses_output = result.output_ses
    ses_path_obj = Path(ses_output) if ses_output else None
    if ses_path_obj is None:
        return None, "FreeRouting autoroute failed: no SES output path was reported."
    if not (ses_path_obj.exists() and ses_path_obj.stat().st_size > 0):
        return None, (
            "FreeRouting ran but the SES session file is missing or empty \u2014 "
            "this is a known KiCad 10 / Specctra round-trip failure.\n"
            "Workaround: open the PCB in KiCad GUI and import the DSN manually "
            "via File > Import > Specctra Session "
            f"({relative_project_path(dsn_file)}).\n"
            f"SES path checked: {ses_path_obj}"
        )
    return ses_path_obj, None


async def _apply_ses_headless(
    ses_path_obj: Path,
    transactional_board_write: TransactionalBoardWriter,
) -> tuple[Path | None, SesRoute | None, str | None]:
    applied_route: SesRoute | None = None
    try:
        ses_text = ses_path_obj.read_text(encoding="utf-8", errors="ignore")

        def apply_ses(current: str) -> str:
            nonlocal applied_route
            updated, applied_route = apply_ses_to_pcb(current, ses_text)
            if not applied_route.segments and not applied_route.vias:
                raise _NoRouteError
            if updated == current:
                raise _AlreadyAppliedError
            return updated

        applied_pcb_file = Path(
            await anyio.to_thread.run_sync(lambda: transactional_board_write(apply_ses))
        )
        return applied_pcb_file, applied_route, None
    except (ValueError, OSError) as exc:
        return None, None, str(exc)
    except Exception as exc:  # noqa: BLE001
        return None, None, f"Unexpected error during headless SES apply: {exc}"


def _build_autoroute_success(
    dsn_file: Path,
    ses_path_obj: Path,
    applied_pcb_file: Path,
    applied_route: SesRoute,
    route_stats: FreeRoutingResult,
    relative_path: RelativePathFormatter,
    ignore_text: str,
    thread_count: int,
) -> ToolResult:
    seg_count = len(applied_route.segments)
    via_count = len(applied_route.vias)
    net_count = len(applied_route.net_names)
    return ToolResult.success(
        "route_autoroute_freerouting",
        changed=True,
        artifacts=[
            ArtifactRef(path=str(dsn_file), kind="dsn"),
            ArtifactRef(path=str(ses_path_obj), kind="ses"),
            ArtifactRef(path=str(applied_pcb_file), kind="pcb"),
        ],
        state_delta=StateDelta(
            summary=(
                f"FreeRouting routed and applied: {seg_count} segment(s), "
                f"{via_count} via(s), {net_count} net(s).\n"
                f"Mode: {route_stats.mode}\n"
                f"DSN: {relative_path(dsn_file)}\n"
                f"SES: {relative_path(ses_path_obj)}\n"
                f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                f"Pass count: {route_stats.pass_count}\n"
                f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                f"Ignored net classes: {ignore_text}\n"
                f"Thread count: {thread_count}\n"
                "Next step: run run_drc() to verify the routed board, "
                "then pcb_fill_all_zones() to fill copper pours.\n"
                f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
            ),
            changed_files=[str(applied_pcb_file)],
        ),
    )


def _build_autoroute_fallback(
    dsn_file: Path,
    staged: Path,
    apply_error: str | None,
    route_stats: FreeRoutingResult,
    relative_path: RelativePathFormatter,
    ignore_text: str,
    thread_count: int,
) -> ToolResult:
    fallback = ToolResult.success(
        "route_autoroute_freerouting",
        changed=False,
        artifacts=[
            ArtifactRef(path=str(dsn_file), kind="dsn"),
            ArtifactRef(path=str(staged), kind="ses"),
        ],
        state_delta=StateDelta(
            summary=(
                "FreeRouting produced a routed session; headless apply failed, "
                "use File > Import > Specctra Session in KiCad GUI to finish.\n"
                f"Headless apply error: {apply_error or 'unknown'}\n"
                f"Mode: {route_stats.mode}\n"
                f"DSN: {relative_path(dsn_file)}\n"
                f"SES: {relative_path(staged)}\n"
                f"Routed: {route_stats.routed_pct:.2f}% ({route_stats.total_nets} "
                f"net(s), {len(route_stats.unrouted_nets)} unrouted)\n"
                f"Pass count: {route_stats.pass_count}\n"
                f"Wall time: {route_stats.wall_seconds:.3f}s\n"
                f"Ignored net classes: {ignore_text}\n"
                f"Thread count: {thread_count}\n"
                "Manual step: open the PCB in KiCad and run "
                "File > Import > Specctra Session, then save the board.\n"
                f"stdout tail: {route_stats.stdout_tail or '(empty)'}"
            ),
            changed_files=[str(dsn_file), str(staged)],
        ),
    )
    fallback.human_gate_required = True
    return fallback


@dataclass(frozen=True)
class RoutingAutorouterService:
    """Run FreeRouting and apply or stage its routed SES result."""

    runner_factory: RunnerFactory
    get_pcb_file: PcbFileProvider
    resolve_within_project: ProjectPathResolver
    relative_project_path: RelativePathFormatter
    transactional_board_write: TransactionalBoardWriter

    async def autoroute(
        self,
        dsn_path: str = "output/routing/board.dsn",
        ses_path: str = "output/routing/board.ses",
        net_classes_to_ignore: list[str] | None = None,
        exclude_nets: list[str] | None = None,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: str | None = None,
        drc_report_path: str = "output/routing/freerouting.drc.json",
        report_progress: ProgressReporter | None = None,
    ) -> ToolResult:
        runner = self.runner_factory()
        pcb_file = self.get_pcb_file()
        dsn_target = self.resolve_within_project(Path(dsn_path))
        ses_target = self.resolve_within_project(Path(ses_path))
        drc_target = self.resolve_within_project(Path(drc_report_path)) if drc_report_path else None

        async def progress(value: float, total: float, message: str) -> None:
            if report_progress is not None:
                await report_progress(value, total, message)

        phase_result = await _execute_freerouting_phase(
            runner,
            pcb_file,
            dsn_target,
            ses_target,
            drc_target,
            progress,
            max_passes=max_passes,
            thread_count=thread_count,
            use_docker=use_docker,
            freerouting_jar_path=freerouting_jar_path,
            net_classes_to_ignore=net_classes_to_ignore,
            exclude_nets=exclude_nets,
        )
        if isinstance(phase_result, ToolResult):
            return phase_result

        dsn_file, result = phase_result
        ses_path_obj, ses_err = _validate_ses_output(result, dsn_file, self.relative_project_path)
        if ses_path_obj is None or ses_err is not None:
            return ToolResult.failure("route_autoroute_freerouting", ses_err or "Unknown error")

        ignore_text = ", ".join([*(net_classes_to_ignore or []), *(exclude_nets or [])]) or "none"
        await progress(85, 100, "Applying SES to board headlessly...")
        applied_pcb, applied_route, apply_error = await _apply_ses_headless(
            ses_path_obj, self.transactional_board_write
        )
        await progress(100, 100, "FreeRouting routing complete.")

        if apply_error is None and applied_pcb is not None and applied_route is not None:
            return _build_autoroute_success(
                dsn_file,
                ses_path_obj,
                applied_pcb,
                applied_route,
                result,
                self.relative_project_path,
                ignore_text,
                thread_count,
            )

        try:
            staged = await anyio.to_thread.run_sync(lambda: runner.stage_ses(ses_path_obj))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return ToolResult.failure(
                "route_autoroute_freerouting",
                f"FreeRouting autoroute failed while staging the SES file: {exc}",
            )

        return _build_autoroute_fallback(
            dsn_file,
            staged,
            apply_error,
            result,
            self.relative_project_path,
            ignore_text,
            thread_count,
        )
