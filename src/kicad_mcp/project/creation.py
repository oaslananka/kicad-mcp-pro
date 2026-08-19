"""Project creation orchestration independent of FastMCP."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from ..file_formats import GENERATED_SEXPR_DIALECT_VERSION


class ProjectCreationConfigProtocol(Protocol):
    @property
    def workspace_root(self) -> Path | None: ...

    @property
    def workspace(self) -> Path: ...

    @property
    def kicad_cli(self) -> Path: ...

    def apply_project(
        self,
        project_dir: Path,
        *,
        project_file: Path,
        pcb_file: Path,
        sch_file: Path,
        output_dir: Path,
    ) -> None: ...


class FormatUpgradeResultProtocol(Protocol):
    @property
    def upgraded(self) -> bool: ...

    @property
    def detail(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectCreationService:
    """Create and activate a minimal KiCad project using injected repository seams."""

    get_config: Callable[[], ProjectCreationConfigProtocol]
    assert_within: Callable[[Path, Path], None]
    new_project_files: Callable[[Path, str], tuple[Path, Path, Path]]
    new_project_payload: Callable[[Path, Path], dict[str, object]]
    upgrade_file: Callable[[Path, Literal["pcb", "sch"], Path], FormatUpgradeResultProtocol]
    reset_connection: Callable[[], None]

    def create(self, path: str, name: str, *, confirm_overwrite: bool = False) -> str:
        cfg = self.get_config()
        base_dir = Path(path).expanduser().resolve()
        if cfg.workspace_root is not None:
            self.assert_within(cfg.workspace, base_dir)
        project_dir = base_dir / name
        if project_dir.exists() and any(project_dir.iterdir()) and not confirm_overwrite:
            return (
                "Refusing to create a project over an existing non-empty directory.\n"
                f"- Directory: {project_dir}\n"
                "Choose a new name/path or rerun with confirm_overwrite=true."
            )
        project_dir.mkdir(parents=True, exist_ok=True)

        project_file, pcb_file, sch_file = self.new_project_files(project_dir, name)
        project_file.write_text(
            json.dumps(self.new_project_payload(cfg.kicad_cli, project_file), indent=2),
            encoding="utf-8",
        )
        pcb_file.write_text(
            f"(kicad_pcb (version {GENERATED_SEXPR_DIALECT_VERSION}) "
            '(generator "kicad-mcp-pro"))\n',
            encoding="utf-8",
        )
        sch_file.write_text(
            (
                "(kicad_sch\n"
                f"\t(version {GENERATED_SEXPR_DIALECT_VERSION})\n"
                '\t(generator "kicad-mcp-pro")\n'
                f'\t(uuid "{uuid.uuid4()}")\n'
                '\t(paper "A4")\n'
                "\t(lib_symbols)\n"
                '\t(sheet_instances (path "/" (page "1")))\n'
                "\t(embedded_fonts no)\n"
                ")\n"
            ),
            encoding="utf-8",
        )

        format_upgrades = [
            (pcb_file, "pcb", self.upgrade_file(pcb_file, "pcb", project_dir)),
            (sch_file, "sch", self.upgrade_file(sch_file, "sch", project_dir)),
        ]
        cfg.apply_project(
            project_dir,
            project_file=project_file,
            pcb_file=pcb_file,
            sch_file=sch_file,
            output_dir=project_dir / "output",
        )
        self.reset_connection()

        lines = [
            f"Created project '{name}' at {project_dir}.",
            f"- Project file: {project_file}",
            f"- PCB file: {pcb_file}",
            f"- Schematic file: {sch_file}",
        ]
        for generated_file, kind, result in format_upgrades:
            if not result.upgraded:
                lines.append(
                    f"- Format note ({kind}): kept repository writer dialect for "
                    f"{generated_file.name}; KiCad migration was unavailable ({result.detail})."
                )
        return "\n".join(lines)
