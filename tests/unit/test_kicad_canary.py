from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_connectivity_differential_command_plan_is_stable_lane_only(tmp_path: Path) -> None:
    stable = {
        step.name: step
        for step in kicad_canary._command_plan(tmp_path, _compatibility_matrix(), "10.0.x")
    }
    preview = {
        step.name: step
        for step in kicad_canary._command_plan(tmp_path, _compatibility_matrix(), "11.0.x")
    }

    stable_step = stable["differential-connectivity-netlist"]
    assert stable_step.fixture == kicad_canary.CONNECTIVITY_DIFFERENTIAL_FIXTURE_ID
    assert stable_step.skip_reason is None
    assert stable_step.outputs == (tmp_path / "differential" / "connectivity-native.net",)
    assert str(tmp_path / "workspace" / kicad_canary.CONNECTIVITY_DIFFERENTIAL_FIXTURE_ID) in (
        " ".join(stable_step.args)
    )
    assert str(kicad_canary.CONNECTIVITY_DIFFERENTIAL_FIXTURE_DIR) not in " ".join(stable_step.args)
    assert preview["differential-connectivity-netlist"].skip_reason == (
        "connectivity differential is currently enabled on the stable KiCad 10 lane"
    )


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


def test_shared_dru_fixtures_avoid_removed_kicad_10_99_footprint_property() -> None:
    offenders = []
    for path in sorted(kicad_canary.FIXTURE_ROOT.rglob("*.kicad_dru")):
        raw = path.read_text(encoding="utf-8")
        if "A.Footprint" in raw or "B.Footprint" in raw:
            offenders.append(path.relative_to(kicad_canary.FIXTURE_ROOT).as_posix())

    assert offenders == []


def test_package_kicad_canary_scripts_keep_artifacts_inside_repository() -> None:
    root = Path(__file__).resolve().parents[2]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))

    for script_name in (
        "test:kicad-cli-contract",
        "test:kicad-cli-contract:nightly",
        "test:kicad-cli-contract:future",
    ):
        command = package["scripts"][script_name]
        assert "../../artifacts/" not in command
        assert "--artifacts artifacts/kicad-cli-contract/" in command


def test_public_compatibility_docs_use_current_compatibility_command() -> None:
    root = Path(__file__).resolve().parents[2]
    compatibility_docs = sorted((root / "docs" / "compatibility").glob("kicad-*.md"))
    assert compatibility_docs

    for path in compatibility_docs:
        raw = path.read_text(encoding="utf-8")
        assert "corepack pnpm run check:compatibility" not in raw, path


