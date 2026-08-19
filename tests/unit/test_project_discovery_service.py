from pathlib import Path

from kicad_mcp.project.discovery import ProjectDiscoveryService


def test_list_recent_projects_empty() -> None:
    service = ProjectDiscoveryService(find_recent_projects=lambda: [])
    assert service.list_recent_projects() == "No recent KiCad projects were found on this machine."


def test_list_recent_projects_renders_legacy_text(tmp_path: Path) -> None:
    projects = [tmp_path / "one.kicad_pro", tmp_path / "two.kicad_pro"]
    service = ProjectDiscoveryService(find_recent_projects=lambda: projects)
    assert service.list_recent_projects() == "\n".join(
        [
            "Found 2 recent project(s):",
            f"1. {projects[0]}",
            f"2. {projects[1]}",
            "",
            "Call `kicad_set_project()` with one of these paths to activate it.",
        ]
    )


def test_scan_directory_rejects_non_directory(tmp_path: Path) -> None:
    service = ProjectDiscoveryService(
        find_recent_projects=lambda: [], scan_project_dir=lambda _path: {}
    )
    assert (
        service.scan_directory(str(tmp_path / "missing")) == "The supplied path is not a directory."
    )


def test_scan_directory_renders_project_files(tmp_path: Path) -> None:
    project = tmp_path / "demo.kicad_pro"
    pcb = tmp_path / "demo.kicad_pcb"
    service = ProjectDiscoveryService(
        find_recent_projects=lambda: [],
        scan_project_dir=lambda _path: {"project": project, "pcb": pcb, "schematic": None},
    )
    assert service.scan_directory(str(tmp_path)) == "\n".join(
        [
            f"Scan results for {tmp_path.resolve()}:",
            f"- Project file: {project}",
            f"- PCB file: {pcb}",
            "- Schematic file: (none)",
        ]
    )
