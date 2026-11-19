from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.errors import ManualStepRequiredError
from kicad_mcp.routing.autorouter import RoutingAutorouterService
from kicad_mcp.utils.freerouting import FreeRoutingResult

PCB = '(kicad_pcb\n\t(version 20250216)\n\t(net 0 "")\n\t(net 1 "GND")\n)\n'
SES = (
    "(session t.dsn (routes (resolution um 10) (network_out "
    '(net "GND" (wire (path F.Cu 250 2500 -5000 11000 -5000)) '
    '(via "Via[0-1]_600:300_um" 11000 -5000)))))'
)


class FakeRunner:
    def __init__(
        self,
        dsn: Path,
        result: FreeRoutingResult | Exception,
        *,
        staged: Path | Exception | None = None,
    ) -> None:
        self.dsn = dsn
        self.result = result
        self.staged = staged
        self.export_calls: list[tuple[Path, Path]] = []
        self.run_calls: list[dict[str, object]] = []
        self.stage_calls: list[Path] = []

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path:
        self.export_calls.append((pcb_path, dsn_path))
        if isinstance(self.result, ManualStepRequiredError):
            raise self.result
        return self.dsn

    def run_freerouting(
        self,
        dsn_path: Path,
        ses_path: Path,
        **kwargs: object,
    ) -> FreeRoutingResult:
        self.run_calls.append({"dsn_path": dsn_path, "ses_path": ses_path, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def stage_ses(self, ses_path: Path) -> Path:
        self.stage_calls.append(ses_path)
        if isinstance(self.staged, Exception):
            raise self.staged
        return self.staged if isinstance(self.staged, Path) else ses_path


def _result(
    dsn: Path, ses: Path, *, returncode: int = 0, excluded_nets: tuple[str, ...] = ()
) -> FreeRoutingResult:
    return FreeRoutingResult(
        mode="docker",
        command=("docker", "run", "freerouting"),
        input_dsn=dsn,
        output_ses=ses,
        returncode=returncode,
        stdout="pass 4\n100% routed\nok",
        stderr="boom" if returncode else "",
        routed_pct=100.0,
        total_nets=1,
        unrouted_nets=[],
        pass_count=4,
        wall_seconds=1.25,
        stdout_tail="100% routed\nok",
        ses_path=ses,
        excluded_nets=excluded_nets,
    )


def _service(
    tmp_path: Path,
    runner: FakeRunner,
    *,
    current: str = PCB,
) -> tuple[RoutingAutorouterService, list[str]]:
    writes: list[str] = []

    def transaction(mutator):
        updated = mutator(current)
        writes.append(updated)
        return str(tmp_path / "demo.kicad_pcb")

    return (
        RoutingAutorouterService(
            runner_factory=lambda: runner,
            get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
            resolve_within_project=lambda path: tmp_path / Path(path),
            relative_project_path=lambda path: str(path.relative_to(tmp_path)),
            transactional_board_write=transaction,
        ),
        writes,
    )


@pytest.mark.anyio
async def test_autoroute_preserves_headless_apply_success_and_progress(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    ses = tmp_path / "output" / "routing" / "board.ses"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("(pcb)", encoding="utf-8")
    ses.write_text(SES, encoding="utf-8")
    runner = FakeRunner(dsn, _result(dsn, ses, excluded_nets=("NO_ROUTE",)))
    service, writes = _service(tmp_path, runner)
    progress: list[tuple[float, float, str]] = []

    async def report(value: float, total: float, message: str) -> None:
        progress.append((value, total, message))

    result = await service.autoroute(
        net_classes_to_ignore=["GND"],
        exclude_nets=["NO_ROUTE"],
        thread_count=8,
        report_progress=report,
    )

    assert result.ok is True
    assert result.changed is True
    assert result.human_gate_required is False
    assert writes
    assert [artifact.kind for artifact in result.artifacts] == ["dsn", "ses", "pcb"]
    assert "FreeRouting routed and applied: 1 segment(s), 1 via(s), 1 net(s)." in (
        result.state_delta.summary
    )
    assert "Ignored net classes: GND\n" in result.state_delta.summary
    assert "Excluded nets: NO_ROUTE" in result.state_delta.summary
    assert "Thread count: 8" in result.state_delta.summary
    assert progress == [
        (10, 100, "Exporting DSN for FreeRouting..."),
        (40, 100, "Running FreeRouting..."),
        (85, 100, "Applying SES to board headlessly..."),
        (100, 100, "FreeRouting routing complete."),
    ]


@pytest.mark.anyio
async def test_autoroute_preserves_gui_fallback_when_headless_apply_fails(
    tmp_path: Path,
) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    ses = tmp_path / "output" / "routing" / "board.ses"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("(pcb)", encoding="utf-8")
    ses.write_text("ses", encoding="utf-8")
    runner = FakeRunner(dsn, _result(dsn, ses), staged=ses)
    service, writes = _service(tmp_path, runner)

    result = await service.autoroute()

    assert result.ok is True
    assert result.changed is False
    assert result.human_gate_required is True
    assert writes == []
    assert runner.stage_calls == [ses]
    assert "headless apply failed" in result.state_delta.summary
    assert "File > Import > Specctra Session" in result.state_delta.summary


@pytest.mark.anyio
async def test_autoroute_preserves_manual_export_gate(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    runner = FakeRunner(dsn, ManualStepRequiredError("manual export required"))
    service, _ = _service(tmp_path, runner)

    result = await service.autoroute()

    assert result.ok is False
    assert result.human_gate_required is True
    assert result.errors == ["manual export required"]


@pytest.mark.anyio
async def test_autoroute_preserves_nonzero_runner_failure(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    ses = tmp_path / "output" / "routing" / "board.ses"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("(pcb)", encoding="utf-8")
    runner = FakeRunner(dsn, _result(dsn, ses, returncode=2))
    service, _ = _service(tmp_path, runner)

    result = await service.autoroute()

    assert result.ok is False
    assert result.errors == [
        "FreeRouting autoroute failed.\nMode: docker\nCommand: docker run freerouting\nstderr: boom"
    ]


@pytest.mark.anyio
async def test_autoroute_preserves_missing_ses_failure(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    ses = tmp_path / "output" / "routing" / "board.ses"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("(pcb)", encoding="utf-8")
    runner = FakeRunner(dsn, _result(dsn, ses))
    service, _ = _service(tmp_path, runner)

    result = await service.autoroute()

    assert result.ok is False
    assert "SES session file is missing or empty" in result.errors[0]


@pytest.mark.anyio
async def test_autoroute_preserves_staging_failure(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    ses = tmp_path / "output" / "routing" / "board.ses"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("(pcb)", encoding="utf-8")
    ses.write_text("ses", encoding="utf-8")
    runner = FakeRunner(
        dsn,
        _result(dsn, ses),
        staged=FileNotFoundError("missing staged SES"),
    )
    service, _ = _service(tmp_path, runner)

    result = await service.autoroute()

    assert result.ok is False
    assert result.errors == [
        "FreeRouting autoroute failed while staging the SES file: missing staged SES"
    ]


@pytest.mark.anyio
async def test_path_resolution_error_timing_is_preserved(tmp_path: Path) -> None:
    dsn = tmp_path / "output" / "routing" / "board.dsn"
    runner = FakeRunner(dsn, RuntimeError("unused"))
    service = RoutingAutorouterService(
        runner_factory=lambda: runner,
        get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
        resolve_within_project=lambda _path: (_ for _ in ()).throw(ValueError("outside")),
        relative_project_path=str,
        transactional_board_write=lambda mutator: str(tmp_path / "demo.kicad_pcb"),
    )

    with pytest.raises(ValueError, match="outside"):
        await service.autoroute()
