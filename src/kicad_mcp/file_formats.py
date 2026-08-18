"""KiCad file-format contracts for generated S-expression content.

The writer dialect version is the newest format whose emitted syntax is explicitly
owned by this repository. It is not a claim about the installed KiCad version.
KiCad-enabled tool adapters may migrate generated files after writing them.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GENERATED_SEXPR_DIALECT_VERSION = "20250316"
GeneratedFileKind = Literal["pcb", "sch", "sym", "fp"]
RunCli = Callable[..., tuple[int, str, str]]


@dataclass(frozen=True, slots=True)
class GeneratedFormatUpgradeResult:
    """Result of asking the installed KiCad CLI to migrate one generated file."""

    upgraded: bool
    detail: str = ""


def upgrade_generated_file(
    path: Path,
    kind: GeneratedFileKind,
    run_cli: RunCli,
    *,
    allowed_root: Path,
) -> GeneratedFormatUpgradeResult:
    """Migrate one generated file after constraining it to a trusted filesystem root."""
    try:
        resolved_root = allowed_root.expanduser().resolve(strict=True)
        resolved_path = path.expanduser().resolve(strict=True)
        relative_path = resolved_path.relative_to(resolved_root)
        safe_path = (resolved_root / relative_path).resolve(strict=True)
    except (OSError, ValueError) as exc:
        return GeneratedFormatUpgradeResult(
            upgraded=False,
            detail=f"Generated file is outside the allowed root or unavailable: {exc}",
        )

    if kind != "fp":
        try:
            original = safe_path.read_bytes()
        except OSError as exc:
            return GeneratedFormatUpgradeResult(upgraded=False, detail=str(exc))

        temp_names = {
            "pcb": "generated.kicad_pcb",
            "sch": "generated.kicad_sch",
            "sym": "generated.kicad_sym",
        }
        with tempfile.TemporaryDirectory(prefix="kicad-mcp-format-") as temp_dir:
            temp_file = Path(temp_dir) / temp_names[kind]
            temp_file.write_bytes(original)
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
            safe_path.write_bytes(temp_file.read_bytes())
            return GeneratedFormatUpgradeResult(upgraded=True)

    try:
        content = safe_path.read_text(encoding="utf-8")
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
        safe_path.write_text(upgraded_file.read_text(encoding="utf-8"), encoding="utf-8")
        return GeneratedFormatUpgradeResult(upgraded=True)