def test_connectivity_differential_writes_stable_machine_report(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = tmp_path / "fixture.kicad_sch"
    fixture.write_text("(kicad_sch)", encoding="utf-8")
    native = tmp_path / "native.net"
    native.write_text(
        '(export (nets (net (code "1") (name "N1") '
        '(node (ref "U1") (pin "1")) (node (ref "R1") (pin "2")))))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)
    monkeypatch.setattr(
        kicad_canary,
        "_connectivity_groups",
        lambda _path: [
            {
                "names": ["N1"],
                "pins": [
                    {"reference": "R1", "pin": "2"},
                    {"reference": "U1", "pin": "1"},
                ],
            }
        ],
    )

    result = kicad_canary._write_connectivity_differential_report(
        artifacts=tmp_path / "artifacts",
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        native_netlist=native,
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "match"
    assert not (tmp_path / "artifacts" / "differential" / "summary.json").exists()
    kicad_canary._write_differential_summary(tmp_path / "artifacts", [result])
    payload = json.loads(
        (tmp_path / "artifacts" / "differential" / "summary.json").read_text(encoding="utf-8")
    )
    assert payload["lane"] == "stable"
    assert payload["results_total"] == 1
    assert payload["match_count"] == 1
    assert payload["results"][0]["fixture_hash"].startswith("sha256:")
    assert payload["results"][0]["comparison_method"] == "pin-membership-sha256.v1"


def test_connectivity_differential_is_not_claimed_for_non_stable_lane(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = tmp_path / "fixture.kicad_sch"
    fixture.write_text("(kicad_sch)", encoding="utf-8")
    assert (
        kicad_canary._write_connectivity_differential_report(
            artifacts=tmp_path / "artifacts",
            kicad_range="11.x",
            kicad_version="11.0.0",
            native_netlist=tmp_path / "missing.net",
            fixture=fixture,
        )
        is None
    )
    assert not (tmp_path / "artifacts" / "differential" / "summary.json").exists()


def test_differential_source_sha_rejects_dirty_source_tree(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def run(args: list[str], **kwargs: object):
        calls.append(tuple(args))
        if args[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=" M scripts/kicad_canary.py\n", stderr=""
            )
        return subprocess.CompletedProcess(args, 0, stdout="a" * 40 + "\n", stderr="")

    monkeypatch.setattr(
        kicad_canary.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None
    )
    monkeypatch.setattr(kicad_canary.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="clean source tree"):
        kicad_canary._source_sha()
    assert calls == [("/usr/bin/git", "status", "--porcelain", "--untracked-files=no")]


def test_differential_source_sha_fails_closed_without_git(monkeypatch) -> None:
    monkeypatch.setattr(kicad_canary.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="git executable is unavailable"):
        kicad_canary._source_sha()


def test_connectivity_differential_missing_native_artifact_is_unavailable_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture.kicad_sch"
    fixture.write_text("(kicad_sch)", encoding="utf-8")
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)
    monkeypatch.setattr(
        kicad_canary,
        "_connectivity_groups",
        lambda _path: [
            {
                "names": ["N1"],
                "pins": [
                    {"reference": "R1", "pin": "2"},
                    {"reference": "U1", "pin": "1"},
                ],
            }
        ],
    )

    result = kicad_canary._write_connectivity_differential_report(
        artifacts=tmp_path / "artifacts",
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        native_netlist=tmp_path / "missing.net",
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is not None
    assert result.reason == "Native KiCad connectivity authority artifact is unavailable."
    assert not (tmp_path / "artifacts" / "differential" / "summary.json").exists()
    kicad_canary._write_differential_summary(tmp_path / "artifacts", [result])
    payload = json.loads(
        (tmp_path / "artifacts" / "differential" / "summary.json").read_text(encoding="utf-8")
    )
    assert payload["unavailable_authority_count"] == 1
    assert payload["infrastructure_invalid_count"] == 0


def test_connectivity_differential_parser_failure_is_infrastructure_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "fixture.kicad_sch"
    fixture.write_text("(kicad_sch)", encoding="utf-8")
    native = tmp_path / "native.net"
    native.write_text("not-a-netlist\n", encoding="utf-8")
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)
    monkeypatch.setattr(
        kicad_canary,
        "_native_net_map",
        lambda _path: (_ for _ in ()).throw(ValueError("native parse failed")),
    )

    result = kicad_canary._write_connectivity_differential_report(
        artifacts=tmp_path / "artifacts",
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        native_netlist=native,
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "infrastructure-invalid"
    assert result.reason == "Connectivity differential infrastructure failed (ValueError)."
    assert not (tmp_path / "artifacts" / "differential" / "summary.json").exists()
    kicad_canary._write_differential_summary(tmp_path / "artifacts", [result])
    payload = json.loads(
        (tmp_path / "artifacts" / "differential" / "summary.json").read_text(encoding="utf-8")
    )
    assert payload["match_count"] == 0
    assert payload["infrastructure_invalid_count"] == 1


def test_connectivity_differential_workspace_copies_gallery_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "gallery"
    source.mkdir()
    (source / "demo.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    (source / "demo.kicad_pro").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(kicad_canary, "CONNECTIVITY_DIFFERENTIAL_FIXTURE_DIR", source)
    monkeypatch.setattr(kicad_canary, "CONNECTIVITY_DIFFERENTIAL_FIXTURE_NAME", "demo.kicad_sch")

    fixture = kicad_canary._prepare_connectivity_differential_workspace(tmp_path / "artifacts")

    assert fixture == (
        tmp_path
        / "artifacts"
        / "workspace"
        / kicad_canary.CONNECTIVITY_DIFFERENTIAL_FIXTURE_ID
        / "demo.kicad_sch"
    )
    assert fixture.read_text(encoding="utf-8") == "(kicad_sch)\n"
    assert (fixture.parent / "demo.kicad_pro").is_file()


def _write_geometry_differential_inputs(tmp_path: Path) -> tuple[Path, Path]:
    artifacts = tmp_path / "artifacts"
    fixture = artifacts / "workspace" / "clean-led-kicad10" / "demo.kicad_pcb"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "(kicad_pcb\n"
        "  (gr_line (start 10 20) (end 110 20) "
        '(stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'
        "  (gr_line (start 110 20) (end 110 80) "
        '(stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'
        "  (gr_line (start 110 80) (end 10 80) "
        '(stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'
        "  (gr_line (start 10 80) (end 10 20) "
        '(stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'
        ")\n",
        encoding="utf-8",
    )
    native = artifacts / "reports" / "board-stats.txt"
    native.parent.mkdir(parents=True)
    native.write_text(
        "PCB statistics report\n"
        "=====================\n"
        "Board\n-----\n"
        "- Width: 100.0000 mm\n"
        "- Height: 60.0000 mm\n"
        "- Area: 6000.00 mm²\n",
        encoding="utf-8",
    )
    return artifacts, fixture


def test_geometry_differential_matches_native_board_stats(tmp_path: Path, monkeypatch) -> None:
    artifacts, fixture = _write_geometry_differential_inputs(tmp_path)
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)

    result = kicad_canary._write_geometry_differential_result(
        artifacts=artifacts,
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        fixture_id="geometry-fixture",
        native_stats=artifacts / "reports" / "board-stats.txt",
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "match"
    assert result.fixture_id == "geometry-fixture"
    assert result.operation == "geometry.board-outline-size"
    assert result.authority == "kicad-cli:pcb-export-stats"


def test_geometry_differential_missing_native_artifact_is_unavailable_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, fixture = _write_geometry_differential_inputs(tmp_path)
    (artifacts / "reports" / "board-stats.txt").unlink()
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)

    result = kicad_canary._write_geometry_differential_result(
        artifacts=artifacts,
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        fixture_id="geometry-fixture",
        native_stats=artifacts / "reports" / "board-stats.txt",
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is not None


def test_geometry_differential_failed_native_step_is_unavailable_even_with_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, fixture = _write_geometry_differential_inputs(tmp_path)
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)

    result = kicad_canary._write_geometry_differential_result(
        artifacts=artifacts,
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        fixture_id="geometry-fixture",
        native_stats=artifacts / "reports" / "board-stats.txt",
        fixture=fixture,
        native_authority_available=False,
    )

    assert result is not None
    assert result.status == "unavailable-authority"
    assert result.native_result_hash is None
    assert result.custom_result_hash is not None


def test_geometry_differential_parser_failure_is_infrastructure_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, fixture = _write_geometry_differential_inputs(tmp_path)
    monkeypatch.setattr(kicad_canary, "_source_sha", lambda: "a" * 40)
    monkeypatch.setattr(
        kicad_canary,
        "_custom_board_outline_bounds",
        lambda _path: (_ for _ in ()).throw(ValueError("parse failed")),
    )

    result = kicad_canary._write_geometry_differential_result(
        artifacts=artifacts,
        kicad_range="10.0.x",
        kicad_version="10.0.6",
        fixture_id="geometry-fixture",
        native_stats=artifacts / "reports" / "board-stats.txt",
        fixture=fixture,
    )

    assert result is not None
    assert result.status == "infrastructure-invalid"
    assert result.fixture_id == "geometry-fixture"
    assert result.native_result_hash is None
    assert result.custom_result_hash is None
