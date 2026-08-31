from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from scripts import kicad_canary
from scripts.kicad_canary import CanaryStep, build_canary_matrix, supports_feature_gate


def _compatibility_matrix() -> dict[str, object]:
    return {
        "kicad": {
            "primary": "10.0.x",
            "supported": [
                {
                    "range": "10.0.x",
                    "state": "primary",
                    "ci": "required",
                },
                {
                    "range": "9.x",
                    "state": "deprecated",
                    "upstreamEol": True,
                    "ci": "scheduled",
                },
                {
                    "range": "8.x",
                    "state": "deprecated",
                    "ci": "manual",
                },
            ],
        },
        "featureGates": {
            "manufacturingExports": {
                "kicad": ["9.x", "10.0.x"],
            },
            "kicad10AdvancedExports": {
                "kicad": ["10.0.x"],
            },
            "kicad10BoardStats": {
                "kicad": ["10.0.x"],
            },
            "kicad10PcbImport": {
                "kicad": ["10.0.x"],
            },
        },
    }


def test_kicad_canary_matrix_uses_scheduled_non_blocking_deprecated_lanes() -> None:
    matrix = build_canary_matrix(_compatibility_matrix(), include_manual=False)

    assert matrix == {
        "include": [
            {
                "id": "kicad-10-primary-windows",
                "range": "10.0.x",
                "state": "primary",
                "ci": "required",
                "os": "windows-2025-vs2026",
                "install": "choco",
                "version": "10.0.6",
                "continue_on_error": False,
            },
            {
                "id": "kicad-10-primary-linux",
                "range": "10.0.x",
                "state": "primary",
                "ci": "required",
                "os": "ubuntu-24.04",
                "install": "apt-ppa",
                "ppa": "ppa:kicad/kicad-10.0-releases",
                "package": "kicad",
                "continue_on_error": False,
            },
            {
                "id": "kicad-9-deprecated-linux",
                "range": "9.x",
                "state": "deprecated",
                "ci": "scheduled",
                "os": "ubuntu-24.04",
                "install": "apt-ppa",
                "ppa": "ppa:kicad/kicad-9.0-releases",
                "package": "kicad",
                "continue_on_error": True,
            },
            {
                "id": "kicad-10-nightly-linux",
                "range": "10.0.x",
                "state": "prerelease",
                "ci": "scheduled",
                "os": "ubuntu-24.04",
                "install": "apt-ppa",
                "ppa": "ppa:kicad/kicad-10.0-nightly",
                "package": "kicad",
                "continue_on_error": True,
            },
        ]
    }


def test_primary_matrix_includes_windows_10_0_6_contract_lane() -> None:
    matrix = build_canary_matrix(_compatibility_matrix(), include_manual=False)

    windows_primary = next(
        lane for lane in matrix["include"] if lane["id"] == "kicad-10-primary-windows"
    )

    assert windows_primary == {
        "id": "kicad-10-primary-windows",
        "range": "10.0.x",
        "state": "primary",
        "ci": "required",
        "os": "windows-2025-vs2026",
        "install": "choco",
        "version": "10.0.6",
        "continue_on_error": False,
    }


def test_kicad_canary_matrix_can_limit_pull_requests_to_required_lanes() -> None:
    matrix = build_canary_matrix(
        _compatibility_matrix(),
        include_manual=False,
        required_only=True,
    )

    assert [lane["id"] for lane in matrix["include"]] == [
        "kicad-10-primary-windows",
        "kicad-10-primary-linux",
    ]


def test_kicad_canary_matrix_exposes_manual_deprecated_lane_on_dispatch() -> None:
    matrix = build_canary_matrix(_compatibility_matrix(), include_manual=True)

    assert matrix["include"][3] == {
        "id": "kicad-8-deprecated-linux",
        "range": "8.x",
        "state": "deprecated",
        "ci": "manual",
        "os": "ubuntu-24.04",
        "install": "apt-ppa",
        "ppa": "ppa:kicad/kicad-8.0-releases",
        "package": "kicad",
        "continue_on_error": True,
    }
    assert matrix["include"][4]["id"] == "kicad-10-nightly-linux"


def test_kicad_canary_uses_shared_fixture_corpus() -> None:
    assert kicad_canary.FIXTURE_ROOT == (
        kicad_canary.REPO_ROOT / "packages" / "kicad-fixtures" / "fixtures"
    )
    assert (
        kicad_canary._project_file("clean-led-kicad10", ".kicad_pcb").name
        == "clean-led-kicad10.kicad_pcb"
    )


