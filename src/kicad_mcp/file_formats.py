"""KiCad file-format contracts for native readers and generated S-expression content.

The writer dialect version is the newest format whose emitted syntax is explicitly
owned by this repository. It is not a claim about the installed KiCad version.
KiCad-enabled tool adapters may migrate generated files after writing them.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .utils.file_replace import FileChangedError, replace_if_unchanged

GENERATED_SEXPR_DIALECT_VERSION = "20250316"
# Explicit reader compatibility, independent of the generated writer dialect.
FOOTPRINT_LIST_READ_VERSIONS = frozenset({"20241229", "20250216", "20250316", "20260206"})
GeneratedFileKind = Literal["pcb", "sch", "sym", "fp"]
NonFootprintGeneratedFileKind = Literal["pcb", "sch", "sym"]
RunCli = Callable[..., tuple[int, str, str]]


@dataclass(frozen=True, slots=True)
class GeneratedFormatUpgradeResult:
    """Result of asking the installed KiCad CLI to migrate one generated file."""

    upgraded: bool
    detail: str = ""


def _resolve_generated_path(path: Path, allowed_root: Path) -> Path:
    resolved_root = allowed_root.expanduser().resolve(strict=True)
    resolved_path = path.expanduser().resolve(strict=True)
    relative_path = resolved_path.relative_to(resolved_root)
    return (resolved_root / relative_path).resolve(strict=True)


def _commit_upgraded_file(
    safe_path: Path, content: str, original_mode: int, original: bytes
) -> GeneratedFormatUpgradeResult:
    """Publish a conversion only if the original destination still matches."""
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".kicad-mcp-format-",
            dir=safe_path.parent,
            delete=False,
        ) as output:
            staged = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(staged, original_mode)
        replace_if_unchanged(staged, safe_path, original)
        return GeneratedFormatUpgradeResult(upgraded=True)
    except (FileChangedError, OSError) as exc:
        return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _upgrade_non_footprint(
    safe_path: Path,
    kind: NonFootprintGeneratedFileKind,
    run_cli: RunCli,
) -> GeneratedFormatUpgradeResult:
    try:
        original_bytes = safe_path.read_bytes()
        original = original_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        original_mode = stat.S_IMODE(safe_path.stat().st_mode)
    except OSError as exc:
        return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))

    temp_names = {
        "pcb": "generated.kicad_pcb",
        "sch": "generated.kicad_sch",
        "sym": "generated.kicad_sym",
    }
    with tempfile.TemporaryDirectory(prefix="kicad-mcp-format-") as temp_dir:
        temp_file = Path(temp_dir) / temp_names[kind]
        temp_file.write_text(original, encoding="utf-8")
        try:
            code, stdout, stderr = run_cli(kind, "upgrade", "--force", str(temp_file))
        except OSError as exc:
            return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))
        if code != 0:
            return GeneratedFormatUpgradeResult(
                upgraded=False,
                detail=stderr or stdout or "KiCad format upgrade failed.",
            )
        if not temp_file.is_file():
            return GeneratedFormatUpgradeResult(
                upgraded=False,
                detail="KiCad format upgrade did not preserve the temporary output file.",
            )
        return _commit_upgraded_file(
            safe_path, temp_file.read_text(encoding="utf-8"), original_mode, original_bytes
        )


def _upgrade_footprint(safe_path: Path, run_cli: RunCli) -> GeneratedFormatUpgradeResult:
    try:
        original_bytes = safe_path.read_bytes()
        content = original_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        original_mode = stat.S_IMODE(safe_path.stat().st_mode)
    except OSError as exc:
        return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))

    match = re.match(r'^\(footprint\s+"([^"\\]+)"', content)
    if match is None:
        return GeneratedFormatUpgradeResult(
            upgraded=False,
            detail="Generated footprint name could not be resolved for format migration.",
        )
    footprint_name = match.group(1)
    if Path(footprint_name).name != footprint_name:
        return GeneratedFormatUpgradeResult(
            upgraded=False,
            detail="Generated footprint name is not safe for temporary library migration.",
        )

    with tempfile.TemporaryDirectory(prefix="kicad-mcp-format-") as temp_dir:
        temp_root = Path(temp_dir)
        input_dir = temp_root / "input.pretty"
        output_dir = temp_root / "output.pretty"
        input_dir.mkdir()
        input_file = input_dir / f"{footprint_name}.kicad_mod"
        input_file.write_text(content, encoding="utf-8")

        try:
            code, stdout, stderr = run_cli(
                "fp",
                "upgrade",
                "--force",
                "--output",
                str(output_dir),
                str(input_dir),
            )
        except OSError as exc:
            return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))
        if code != 0:
            return GeneratedFormatUpgradeResult(
                upgraded=False,
                detail=stderr or stdout or "KiCad footprint format upgrade failed.",
            )

        upgraded_file = output_dir / input_file.name
        if not upgraded_file.is_file():
            return GeneratedFormatUpgradeResult(
                upgraded=False,
                detail="KiCad footprint upgrade did not produce the expected output file.",
            )
        return _commit_upgraded_file(
            safe_path, upgraded_file.read_text(encoding="utf-8"), original_mode, original_bytes
        )


def upgrade_generated_file(
    path: Path,
    kind: GeneratedFileKind,
    run_cli: RunCli,
    *,
    allowed_root: Path,
) -> GeneratedFormatUpgradeResult:
    """Migrate one generated file after constraining it to a trusted filesystem root."""
    try:
        safe_path = _resolve_generated_path(path, allowed_root)
    except (OSError, ValueError) as exc:
        return GeneratedFormatUpgradeResult(
            upgraded=False,
            detail=f"Generated file is outside the allowed root or unavailable: {exc}",
        )

    if kind == "fp":
        return _upgrade_footprint(safe_path, run_cli)
    return _upgrade_non_footprint(safe_path, kind, run_cli)
