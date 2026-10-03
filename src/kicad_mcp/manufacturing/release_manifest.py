"""FastMCP-independent manufacturing release-manifest generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .release_evidence import build_release_file_hashes, build_source_hashes, find_release_files


class DesignIntentLike(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


class ReleaseManifestPrerequisiteError(RuntimeError):
    """Raised when required manufacturing release inputs are unavailable."""


@dataclass(frozen=True)
class ReleaseManifestContext:
    """Runtime inputs needed to generate a manufacturing release manifest."""

    output_dir: Path
    project_file: Path | None
    pcb_file: Path | None
    sch_file: Path | None
    kicad_cli: Path
    kicad_cli_version: str | None
    kicad_mcp_version: str


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ReleaseManifestService:
    """Generate deterministic manufacturing package manifests without FastMCP."""

    now_utc: Callable[[], datetime] = _now_utc

    def create_manifest(
        self,
        *,
        intent: DesignIntentLike,
        context: ReleaseManifestContext,
        output_path: str = "",
    ) -> str:
        """Generate ``manifest.json`` and ``MANIFEST.txt`` for release artifacts.

        ``output_path`` is intentionally retained but ignored to preserve the
        existing public MCP behavior during this structural extraction.
        """
        _ = output_path
        out_dir = context.output_dir
        if not out_dir.exists():
            raise ReleaseManifestPrerequisiteError(
                f"Output directory does not exist: {out_dir}\n"
                "Run export_manufacturing_package() first."
            )

        release_files = find_release_files(out_dir)
        if not release_files:
            raise ReleaseManifestPrerequisiteError(
                "No release files found in output directory.\n"
                "Run export_manufacturing_package() first to generate Gerber/drill/BOM files."
            )

        file_hashes = build_release_file_hashes(release_files)

        intent_json = json.dumps(intent.model_dump(), sort_keys=True)
        intent_hash = hashlib.sha256(intent_json.encode()).hexdigest()[:16]
        source_hashes = build_source_hashes(
            [
                ("project", context.project_file),
                ("pcb", context.pcb_file),
                ("schematic", context.sch_file),
            ]
        )
        provenance: dict[str, Any] = {
            "kicad_mcp_version": context.kicad_mcp_version,
            "kicad_cli": str(context.kicad_cli),
            "kicad_cli_version": context.kicad_cli_version,
            "intent_hash": intent_hash,
            "source_hashes": source_hashes,
        }
        content_basis = json.dumps({"files": file_hashes, "provenance": provenance}, sort_keys=True)
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()

        manifest: dict[str, Any] = {
            "kicad_mcp_version": context.kicad_mcp_version,
            "generated_utc": self.now_utc().isoformat(),
            "content_hash": content_hash,
            "intent_hash": intent_hash,
            "provenance": provenance,
            "files": file_hashes,
        }

        manifest_json_path = out_dir / "manifest.json"
        manifest_json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        txt_lines = [
            "kicad-mcp-pro Release Manifest",
            f"Generated: {manifest['generated_utc']}",
            f"Tool version: kicad-mcp-pro {context.kicad_mcp_version}",
            f"KiCad CLI version: {context.kicad_cli_version or 'unknown'}",
            f"Content hash: {content_hash}",
            f"Intent hash: {intent_hash}",
            "",
            f"{'Filename':<50} {'SHA256':>16}",
            "-" * 70,
        ]
        for entry in file_hashes:
            txt_lines.append(f"{entry['filename']:<50} {entry['sha256'][:16]}")

        manifest_txt_path = out_dir / "MANIFEST.txt"
        manifest_txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

        return (
            "Release manifest generated:\n"
            f"- {manifest_json_path} ({len(file_hashes)} files)\n"
            f"- {manifest_txt_path}\n"
            f"Content hash: {content_hash}\n"
            f"Intent hash: {intent_hash}\n"
            f"Files covered: {', '.join(entry['filename'] for entry in file_hashes[:10])}"
            + ("…" if len(file_hashes) > 10 else "")
        )