def test_fixture_workspace_copy_does_not_require_directory_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixture_root = tmp_path / "fixtures"
    source = fixture_root / "portable-fixture"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "board.kicad_pcb").write_text("board\n", encoding="utf-8")
    (nested / "sheet.kicad_sch").write_text("sheet\n", encoding="utf-8")
    monkeypatch.setattr(kicad_canary, "FIXTURE_ROOT", fixture_root)

    original_copystat = shutil.copystat

    def deny_directory_metadata(source_path, target_path, *, follow_symlinks=True):
        if Path(source_path).is_dir():
            raise PermissionError("directory metadata is not writable")
        return original_copystat(
            source_path,
            target_path,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(kicad_canary.shutil, "copystat", deny_directory_metadata)

    workspace = kicad_canary._prepare_fixture_workspaces(
        tmp_path / "artifacts",
        {"portable-fixture"},
    )

    copied = workspace / "portable-fixture"
    assert (copied / "board.kicad_pcb").read_text(encoding="utf-8") == "board\n"
    assert (copied / "nested" / "sheet.kicad_sch").read_text(encoding="utf-8") == "sheet\n"


def test_command_plan_covers_oaslana_38_export_surface(tmp_path: Path) -> None:
    steps = {
        step.name: step
        for step in kicad_canary._command_plan(tmp_path, _compatibility_matrix(), "10.0.x")
    }

    for name in [
        "version",
        "clean-erc",
        "dirty-erc",
        "clean-drc",
        "dirty-drc",
        "schematic-pdf",
        "schematic-pdf-no-property-popups",
        "pcb-pdf",
        "pcb-svg",
        "pcb-dxf",
        "gerbers",
        "drill",
        "ipc2581",
        "bom",
        "netlist",
        "board-stats",
        "pads-import-capability",
        "allegro-import-capability",
        "step",
        "path-with-spaces-board-stats",
        "unicode-path-board-stats",
        "read-only-output-failure",
    ]:
        assert name in steps

    assert steps["path-with-spaces-board-stats"].fixture == "paths-with-spaces"
    assert steps["unicode-path-board-stats"].fixture == "unicode-path-çöğü"
    assert steps["read-only-output-failure"].expects_failure is True
    assert "--layers" in steps["pcb-pdf"].args
    assert "--exclude-pdf-property-popups" in steps["schematic-pdf-no-property-popups"].args
    assert steps["pads-import-capability"].required_output_tokens == ("--format", "pads")
    assert steps["allegro-import-capability"].optional_capability is True
    assert str(kicad_canary.FIXTURE_ROOT) not in " ".join(steps["clean-erc"].args)
    assert str(tmp_path / "workspace" / "clean-led-kicad10") in " ".join(steps["clean-erc"].args)


def test_unsupported_feature_steps_are_structured_skips(tmp_path: Path) -> None:
    steps = {
        step.name: step
        for step in kicad_canary._command_plan(tmp_path, _compatibility_matrix(), "8.x")
    }

    assert steps["gerbers"].skip_reason == "manufacturingExports is not enabled for KiCad 8.x"
    assert steps["drill"].skip_reason == "manufacturingExports is not enabled for KiCad 8.x"
    assert (
        steps["schematic-pdf-no-property-popups"].skip_reason
        == "kicad10AdvancedExports is not enabled for KiCad 8.x"
    )
    assert steps["board-stats"].skip_reason == "kicad10BoardStats is not enabled for KiCad 8.x"
    assert (
        steps["pads-import-capability"].skip_reason
        == "kicad10PcbImport is not enabled for KiCad 8.x"
    )

    result = kicad_canary._run_step(Path(sys.executable), steps["gerbers"], tmp_path)

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "manufacturingExports is not enabled for KiCad 8.x"


def test_kicad_canary_gates_manufacturing_exports_by_compatibility_range() -> None:
    compatibility = _compatibility_matrix()

    assert supports_feature_gate(compatibility, "manufacturingExports", "10.0.x")
    assert supports_feature_gate(compatibility, "manufacturingExports", "9.x")
    assert not supports_feature_gate(compatibility, "manufacturingExports", "8.x")


def test_issue_276_deprecated_kicad9_lane_skips_kicad10_only_cli_steps(tmp_path: Path) -> None:
    # Regression for #276: the KiCad 9.x deprecated canary lane failed because
    # `pcb export stats` and `pcb import` are KiCad 10-only CLI surfaces that
    # KiCad 9.0.9 does not provide. They must be gated as structured skips so
    # the best-effort deprecated lane only exercises core workflows.
    compatibility = _compatibility_matrix()
    assert not supports_feature_gate(compatibility, "kicad10BoardStats", "9.x")
    assert not supports_feature_gate(compatibility, "kicad10PcbImport", "9.x")
    assert supports_feature_gate(compatibility, "kicad10BoardStats", "10.0.x")
    assert supports_feature_gate(compatibility, "kicad10PcbImport", "10.0.x")

    steps = {step.name: step for step in kicad_canary._command_plan(tmp_path, compatibility, "9.x")}

    for name in [
        "board-stats",
        "path-with-spaces-board-stats",
        "unicode-path-board-stats",
        "read-only-output-failure",
    ]:
        assert steps[name].skip_reason == "kicad10BoardStats is not enabled for KiCad 9.x"
    for name in ["pads-import-capability", "allegro-import-capability"]:
        assert steps[name].skip_reason == "kicad10PcbImport is not enabled for KiCad 9.x"

    # Core best-effort workflows stay active on the deprecated lane.
    for name in ["clean-erc", "clean-drc", "bom", "netlist", "gerbers", "step"]:
        assert steps[name].skip_reason is None

    skipped = kicad_canary._run_step(Path(sys.executable), steps["board-stats"], tmp_path)
    assert skipped["ok"] is True
    assert skipped["skipped"] is True
    assert skipped["reason"] == "kicad10BoardStats is not enabled for KiCad 9.x"


def test_missing_cli_writes_structured_summary(tmp_path: Path, monkeypatch) -> None:
    def raise_missing_cli() -> Path:
        raise FileNotFoundError("kicad-cli not found in test")

    monkeypatch.setattr(kicad_canary, "_resolve_cli", raise_missing_cli)

    exit_code = kicad_canary.run_canary(tmp_path, "10.0.x")
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert summary["kicadRange"] == "10.0.x"
    assert summary["failingFixtures"] == ["environment"]
    assert summary["results"] == [
        {
            "name": "resolve-cli",
            "fixture": "environment",
            "ok": False,
            "error": "kicad-cli not found in test",
        }
    ]


def test_violation_step_only_accepts_documented_kicad_exit_code(tmp_path: Path) -> None:
    cli = Path(sys.executable)
    script = tmp_path / "fake_kicad_cli.py"
    script.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")

    result = kicad_canary._run_step(
        cli,
        CanaryStep(
            name="dirty-drc",
            fixture="dirty",
            args=(str(script),),
            expects_violations=True,
        ),
        tmp_path / "artifacts",
    )

    assert result["returncode"] == 2
    assert result["ok"] is False


def test_optional_capability_probe_records_structured_skip(tmp_path: Path) -> None:
    cli = Path(sys.executable)
    script = tmp_path / "fake_kicad_cli.py"
    script.write_text("print('Usage: kicad-cli pcb import --format pads')\n", encoding="utf-8")

    result = kicad_canary._run_step(
        cli,
        CanaryStep(
            name="allegro-import-capability",
            fixture="kicad-10-0-3-regressions",
            args=(str(script),),
            required_output_tokens=("allegro",),
            optional_capability=True,
        ),
        tmp_path / "artifacts",
    )

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["missingTokens"] == ["allegro"]
    assert result["reason"] == "Optional capability not advertised: allegro"


def test_timeout_step_writes_artifact_logs(tmp_path: Path, monkeypatch) -> None:
    cli = Path(sys.executable)
    script = tmp_path / "hanging_kicad_cli.py"
    script.write_text(
        "import time\nprint('started', flush=True)\ntime.sleep(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kicad_canary, "DEFAULT_TIMEOUT_SECONDS", 0.01)
    artifacts = tmp_path / "artifacts"

    result = kicad_canary._run_step(
        cli,
        CanaryStep(name="version", fixture="compatibility", args=(str(script),)),
        artifacts,
    )

    assert result["ok"] is False
    assert result["returncode"] == -1
    assert "timed out" in (artifacts / "logs" / "version.stderr.log").read_text(encoding="utf-8")


def test_version_range_rejects_wrong_minor_for_minor_pinned_range(tmp_path: Path) -> None:
    stdout = tmp_path / "version.stdout.log"
    stderr = tmp_path / "version.stderr.log"
    stdout.write_text("KiCad 10.1.0\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")

    error = kicad_canary._version_range_error(
        {"stdout": str(stdout), "stderr": str(stderr)},
        "10.0.x",
    )

    assert error is not None
    assert "10.0.x" in error


def test_run_canary_writes_summary_when_version_range_fails(tmp_path: Path, monkeypatch) -> None:
    cli = Path(sys.executable)
    script = tmp_path / "version_kicad_cli.py"
    script.write_text("print('KiCad 10.1.0')\n", encoding="utf-8")

    monkeypatch.setattr(kicad_canary, "_resolve_cli", lambda: cli)
    monkeypatch.setattr(kicad_canary, "_read_compatibility_matrix", _compatibility_matrix)
    monkeypatch.setattr(
        kicad_canary,
        "_command_plan",
        lambda artifacts, compatibility, kicad_range: [
            CanaryStep(name="version", fixture="compatibility", args=(str(script),))
        ],
    )

    artifacts = tmp_path / "artifacts"
    exit_code = kicad_canary.run_canary(artifacts, "10.0.x")

    assert exit_code == 1
    assert (artifacts / "summary.json").exists()
    assert (artifacts / "failing-fixtures.txt").read_text(encoding="utf-8") == ("compatibility\n")
