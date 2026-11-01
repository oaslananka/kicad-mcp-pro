"""Opt-in local-only native KiCad DRC counts on an isolated project copy.

NOT wired to Cloud transport/MCP. A future native remote operation needs
a separately reviewed owner approval and authenticated request boundary.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from kicad_mcp.cloud_readonly_boundary import (
    _NAME,
    LocalReadDeniedError,
    OperatorProject,
    _open_operator_directory,
)

_DENIED = "request denied"
_MAX_PCB_BYTES = 32 * 1024 * 1024
_MAX_PROJECT_BYTES = 4 * 1024 * 1024
_MAX_REPORT_BYTES = 1024 * 1024


def _copy_bound_file(
    dir_fd: int, name: str, destination: Path, limit: int, *, required: bool
) -> None:
    """Copy an owner-selected direct child, rejecting symlinks and hardlinks."""
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise LocalReadDeniedError(_DENIED)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        if required:
            raise LocalReadDeniedError(_DENIED) from exc
        return
    except OSError as exc:
        raise LocalReadDeniedError(_DENIED) from exc

    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            or opened.st_size > limit
        ):
            raise LocalReadDeniedError(_DENIED)
        remaining = limit + 1
        with destination.open("xb") as output:
            while remaining > 0:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
            if remaining <= 0:
                raise LocalReadDeniedError(_DENIED)
    except OSError as exc:
        raise LocalReadDeniedError(_DENIED) from exc
    finally:
        os.close(fd)


def summarize_native_pcb_drc(policy: OperatorProject) -> dict[str, int]:
    """Return *only* DRC issue counts; never expose project contents or paths.

    Runs KiCad CLI on owner-approved, bounded temporary **copies** so the
    original board and project files cannot be modified by the child process.
    No shell, caller-supplied executable, flags, output path or file names.
    """
    if (
        not isinstance(policy, OperatorProject)
        or not isinstance(policy.filename_stem, str)
        or not _NAME.fullmatch(policy.filename_stem)
        or policy.filename_stem in {".", ".."}
    ):
        raise LocalReadDeniedError(_DENIED)
    executable = shutil.which("kicad-cli")
    if not executable:
        raise LocalReadDeniedError(_DENIED)
    fd: int | None = None
    try:
        fd = _open_operator_directory(policy.directory)
        with tempfile.TemporaryDirectory(prefix="kicad-mcp-drc-") as scratch:
            folder = Path(scratch)
            board = folder / (policy.filename_stem + ".kicad_pcb")
            project = folder / (policy.filename_stem + ".kicad_pro")
            output = folder / "drc.json"
            _copy_bound_file(fd, board.name, board, _MAX_PCB_BYTES, required=True)
            _copy_bound_file(fd, project.name, project, _MAX_PROJECT_BYTES, required=False)
            completed = subprocess.run(
                [
                    executable,
                    "pcb",
                    "drc",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                    str(board),
                ],
                cwd=folder,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=40,
            )
            if completed.returncode != 0:
                raise LocalReadDeniedError(_DENIED)
            report = output.stat()
            if not stat.S_ISREG(report.st_mode) or not (1 <= report.st_size <= _MAX_REPORT_BYTES):
                raise LocalReadDeniedError(_DENIED)
            contents = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(contents, dict):
                raise LocalReadDeniedError(_DENIED)
            violations = contents.get("violations")
            unconnected = contents.get("unconnected_items")
            if not isinstance(violations, list) or not isinstance(unconnected, list):
                raise LocalReadDeniedError(_DENIED)
            return {"violations": len(violations), "unconnectedItems": len(unconnected)}
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc
    finally:
        if fd is not None:
            os.close(fd)
