"""Regression tests for variant export output-path confinement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kicad_mcp.path_safety import UnsafePathError
from kicad_mcp.tools import export_support, variants


@pytest.fixture
def export_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    out_dir = tmp_path / "output" / "variants"
    out_dir.mkdir(parents=True)
    state = {
        "default_variant": "default",
        "variants": {"default": {"overrides": {}}},
    }

    class Config:
        def resolve_within_project(self, path: str, *, allow_absolute: bool = False) -> Path:
            return variants.resolve_under(tmp_path, path, allow_absolute=allow_absolute)

        def ensure_output_dir(self, subdir: str) -> Path:
            assert subdir == "variants"
            return out_dir

    monkeypatch.setattr(variants, "get_config", Config)
    monkeypatch.setattr(variants, "_load_state", lambda: state)
    monkeypatch.setattr(variants, "_bom_rows", lambda *_args: [])
    monkeypatch.setattr(export_support, "_ensure_output_dir", lambda _subdir: out_dir)
    monkeypatch.setattr(export_support, "_get_sch_file", lambda: tmp_path / "board.kicad_sch")
    monkeypatch.setattr(export_support, "_get_pcb_file", lambda: tmp_path / "board.kicad_pcb")

    def unexpected_cli(_args: object) -> None:
        pytest.fail("Export CLI must not run for an unsafe output path.")

    monkeypatch.setattr(export_support, "_run_cli_variants", unexpected_cli)
    return out_dir, state


@pytest.mark.parametrize(
    "variant",
    [
        "../outside",
        r"..\outside",
        "/absolute",
        r"C:\absolute",
        r"\\server\share\outside",
        "nested/child",
        "nested\\child",
        ".",
        "..",
    ],
)
@pytest.mark.parametrize(
    "tool_name",
    [
        "variant_export_bom",
        "variant_export_schematic",
        "variant_export_manufacturing_package",
    ],
)
def test_variant_exports_reject_unsafe_variant_names(
    export_setup: tuple[Path, dict], variant: str, tool_name: str
) -> None:
    out_dir, state = export_setup
    state["variants"][variant] = {"overrides": {}}
    with pytest.raises(ValueError, match="single filename components"):
        getattr(variants, tool_name)(variant)
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize(
    "output_name",
    [
        "../outside.pdf",
        r"..\outside.pdf",
        "/absolute.pdf",
        r"C:\absolute.pdf",
        r"\\server\share\outside.pdf",
        "nested/file.pdf",
        "nested\\file.pdf",
        ".",
        "..",
    ],
)
@pytest.mark.parametrize(
    "tool_name",
    ["variant_export_schematic", "variant_export_manufacturing_package"],
)
def test_variant_exports_reject_unsafe_output_names(
    export_setup: tuple[Path, dict], output_name: str, tool_name: str
) -> None:
    out_dir, _state = export_setup
    with pytest.raises(ValueError, match="single filename components"):
        getattr(variants, tool_name)("default", output_name)
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize(
    "tool_name",
    ["variant_export_schematic", "variant_export_manufacturing_package"],
)
def test_custom_output_does_not_bypass_variant_validation(
    export_setup: tuple[Path, dict], tool_name: str
) -> None:
    out_dir, state = export_setup
    state["variants"]["../outside"] = {"overrides": {}}
    with pytest.raises(ValueError, match="single filename components"):
        getattr(variants, tool_name)("../outside", "safe.pdf")
    assert list(out_dir.iterdir()) == []


def test_variant_export_rejects_symlink_outside_output_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("keep", encoding="utf-8")
    alias = out_dir / "alias.csv"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host.")

    with pytest.raises(UnsafePathError):
        variants._safe_variant_export_path(out_dir, "default", alias.name)
    assert outside.read_text(encoding="utf-8") == "keep"


def test_variant_export_allows_single_component_names(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    actual = variants._safe_variant_export_path(out_dir, "revision B", "revision B_bom.csv")
    assert actual == out_dir / "revision B_bom.csv"


def test_schematic_export_preserves_valid_custom_filename(
    export_setup: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir, _state = export_setup

    def export_pdf(commands: list[list[str]]) -> tuple[int, str, str]:
        command = commands[0]
        destination = Path(command[command.index("--output") + 1])
        assert destination.parent == out_dir
        destination.write_bytes(b"fake-pdf")
        return 0, "", ""

    monkeypatch.setattr(export_support, "_run_cli_variants", export_pdf)
    result = variants.variant_export_schematic("default", "custom-schematic.pdf")
    assert "custom-schematic.pdf" in result
    assert (out_dir / "custom-schematic.pdf").read_bytes() == b"fake-pdf"


def test_manufacturing_export_writes_manifest_only_within_output_dir(
    export_setup: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir, _state = export_setup
    project = out_dir.parents[1]
    board = project / "board.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    (project / "approval.json").write_text(
        json.dumps(
            {
                "approved_by": "Test Reviewer",
                "approved_at_utc": "2026-11-27T00:00:00Z",
                "approval_scope": "manufacturing release",
                "approved_project_files": [
                    {"path": board.name, "sha256": hashlib.sha256(board.read_bytes()).hexdigest()}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.validation._evaluate_project_gate", lambda: [])
    monkeypatch.setattr(
        export_support, "_run_cli_variants", lambda _commands: (1, "", "mocked CLI")
    )
    result = variants.variant_export_manufacturing_package(
        "default", "custom-manufacturing.json", "approval.json"
    )
    assert "custom-manufacturing.json" in result
    assert (out_dir / "custom-manufacturing.json").is_file()
    assert (out_dir / "default_bom.csv").is_file()
    assert (out_dir / "default_gerber").is_dir()
    assert (out_dir / "default_drill").is_dir()


def test_bom_export_never_overwrites_external_symlink(
    export_setup: tuple[Path, dict], tmp_path: Path
) -> None:
    out_dir, _state = export_setup
    outside = tmp_path / "important.txt"
    outside.write_text("unchanged", encoding="utf-8")
    alias = out_dir / "default_bom.csv"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host.")

    with pytest.raises(UnsafePathError):
        variants.variant_export_bom("default")
    assert outside.read_text(encoding="utf-8") == "unchanged"


def test_variant_manufacturing_requires_approval_before_artifacts(
    export_setup: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir, _ = export_setup
    monkeypatch.setattr("kicad_mcp.tools.validation._evaluate_project_gate", lambda: [])
    result = variants.variant_export_manufacturing_package("default")
    assert "approval_evidence_path" in result
    assert list(out_dir.iterdir()) == []


def test_variant_manufacturing_rejects_changed_project_before_export(
    export_setup: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir, _ = export_setup
    project = out_dir.parents[1]
    board = project / "board.kicad_pcb"
    board.write_text("changed", encoding="utf-8")
    (project / "approval.json").write_text(
        json.dumps(
            {
                "approved_by": "Test Reviewer",
                "approved_at_utc": "2026-11-27T00:00:00Z",
                "approval_scope": "manufacturing release",
                "approved_project_files": [
                    {"path": board.name, "sha256": hashlib.sha256(b"before").hexdigest()}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.validation._evaluate_project_gate", lambda: [])
    result = variants.variant_export_manufacturing_package(
        "default", approval_evidence_path="approval.json"
    )
    assert "project file digest mismatch" in result
    assert list(out_dir.iterdir()) == []


def test_variant_manufacturing_rejects_failed_gate_before_approval(
    export_setup: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    out_dir, _ = export_setup
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [SimpleNamespace(status="FAIL")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._render_project_gate_report", lambda outcomes, summary: summary
    )
    result = variants.variant_export_manufacturing_package(
        "default", approval_evidence_path="unreadable.json"
    )
    assert "hard-blocked until the full project quality gate passes" in result
    assert list(out_dir.iterdir()) == []
