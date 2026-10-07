#!/usr/bin/env python3
"""Write separate KiCad 11 headless read, write, and export canary reports."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from kicad_mcp.evals.roundtrip_differential import RoundTripSnapshot
    from kicad_mcp.evals.semantic_differential import DifferentialResult

try:
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from runtime_path_safety import approved_runtime_path

REPO_ROOT = Path(__file__).resolve().parents[1]
SURFACES = ("read", "write", "export")
_KICAD_CLI_NAMES = frozenset(
    {"kicad-cli", "kicad-cli.exe", "kicad-nightly-cli", "kicad-nightly-cli.exe"}
)
_KICAD_INPUT_SUFFIXES = frozenset({".kicad_pro", ".kicad_pcb", ".kicad_sch"})


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    surface: str
    status: str
    kicad_version: str | None
    reason: str
    evidence: list[str]
    backend: str


@dataclass(frozen=True, slots=True)
class LiveIdentityProbe:
    native_project_path: str
    native_board_name: str
    custom_board_name: str
    custom_fingerprint: str


@dataclass(frozen=True, slots=True)
class RoundTripProbe:
    native_snapshot: RoundTripSnapshot
    custom_snapshot: RoundTripSnapshot


def _validated_kicad_cli(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"KiCad CLI executable does not exist: {path}") from exc
    if resolved.name.casefold() not in _KICAD_CLI_NAMES or not resolved.is_file():
        raise ValueError(f"KiCad CLI executable is not an approved kicad-cli binary: {path}")
    if not os.access(resolved, os.X_OK):
        raise ValueError(f"KiCad CLI executable is not executable: {path}")
    return resolved


def _validated_project_or_file(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"KiCad project or design file does not exist: {path}") from exc
    if not resolved.is_file() or resolved.suffix.casefold() not in _KICAD_INPUT_SUFFIXES:
        raise ValueError(f"KiCad project or design file has an unsupported path: {path}")
    return resolved


def _report_payload(report: SurfaceReport) -> dict[str, object]:
    payload = asdict(report)
    payload["kicadVersion"] = payload.pop("kicad_version")
    return payload


def _write_report(artifacts: Path, report: SurfaceReport) -> None:
    target = artifacts / report.surface
    target.mkdir(parents=True, exist_ok=True)
    (target / "summary.json").write_text(
        json.dumps(_report_payload(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _version(cli: Path) -> tuple[str | None, list[str]]:
    result = _run([str(cli), "version"])
    evidence = [f"kicad-cli version exit={result.returncode}"]
    if result.returncode != 0:
        return None, [*evidence, result.stderr.strip()]
    match = re.search(r"\b\d+\.\d+(?:\.\d+)?\b", f"{result.stdout}\n{result.stderr}")
    return (match.group(0) if match else None), evidence


def _major(version: str | None) -> int | None:
    if not version:
        return None
    match = re.match(r"(\d+)", version)
    return int(match.group(1)) if match else None


def _api_server_help(cli: Path) -> tuple[bool, list[str]]:
    result = _run([str(cli), "api-server", "--help"])
    text = f"{result.stdout}\n{result.stderr}"
    advertised = result.returncode == 0 and "api server" in text.casefold()
    return advertised, [
        f"kicad-cli api-server --help exit={result.returncode}",
        f"headless-api-advertised={str(advertised).lower()}",
    ]


def _headless_read_write(
    *,
    cli: Path,
    project_or_file: Path,
    version: str | None,
) -> tuple[SurfaceReport, SurfaceReport, LiveIdentityProbe | None, str | None]:
    evidence: list[str] = []
    try:
        from kipy import KiCad
    except ImportError as exc:
        reason = f"kicad-python is unavailable: {exc}"
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return (
            blocked,
            SurfaceReport("write", "blocked", version, reason, evidence, "unavailable"),
            None,
            reason,
        )

    parameters = inspect.signature(KiCad.__init__).parameters
    required = {"headless", "kicad_cli_path", "file_path"}
    missing = sorted(required - set(parameters))
    if missing:
        reason = "Installed kicad-python does not expose headless construction: " + ", ".join(
            missing
        )
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return (
            blocked,
            SurfaceReport("write", "blocked", version, reason, evidence, "unavailable"),
            None,
            reason,
        )

    client: Any | None = None
    try:
        constructor = cast(Callable[..., Any], KiCad)
        active_client = constructor(
            headless=True,
            timeout_ms=10_000,
            kicad_cli_path=str(cli),
            file_path=str(project_or_file),
        )
        client = active_client
        connected_version = str(active_client.get_version())
        board = active_client.get_board()
        evidence.extend([f"connected-version={connected_version}", "board-open=true"])
        identity_probe: LiveIdentityProbe | None = None
        identity_error: str | None = None
        try:
            from kicad_mcp.pcb.transaction_lifecycle import live_board_identity

            project = board.get_project()
            native_project_path = str(getattr(project, "path", "")).strip()
            native_board_name = str(getattr(board, "name", "")).strip()
            custom_identity = live_board_identity(board)
            identity_probe = LiveIdentityProbe(
                native_project_path=native_project_path,
                native_board_name=native_board_name,
                custom_board_name=custom_identity.board_name,
                custom_fingerprint=custom_identity.fingerprint,
            )
        except Exception as exc:
            identity_error = f"Live object identity probe failed: {type(exc).__name__}: {exc}"

        read = SurfaceReport(
            "read",
            "passed",
            version,
            "Headless IPC opened the fixture and returned a board handle.",
            list(evidence),
            "kicad-11-headless-ipc",
        )
        begin = getattr(board, "begin_commit", None)
        drop = getattr(board, "drop_commit", None)
        if callable(begin) and callable(drop):
            begin()
            drop()
            write = SurfaceReport(
                "write",
                "passed",
                version,
                "Headless IPC opened and discarded a no-op transaction without persisting changes.",
                [*evidence, "no-op-transaction=discarded"],
                "kicad-11-headless-ipc",
            )
        else:
            write = SurfaceReport(
                "write",
                "blocked",
                version,
                "The headless board API does not expose begin_commit/drop_commit.",
                list(evidence),
                "unavailable",
            )
        return read, write, identity_probe, identity_error
    except Exception as exc:
        reason = f"Headless IPC probe failed: {type(exc).__name__}: {exc}"
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return (
            blocked,
            SurfaceReport("write", "blocked", version, reason, evidence, "unavailable"),
            None,
            reason,
        )
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def _native_roundtrip_snapshot(board: object) -> RoundTripSnapshot:
    from kicad_mcp.evals.roundtrip_differential import RoundTripSnapshot

    typed_board = cast(Any, board)
    footprints = list(typed_board.get_footprints())
    tracks = list(typed_board.get_tracks())
    vias = list(typed_board.get_vias())
    zones = list(typed_board.get_zones())
    nets = list(typed_board.get_nets())
    net_names = tuple(name for net in nets if (name := str(getattr(net, "name", "")).strip()))
    return RoundTripSnapshot(
        footprint_count=len(footprints),
        track_count=len(tracks),
        via_count=len(vias),
        zone_count=len(zones),
        net_names=net_names,
    )


def _custom_roundtrip_snapshot(board_file: Path) -> RoundTripSnapshot:
    from kicad_mcp.evals.roundtrip_differential import RoundTripSnapshot
    from kicad_mcp.tools.board_file import _normalize_board_content, _parse_board_footprint_blocks
    from kicad_mcp.tools.pcb import (
        _board_file_nets,
        _board_file_segments,
        _board_file_vias,
        _board_file_zones,
    )

    content = _normalize_board_content(board_file.read_text(encoding="utf-8"))
    return RoundTripSnapshot(
        footprint_count=len(_parse_board_footprint_blocks(content)),
        track_count=len(_board_file_segments(content)),
        via_count=len(_board_file_vias(content)),
        zone_count=len(_board_file_zones(content)),
        net_names=tuple(_board_file_nets(content).values()),
    )


@contextmanager
def _headless_client(
    *,
    constructor: Callable[..., Any],
    cli: Path,
    file_path: Path,
) -> Iterator[Any]:
    client = constructor(
        headless=True,
        timeout_ms=10_000,
        kicad_cli_path=str(cli),
        file_path=str(file_path),
    )
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _headless_roundtrip_probe(
    *,
    cli: Path,
    project_or_file: Path,
    artifacts: Path,
) -> tuple[RoundTripProbe | None, str | None]:
    try:
        from kipy import KiCad
    except ImportError as exc:
        return None, f"kicad-python is unavailable: {exc}"

    output = artifacts / "differential" / f"native-roundtrip-{project_or_file.stem}.kicad_pcb"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    try:
        constructor = cast(Callable[..., Any], KiCad)
        with _headless_client(
            constructor=constructor,
            cli=cli,
            file_path=project_or_file,
        ) as source_client:
            source_board = source_client.get_board()
            save_as = getattr(source_board, "save_as", None)
            if not callable(save_as):
                raise RuntimeError("headless board API does not expose save_as")
            save_as(str(output), overwrite=True, include_project=False)
            if not output.is_file():
                raise RuntimeError("native save_as did not produce a board file")

        with _headless_client(
            constructor=constructor,
            cli=cli,
            file_path=output,
        ) as reopen_client:
            reopened_board = reopen_client.get_board()
            native_snapshot = _native_roundtrip_snapshot(reopened_board)

        custom_snapshot = _custom_roundtrip_snapshot(output)
        return RoundTripProbe(
            native_snapshot=native_snapshot,
            custom_snapshot=custom_snapshot,
        ), None
    except Exception as exc:
        return None, f"Native round-trip probe failed: {type(exc).__name__}: {exc}"


def _source_sha() -> str:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Could not resolve git executable for live identity differential")
    result = subprocess.run(
        [git, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    source_sha = result.stdout.strip().lower()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40,64}", source_sha) is None:
        raise RuntimeError("Could not resolve exact source SHA for live identity differential")
    return source_sha


def _persist_differential_result(
    *,
    artifacts: Path,
    result: DifferentialResult,
    operation: str,
    filename: str,
) -> None:
    from kicad_mcp.evals.semantic_differential import (
        DifferentialReport,
        aggregate_differential_results,
        render_differential_report_json,
    )

    differential = artifacts / "differential"
    differential.mkdir(parents=True, exist_ok=True)
    (differential / filename).write_text(
        json.dumps(result.model_dump(mode="json", exclude_none=True), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    summary_path = differential / "summary.json"
    existing = []
    if summary_path.is_file():
        report = DifferentialReport.model_validate(
            json.loads(summary_path.read_text(encoding="utf-8"))
        )
        existing = [
            item
            for item in report.results
            if not (item.operation == operation and item.fixture_id == result.fixture_id)
        ]
    summary = aggregate_differential_results([*existing, result])
    summary_path.write_text(
        render_differential_report_json(summary),
        encoding="utf-8",
        newline="\n",
    )


def _write_live_identity_differential(
    *,
    artifacts: Path,
    project_or_file: Path,
    kicad_version: str,
    probe: LiveIdentityProbe | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> object:
    from kicad_mcp.evals.live_object_identity_differential import (
        LIVE_OBJECT_IDENTITY_OPERATION,
        classify_live_object_identity_differential,
        hash_live_identity_fixture,
    )
    from kicad_mcp.pcb.live_edit_evidence import LiveBoardIdentity

    custom_identity = (
        LiveBoardIdentity(
            board_name=probe.custom_board_name,
            internal_key="redacted",
            fingerprint=probe.custom_fingerprint,
        )
        if probe is not None
        else None
    )
    result = classify_live_object_identity_differential(
        source_sha=_source_sha(),
        lane="preview",
        kicad_version=kicad_version,
        fixture_id=project_or_file.stem,
        fixture_hash=hash_live_identity_fixture(project_or_file),
        native_project_path=probe.native_project_path if probe is not None else None,
        native_board_name=probe.native_board_name if probe is not None else None,
        custom_identity=custom_identity,
        authority_available=authority_available,
        infrastructure_valid=infrastructure_valid,
        reason=reason,
    )

    _persist_differential_result(
        artifacts=artifacts,
        result=result,
        operation=LIVE_OBJECT_IDENTITY_OPERATION,
        filename="live-object-identity.json",
    )
    return result


def _write_roundtrip_differential(
    *,
    artifacts: Path,
    project_or_file: Path,
    kicad_version: str,
    probe: RoundTripProbe | None,
    authority_available: bool = True,
    infrastructure_valid: bool = True,
    reason: str | None = None,
) -> object:
    from kicad_mcp.evals.roundtrip_differential import (
        ROUNDTRIP_OPERATION,
        classify_roundtrip_differential,
        hash_roundtrip_fixture,
    )

    result = classify_roundtrip_differential(
        source_sha=_source_sha(),
        lane="preview",
        kicad_version=kicad_version,
        fixture_id=project_or_file.stem,
        fixture_hash=hash_roundtrip_fixture(project_or_file),
        native_snapshot=probe.native_snapshot if probe is not None else None,
        custom_snapshot=probe.custom_snapshot if probe is not None else None,
        authority_available=authority_available,
        infrastructure_valid=infrastructure_valid,
        reason=reason,
    )

    _persist_differential_result(
        artifacts=artifacts,
        result=result,
        operation=ROUNDTRIP_OPERATION,
        filename="roundtrip-reopen.json",
    )
    return result


def _export_report(
    *, cli: Path, project_or_file: Path, artifacts: Path, version: str | None
) -> SurfaceReport:
    output = artifacts / "export" / "board-stats.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            str(cli),
            "pcb",
            "export",
            "stats",
            "--output",
            str(output),
            str(project_or_file),
        ],
        timeout=180,
    )
    ok = result.returncode == 0 and output.exists() and output.stat().st_size > 0
    return SurfaceReport(
        "export",
        "passed" if ok else "blocked",
        version,
        (
            "KiCad CLI produced a non-empty board statistics artifact."
            if ok
            else f"KiCad CLI export smoke failed with exit code {result.returncode}."
        ),
        [f"kicad-cli pcb export stats exit={result.returncode}"],
        "kicad-cli" if ok else "unavailable",
    )


def run_canary(
    *,
    artifacts: Path,
    kicad_cli: Path | None,
    project_or_file: Path | None,
    require_ready: bool,
    unavailable_reason: str | None = None,
) -> int:
    """Run or report all three surfaces and optionally require native readiness."""
    artifacts = approved_runtime_path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    if kicad_cli is None or project_or_file is None:
        reason = unavailable_reason or "KiCad nightly CLI or fixture is unavailable."
        for surface in SURFACES:
            _write_report(
                artifacts,
                SurfaceReport(surface, "blocked", None, reason, [], "unavailable"),
            )
        return 1 if require_ready else 0

    kicad_cli = _validated_kicad_cli(kicad_cli)
    project_or_file = _validated_project_or_file(project_or_file)

    version, version_evidence = _version(kicad_cli)
    api_advertised, api_evidence = _api_server_help(kicad_cli)
    major = _major(version)
    if major is None or major < 11 or not api_advertised:
        reason = (
            f"KiCad 11+ headless IPC is not ready (version={version!r}, "
            f"apiServerAdvertised={api_advertised})."
        )
        for surface in ("read", "write"):
            _write_report(
                artifacts,
                SurfaceReport(
                    surface,
                    "blocked",
                    version,
                    reason,
                    [*version_evidence, *api_evidence],
                    "unavailable",
                ),
            )
        export = _export_report(
            cli=kicad_cli,
            project_or_file=project_or_file,
            artifacts=artifacts,
            version=version,
        )
        _write_report(artifacts, export)
        if version is not None:
            _write_live_identity_differential(
                artifacts=artifacts,
                project_or_file=project_or_file,
                kicad_version=version,
                probe=None,
                authority_available=False,
                reason=reason,
            )
            _write_roundtrip_differential(
                artifacts=artifacts,
                project_or_file=project_or_file,
                kicad_version=version,
                probe=None,
                authority_available=False,
                reason=reason,
            )
        return 1 if require_ready else 0

    read, write, identity_probe, identity_error = _headless_read_write(
        cli=kicad_cli,
        project_or_file=project_or_file,
        version=version,
    )
    read = SurfaceReport(
        read.surface,
        read.status,
        read.kicad_version,
        read.reason,
        [*version_evidence, *api_evidence, *read.evidence],
        read.backend,
    )
    write = SurfaceReport(
        write.surface,
        write.status,
        write.kicad_version,
        write.reason,
        [*version_evidence, *api_evidence, *write.evidence],
        write.backend,
    )
    export = _export_report(
        cli=kicad_cli,
        project_or_file=project_or_file,
        artifacts=artifacts,
        version=version,
    )
    for report in (read, write, export):
        _write_report(artifacts, report)
    identity_result = _write_live_identity_differential(
        artifacts=artifacts,
        project_or_file=project_or_file,
        kicad_version=version or "unknown",
        probe=identity_probe,
        infrastructure_valid=identity_error is None and identity_probe is not None,
        reason=identity_error,
    )
    roundtrip_probe, roundtrip_error = _headless_roundtrip_probe(
        cli=kicad_cli,
        project_or_file=project_or_file,
        artifacts=artifacts,
    )
    roundtrip_result = _write_roundtrip_differential(
        artifacts=artifacts,
        project_or_file=project_or_file,
        kicad_version=version or "unknown",
        probe=roundtrip_probe,
        infrastructure_valid=roundtrip_error is None and roundtrip_probe is not None,
        reason=roundtrip_error,
    )
    ready = (
        all(report.status == "passed" for report in (read, write, export))
        and getattr(identity_result, "status", None) == "match"
        and getattr(roundtrip_result, "status", None) == "match"
    )
    return 0 if ready or not require_ready else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--kicad-cli", type=Path)
    parser.add_argument("--project-or-file", type=Path)
    parser.add_argument("--unavailable-reason")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    return run_canary(
        artifacts=args.artifacts,
        kicad_cli=args.kicad_cli,
        project_or_file=args.project_or_file,
        require_ready=args.require_ready,
        unavailable_reason=args.unavailable_reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
