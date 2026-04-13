"""Helpers for FreeRouting-based Specctra workflows."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from ..config import get_config
from ..discovery import get_cli_capabilities

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FreeRoutingResult:
    """Normalized outcome of a FreeRouting autoroute run."""

    mode: str
    command: tuple[str, ...]
    input_dsn: Path
    output_ses: Path
    returncode: int
    stdout: str
    stderr: str


def _sanitize_text(text: str) -> str:
    cfg = get_config()
    sanitized = text.replace(str(cfg.kicad_cli), "kicad-cli")
    if cfg.freerouting_jar is not None:
        sanitized = sanitized.replace(str(cfg.freerouting_jar), "<freerouting-jar>")
    if cfg.project_dir is not None:
        sanitized = sanitized.replace(str(cfg.project_dir), "<project>")
    return sanitized.strip()


def _common_parent(paths: list[Path]) -> Path:
    return Path(os.path.commonpath([str(path.resolve()) for path in paths]))


def _container_relpath(base: Path, target: Path) -> str:
    return target.resolve().relative_to(base.resolve()).as_posix()


class FreeRoutingRunner:
    """Run FreeRouting against project-provided Specctra files."""

    def __init__(
        self,
        *,
        docker_image: str | None = None,
        docker_executable: str | None = None,
        java_executable: str | None = None,
    ) -> None:
        cfg = get_config()
        self._docker_image = docker_image or cfg.freerouting_image
        self._docker_executable = docker_executable or cfg.docker_executable
        self._java_executable = java_executable or cfg.java_executable

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path:
        """Stage an existing DSN file for FreeRouting or explain the missing export path."""
        cfg = get_config()
        target = cfg.resolve_within_project(dsn_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return target

        caps = get_cli_capabilities(cfg.kicad_cli)
        if caps.supports_specctra_export:
            raise RuntimeError(
                "Specctra DSN export appears to be available in this KiCad CLI build, "
                "but the exact headless export syntax has not been wired yet. "
                f"Export the DSN once from KiCad and place it at {target}."
            )

        candidates = [
            pcb_path.with_suffix(".dsn"),
            cfg.project_root / "routing" / f"{pcb_path.stem}.dsn",
            cfg.project_root / "output" / "routing" / f"{pcb_path.stem}.dsn",
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return target

        raise RuntimeError(
            "The detected KiCad CLI does not provide headless Specctra DSN export on this "
            f"machine ({cfg.kicad_cli}). Export a .dsn file from KiCad's PCB Editor and place "
            f"it at {target} or next to {pcb_path.name}."
        )

    def run_freerouting(
        self,
        dsn_path: Path,
        ses_path: Path,
        *,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: Path | None = None,
        net_classes_to_ignore: list[str] | None = None,
        timeout: float | None = None,
    ) -> FreeRoutingResult:
        """Run FreeRouting via Docker or a local JAR and return the normalized result."""
        cfg = get_config()
        if not dsn_path.exists():
            raise FileNotFoundError(f"Specctra DSN input was not found: {dsn_path}")

        output = ses_path.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        ignore_arg = ",".join(net_classes_to_ignore or [])

        if use_docker:
            mount_root = _common_parent([dsn_path, output])
            dsn_arg = _container_relpath(mount_root, dsn_path)
            ses_arg = _container_relpath(mount_root, output)
            command = [
                self._docker_executable,
                "run",
                "--rm",
                "-v",
                f"{mount_root}:/work",
                "-w",
                "/work",
                self._docker_image,
                "-de",
                dsn_arg,
                "-do",
                ses_arg,
                "-mp",
                str(max_passes),
            ]
            if ignore_arg:
                command.extend(["-inc", ignore_arg])
            mode = "docker"
        else:
            jar_path = (freerouting_jar_path or cfg.freerouting_jar)
            if jar_path is None:
                raise RuntimeError(
                    "FreeRouting JAR path is required when use_docker=False. "
                    "Set KICAD_MCP_FREEROUTING_JAR or pass freerouting_jar_path."
                )
            command = [
                self._java_executable,
                "-jar",
                str(jar_path),
                "-de",
                str(dsn_path.resolve()),
                "-do",
                str(output),
                "-mp",
                str(max_passes),
            ]
            if ignore_arg:
                command.extend(["-inc", ignore_arg])
            mode = "jar"

        if thread_count > 1:
            logger.debug("freerouting_thread_count_advisory", thread_count=thread_count, mode=mode)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout or max(cfg.cli_timeout, 300.0),
                check=False,
            )
        except FileNotFoundError as exc:
            missing = self._docker_executable if use_docker else self._java_executable
            raise RuntimeError(
                f"{missing} was not found. Install the required runtime or switch "
                f"{'use_docker' if use_docker else 'to Docker mode'}."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "FreeRouting timed out after "
                f"{exc.timeout} seconds while processing {dsn_path.name}."
            ) from exc

        return FreeRoutingResult(
            mode=mode,
            command=tuple(str(part) for part in command),
            input_dsn=dsn_path.resolve(),
            output_ses=output,
            returncode=result.returncode,
            stdout=_sanitize_text(result.stdout),
            stderr=_sanitize_text(result.stderr),
        )

    def import_ses(self, pcb_path: Path, ses_path: Path) -> Path:
        """Stage a session file for KiCad import and explain the remaining manual step."""
        cfg = get_config()
        if not ses_path.exists():
            raise FileNotFoundError(f"Specctra SES session was not found: {ses_path}")

        staged = cfg.resolve_within_project(cfg.ensure_output_dir("routing") / ses_path.name)
        if staged.resolve() != ses_path.resolve():
            shutil.copy2(ses_path, staged)

        caps = get_cli_capabilities(cfg.kicad_cli)
        if caps.supports_specctra_import:
            logger.warning(
                "specctra_import_detected_but_manual",
                pcb=str(pcb_path),
                ses=str(staged),
            )

        return staged
