#!/usr/bin/env python3
"""Generate KiCad canary lanes and run artifact-producing CLI smoke checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from runtime_path_safety import approved_runtime_path

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT
FIXTURE_ROOT = REPO_ROOT / "packages" / "kicad-fixtures" / "fixtures"
DEFAULT_TIMEOUT_SECONDS = 180
KICAD_VIOLATION_EXIT_CODE = 5
WINDOWS_PRIMARY_RUNNER = "windows-2025-vs2026"
WINDOWS_PRIMARY_KICAD_VERSION = "10.0.6"

INSTALLERS = {
    "10.0.x": {
        "release_ppa": "ppa:kicad/kicad-10.0-releases",
        "nightly_ppa": "ppa:kicad/kicad-10.0-nightly",
        "package": "kicad",
    },
    "9.x": {
        "release_ppa": "ppa:kicad/kicad-9.0-releases",
        "package": "kicad",
    },
    "8.x": {
        "release_ppa": "ppa:kicad/kicad-8.0-releases",
        "package": "kicad",
    },
}


@dataclass(frozen=True)
class CanaryStep:
    """One KiCad CLI canary command and its artifact expectations."""

    name: str
    fixture: str
    args: tuple[str, ...] = ()
    outputs: tuple[Path, ...] = ()
    expects_violations: bool = False
    expects_failure: bool = False
    skip_reason: str | None = None
    readonly_dirs: tuple[Path, ...] = ()
    required_output_tokens: tuple[str, ...] = ()
    optional_capability: bool = False


def _read_compatibility_matrix() -> dict[str, Any]:
    data = yaml.safe_load((REPO_ROOT / "compatibility.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("compatibility.yaml must contain a YAML mapping")
    return data


def _entry_value(entry: object, key: str) -> str:
    if not isinstance(entry, dict):
        raise TypeError(f"KiCad compatibility entry must be a mapping, got {entry!r}")
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"KiCad compatibility entry missing string {key!r}: {entry!r}")
    return value


def _lane_id(kicad_range: str, state: str) -> str:
    major = _expected_major(kicad_range)
    return f"kicad-{major}-{state}"


def _expected_major(kicad_range: str) -> int:
    match = re.match(r"(?P<major>\d+)", kicad_range)
    if match is None:
        raise ValueError(f"Cannot derive KiCad major version from range {kicad_range!r}")
    return int(match.group("major"))


def _linux_release_lane(entry: object) -> dict[str, object]:
    kicad_range = _entry_value(entry, "range")
    state = _entry_value(entry, "state")
    ci_mode = _entry_value(entry, "ci")
    installer = INSTALLERS.get(kicad_range)
    if installer is None:
        raise ValueError(f"No canary installer metadata for KiCad range {kicad_range!r}")
    return {
        "id": f"{_lane_id(kicad_range, state)}-linux",
        "range": kicad_range,
        "state": state,
        "ci": ci_mode,
        "os": "ubuntu-24.04",
        "install": "apt-ppa",
        "ppa": installer["release_ppa"],
        "package": installer["package"],
        "continue_on_error": state == "deprecated",
    }


def _windows_primary_lane(entry: object, compatibility: dict[str, Any]) -> dict[str, object]:
    kicad_range = _entry_value(entry, "range")
    state = _entry_value(entry, "state")
    ci_mode = _entry_value(entry, "ci")
    kicad = compatibility.get("kicad")
    latest_verified = WINDOWS_PRIMARY_KICAD_VERSION
    if isinstance(kicad, dict) and isinstance(kicad.get("latestVerified"), str):
        latest_verified = str(kicad["latestVerified"])
    return {
        "id": f"{_lane_id(kicad_range, state)}-windows",
        "range": kicad_range,
        "state": state,
        "ci": ci_mode,
        "os": WINDOWS_PRIMARY_RUNNER,
        "install": "choco",
        "version": latest_verified,
        "continue_on_error": False,
    }


def _nightly_lane(primary_range: str) -> dict[str, object]:
    installer = INSTALLERS.get(primary_range)
    if installer is None or "nightly_ppa" not in installer:
        raise ValueError(f"No nightly canary installer metadata for {primary_range!r}")
    return {
        "id": f"kicad-{_expected_major(primary_range)}-nightly-linux",
        "range": primary_range,
        "state": "prerelease",
        "ci": "scheduled",
        "os": "ubuntu-24.04",
        "install": "apt-ppa",
        "ppa": installer["nightly_ppa"],
        "package": installer["package"],
        "continue_on_error": True,
    }


def build_canary_matrix(
    compatibility: dict[str, Any],
    *,
    include_manual: bool,
    required_only: bool = False,
) -> dict[str, list[dict[str, object]]]:
    """Return GitHub Actions matrix lanes derived from compatibility metadata."""
    kicad = compatibility.get("kicad")
    if not isinstance(kicad, dict):
        raise ValueError("compatibility metadata missing kicad mapping")
    entries = kicad.get("supported")
    if not isinstance(entries, list):
        raise ValueError("compatibility metadata missing kicad.supported list")

    primary = kicad.get("primary")
    if not isinstance(primary, str) or not primary:
        raise ValueError("compatibility metadata missing kicad.primary")

    lanes: list[dict[str, object]] = []
    for entry in entries:
        ci_mode = _entry_value(entry, "ci")
        if required_only and ci_mode != "required":
            continue
        if ci_mode not in {"required", "scheduled"} and not (
            include_manual and ci_mode == "manual"
        ):
            continue
        if _entry_value(entry, "range") == primary and _entry_value(entry, "state") == "primary":
            lanes.append(_windows_primary_lane(entry, compatibility))
        lanes.append(_linux_release_lane(entry))

    if not required_only:
        lanes.append(_nightly_lane(primary))
    return {"include": lanes}


def supports_feature_gate(
    compatibility: dict[str, Any],
    feature_name: str,
    kicad_range: str,
) -> bool:
    """Return whether a KiCad range is included in a compatibility feature gate."""
    feature_gates = compatibility.get("featureGates")
    if not isinstance(feature_gates, dict):
        return False
    feature = feature_gates.get(feature_name)
    if not isinstance(feature, dict):
        return False
    ranges = feature.get("kicad")
    return isinstance(ranges, list) and kicad_range in ranges


def _fixture_file(root: Path, fixture: str, suffix: str) -> Path:
    matches = sorted((root / fixture).glob(f"*{suffix}"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one {suffix} file in fixture {fixture!r}, found {len(matches)}"
        )
    return matches[0]


def _project_file(fixture: str, suffix: str) -> Path:
    return _fixture_file(FIXTURE_ROOT, fixture, suffix)


def _copy_fixture_tree(source: Path, target: Path) -> None:
    """Copy fixture contents without requiring writable filesystem metadata."""
    target.mkdir(parents=True, exist_ok=False)
    for entry in source.iterdir():
        destination = target / entry.name
        if entry.is_dir():
            _copy_fixture_tree(entry, destination)
        elif entry.is_file():
            shutil.copyfile(entry, destination)
        else:
            raise OSError(f"Unsupported fixture entry: {entry}")


def _prepare_fixture_workspaces(artifacts: Path, fixtures: set[str]) -> Path:
    workspace_root = artifacts / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    for fixture in sorted(fixtures):
        source = FIXTURE_ROOT / fixture
        target = workspace_root / fixture
        if not source.is_dir():
            raise FileNotFoundError(f"Unknown KiCad fixture: {fixture}")
        if target.exists():
            shutil.rmtree(target)
        _copy_fixture_tree(source, target)
    return workspace_root


def _feature_skip_reason(
    compatibility: dict[str, Any],
    feature_name: str,
    kicad_range: str,
) -> str | None:
    if supports_feature_gate(compatibility, feature_name, kicad_range):
        return None
    return f"{feature_name} is not enabled for KiCad {kicad_range}"


def _command_plan(
    artifacts: Path,
    compatibility: dict[str, Any],
    kicad_range: str,
) -> list[CanaryStep]:
    workspace_root = _prepare_fixture_workspaces(
        artifacts,
        {
            "clean-led-kicad10",
            "drc-courtyard-error",
            "erc-power-pin-error",
            "kicad-10-0-3-regressions",
            "paths-with-spaces",
            "unicode-path-çöğü",
        },
    )
    clean_schematic = _fixture_file(workspace_root, "clean-led-kicad10", ".kicad_sch")
    clean_board = _fixture_file(workspace_root, "clean-led-kicad10", ".kicad_pcb")
    regression_schematic = _fixture_file(workspace_root, "kicad-10-0-3-regressions", ".kicad_sch")
    dirty_erc = _fixture_file(workspace_root, "erc-power-pin-error", ".kicad_sch")
    dirty_drc = _fixture_file(workspace_root, "drc-courtyard-error", ".kicad_pcb")
    path_with_spaces_board = _fixture_file(workspace_root, "paths-with-spaces", ".kicad_pcb")
    unicode_path_board = _fixture_file(workspace_root, "unicode-path-çöğü", ".kicad_pcb")

    reports = artifacts / "reports"
    manufacturing = artifacts / "manufacturing"
    graphics = artifacts / "graphics"
    readonly_output = artifacts / "readonly-project"
    manufacturing_skip = _feature_skip_reason(compatibility, "manufacturingExports", kicad_range)
    kicad10_export_skip = _feature_skip_reason(
        compatibility,
        "kicad10AdvancedExports",
        kicad_range,
    )
    board_stats_skip = _feature_skip_reason(compatibility, "kicad10BoardStats", kicad_range)
    pcb_import_skip = _feature_skip_reason(compatibility, "kicad10PcbImport", kicad_range)
    steps = [
        CanaryStep(name="version", fixture="compatibility", args=("version",)),
        CanaryStep(
            name="clean-erc",
            fixture="clean-led-kicad10",
            args=(
                "sch",
                "erc",
                "--format",
                "json",
                "--severity-all",
                "--output",
                str(reports / "clean-erc.json"),
                str(clean_schematic),
            ),
            outputs=(reports / "clean-erc.json",),
        ),
        CanaryStep(
            name="dirty-erc",
            fixture="erc-power-pin-error",
            args=(
                "sch",
                "erc",
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                "--output",
                str(reports / "dirty-erc.json"),
                str(dirty_erc),
            ),
            outputs=(reports / "dirty-erc.json",),
            expects_violations=True,
        ),
        CanaryStep(
            name="clean-drc",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "drc",
                "--format",
                "json",
                "--severity-all",
                "--output",
                str(reports / "clean-drc.json"),
                str(clean_board),
            ),
            outputs=(reports / "clean-drc.json",),
        ),
        CanaryStep(
            name="dirty-drc",
            fixture="drc-courtyard-error",
            args=(
                "pcb",
                "drc",
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                "--output",
                str(reports / "dirty-drc.json"),
                str(dirty_drc),
            ),
            outputs=(reports / "dirty-drc.json",),
            expects_violations=True,
        ),
        CanaryStep(
            name="schematic-pdf",
            fixture="clean-led-kicad10",
            args=(
                "sch",
                "export",
                "pdf",
                "--output",
                str(reports / "schematic.pdf"),
                str(clean_schematic),
            ),
            outputs=(reports / "schematic.pdf",),
        ),
        CanaryStep(
            name="schematic-pdf-no-property-popups",
            fixture="kicad-10-0-3-regressions",
            args=(
                "sch",
                "export",
                "pdf",
                "--output",
                str(reports / "schematic-no-property-popups.pdf"),
                "--exclude-pdf-property-popups",
                str(regression_schematic),
            ),
            outputs=(reports / "schematic-no-property-popups.pdf",),
            skip_reason=kicad10_export_skip,
        ),
        CanaryStep(
            name="pcb-pdf",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "pdf",
                "--output",
                str(reports / "pcb.pdf"),
                "--layers",
                "F.Cu,B.Cu,Edge.Cuts",
                str(clean_board),
            ),
            outputs=(reports / "pcb.pdf",),
        ),
        CanaryStep(
            name="pcb-svg",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "svg",
                "--output",
                str(graphics / "pcb-svg"),
                "--layers",
                "F.Cu,B.Cu,Edge.Cuts",
                str(clean_board),
            ),
            outputs=(graphics / "pcb-svg",),
        ),
        CanaryStep(
            name="pcb-dxf",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "dxf",
                "--output",
                str(graphics / "pcb.dxf"),
                "--layers",
                "F.Cu,B.Cu,Edge.Cuts",
                str(clean_board),
            ),
            outputs=(graphics / "pcb.dxf",),
        ),
        CanaryStep(
            name="bom",
            fixture="clean-led-kicad10",
            args=(
                "sch",
                "export",
                "bom",
                "--format-preset",
                "CSV",
                "--output",
                str(reports / "bom.csv"),
                str(clean_schematic),
            ),
            outputs=(reports / "bom.csv",),
        ),
        CanaryStep(
            name="netlist",
            fixture="clean-led-kicad10",
            args=(
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadsexpr",
                "--output",
                str(reports / "netlist.net"),
                str(clean_schematic),
            ),
            outputs=(reports / "netlist.net",),
        ),
        CanaryStep(
            name="board-stats",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "stats",
                "--output",
                str(reports / "board-stats.txt"),
                str(clean_board),
            ),
            outputs=(reports / "board-stats.txt",),
            skip_reason=board_stats_skip,
        ),
        CanaryStep(
            name="pads-import-capability",
            fixture="kicad-10-0-3-regressions",
            args=("pcb", "import", "--help"),
            required_output_tokens=("--format", "pads"),
            skip_reason=pcb_import_skip,
        ),
        CanaryStep(
            name="allegro-import-capability",
            fixture="kicad-10-0-3-regressions",
            args=("pcb", "import", "--help"),
            required_output_tokens=("allegro",),
            optional_capability=True,
            skip_reason=pcb_import_skip,
        ),
        CanaryStep(
            name="step",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "step",
                "--output",
                str(graphics / "board.step"),
                str(clean_board),
            ),
            outputs=(graphics / "board.step",),
        ),
        CanaryStep(
            name="path-with-spaces-board-stats",
            fixture="paths-with-spaces",
            args=(
                "pcb",
                "export",
                "stats",
                "--output",
                str(reports / "path-with-spaces-board-stats.txt"),
                str(path_with_spaces_board),
            ),
            outputs=(reports / "path-with-spaces-board-stats.txt",),
            skip_reason=board_stats_skip,
        ),
        CanaryStep(
            name="unicode-path-board-stats",
            fixture="unicode-path-çöğü",
            args=(
                "pcb",
                "export",
                "stats",
                "--output",
                str(reports / "unicode-path-board-stats.txt"),
                str(unicode_path_board),
            ),
            outputs=(reports / "unicode-path-board-stats.txt",),
            skip_reason=board_stats_skip,
        ),
        CanaryStep(
            name="read-only-output-failure",
            fixture="clean-led-kicad10",
            args=(
                "pcb",
                "export",
                "stats",
                "--output",
                str(readonly_output / "board-stats.txt"),
                str(clean_board),
            ),
            expects_failure=True,
            readonly_dirs=(readonly_output,),
            skip_reason=board_stats_skip,
        ),
    ]

    steps.extend(
        [
            CanaryStep(
                name="gerbers",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "gerbers",
                    "--layers",
                    "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts",
                    "--output",
                    str(manufacturing / "gerbers"),
                    str(clean_board),
                ),
                outputs=(manufacturing / "gerbers",),
                skip_reason=manufacturing_skip,
            ),
            CanaryStep(
                name="drill",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "drill",
                    "--output",
                    str(manufacturing / "drill"),
                    str(clean_board),
                ),
                outputs=(manufacturing / "drill",),
                skip_reason=manufacturing_skip,
            ),
            CanaryStep(
                name="ipc2581",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "ipc2581",
                    "--output",
                    str(manufacturing / "board.ipc2581"),
                    str(clean_board),
                ),
                outputs=(manufacturing / "board.ipc2581",),
                skip_reason=manufacturing_skip,
            ),
        ]
    )

    # ---- M2-M4 tool coverage ----
    steps.extend(
        [
            CanaryStep(
                name="schematic-dxf",
                fixture="clean-led-kicad10",
                args=(
                    "sch",
                    "export",
                    "dxf",
                    "--output",
                    str(graphics / "schematic.dxf"),
                    str(clean_schematic),
                ),
                outputs=(graphics / "schematic.dxf",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="schematic-svg",
                fixture="clean-led-kicad10",
                args=(
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    str(graphics / "schematic.svg"),
                    str(clean_schematic),
                ),
                outputs=(graphics / "schematic.svg",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="schematic-python-bom",
                fixture="clean-led-kicad10",
                args=(
                    "sch",
                    "export",
                    "python-bom",
                    "--output",
                    str(reports / "python_bom.py"),
                    str(clean_schematic),
                ),
                outputs=(reports / "python_bom.py",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="pcb-render",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "render",
                    "--output",
                    str(graphics / "render.png"),
                    "--side",
                    "top",
                    str(clean_board),
                ),
                outputs=(graphics / "render.png",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="pcb-export-stepz",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "stpz",
                    "--output",
                    str(graphics / "board.stepz"),
                    str(clean_board),
                ),
                outputs=(graphics / "board.stepz",),
                skip_reason=manufacturing_skip,
            ),
            CanaryStep(
                name="spice-netlist",
                fixture="clean-led-kicad10",
                args=(
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    "spice",
                    "--output",
                    str(reports / "simulation.cir"),
                    str(clean_schematic),
                ),
                outputs=(reports / "simulation.cir",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="pcb-export-brep",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "brep",
                    "--output",
                    str(graphics / "board.brep"),
                    str(clean_board),
                ),
                outputs=(graphics / "board.brep",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="pcb-export-glb",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "glb",
                    "--output",
                    str(graphics / "board.glb"),
                    str(clean_board),
                ),
                outputs=(graphics / "board.glb",),
                skip_reason=kicad10_export_skip,
            ),
            CanaryStep(
                name="pcb-export-stl",
                fixture="clean-led-kicad10",
                args=(
                    "pcb",
                    "export",
                    "stl",
                    "--output",
                    str(graphics / "board.stl"),
                    str(clean_board),
                ),
                outputs=(graphics / "board.stl",),
                skip_reason=kicad10_export_skip,
            ),
        ]
    )
    return steps


def _cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    for name in ("KICAD_CANARY_KICAD_CLI", "KICAD_MCP_KICAD_CLI", "KICAD_CLI_PATH"):
        raw = os.environ.get(name, "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    discovered = shutil.which("kicad-cli")
    if discovered:
        candidates.append(Path(discovered))
    return candidates


def _resolve_cli() -> Path:
    for candidate in _cli_candidates():
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in _cli_candidates()) or "<none>"
    raise FileNotFoundError(f"kicad-cli not found via canary env or PATH. Candidates: {searched}")


def _write_text(path: Path, text: str) -> None:
    path = approved_runtime_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _subprocess_output_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _path_has_content(path: Path) -> bool:
    if path.is_dir():
        return any(path.iterdir())
    return path.exists() and path.stat().st_size > 0


def _make_readonly_dirs(paths: tuple[Path, ...]) -> list[Path]:
    readonly_paths: list[Path] = []
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o555)
        readonly_paths.append(path)
    return readonly_paths


def _restore_writable_dirs(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.chmod(0o755)
        except OSError:
            pass


def _run_step(cli: Path, step: CanaryStep, artifacts: Path) -> dict[str, object]:
    if step.skip_reason is not None:
        return {
            "name": step.name,
            "fixture": step.fixture,
            "returncode": None,
            "expectsViolations": step.expects_violations,
            "expectsFailure": step.expects_failure,
            "outputs": [str(path.relative_to(artifacts)) for path in step.outputs],
            "ok": True,
            "skipped": True,
            "reason": step.skip_reason,
        }
    if step.readonly_dirs and os.name == "nt":
        return {
            "name": step.name,
            "fixture": step.fixture,
            "returncode": None,
            "expectsViolations": step.expects_violations,
            "expectsFailure": step.expects_failure,
            "outputs": [],
            "ok": True,
            "skipped": True,
            "reason": "read-only directory permission checks are covered by Linux canary lanes",
        }

    command = [str(cli), *step.args]
    error: str | None = None
    readonly_dirs = _make_readonly_dirs(step.readonly_dirs)
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _subprocess_output_text(exc.stdout or exc.output)
        stderr = _subprocess_output_text(exc.stderr)
        error = f"Command timed out after {exc.timeout} seconds"
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        stderr += f"{error}\n"
        returncode = -1
    except (OSError, subprocess.SubprocessError) as exc:
        stdout = ""
        error = f"{type(exc).__name__}: {exc}"
        stderr = f"{error}\n"
        returncode = -1
    finally:
        _restore_writable_dirs(readonly_dirs)

    logs = artifacts / "logs"
    _write_text(logs / f"{step.name}.command.txt", shlex.join(command) + "\n")
    _write_text(logs / f"{step.name}.stdout.log", stdout)
    _write_text(logs / f"{step.name}.stderr.log", stderr)

    outputs_exist = all(_path_has_content(path) for path in step.outputs)
    command_ok = (
        returncode == KICAD_VIOLATION_EXIT_CODE if step.expects_violations else returncode == 0
    )
    if step.expects_failure:
        command_ok = returncode not in {0, None}
        outputs_exist = True
    combined_output = f"{stdout}\n{stderr}".casefold()
    missing_tokens = [
        token for token in step.required_output_tokens if token.casefold() not in combined_output
    ]
    capability_skip = bool(step.optional_capability and missing_tokens and command_ok)
    step_ok = command_ok and outputs_exist and (not missing_tokens or capability_skip)
    step_result: dict[str, object] = {
        "name": step.name,
        "fixture": step.fixture,
        "returncode": returncode,
        "expectsViolations": step.expects_violations,
        "expectsFailure": step.expects_failure,
        "outputs": [str(path.relative_to(artifacts)) for path in step.outputs],
        "ok": step_ok,
    }
    if missing_tokens:
        step_result["missingTokens"] = missing_tokens
    if capability_skip:
        step_result["skipped"] = True
        step_result["reason"] = f"Optional capability not advertised: {', '.join(missing_tokens)}"
    if error is not None:
        step_result["error"] = error
    return step_result


def _version_range_error(version_result: dict[str, object], kicad_range: str) -> str | None:
    stdout_path = Path(str(version_result["stdout"]))
    stderr_path = Path(str(version_result["stderr"]))
    output = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (stdout_path, stderr_path)
        if path.exists()
    )
    match = re.search(r"\b(?P<major>\d+)\.(?P<minor>\d+)(?:\.\d+)?\b", output)
    if match is None:
        return f"Could not read KiCad version from canary logs for {kicad_range}"

    range_match = re.fullmatch(r"(?P<major>\d+)(?:\.(?P<minor>\d+))?\.x", kicad_range)
    if range_match is None:
        return f"Unsupported KiCad canary range {kicad_range}"

    actual_major = int(match.group("major"))
    actual_minor = int(match.group("minor"))
    expected_major = int(range_match.group("major"))
    expected_minor = range_match.group("minor")
    if actual_major != expected_major:
        return f"KiCad version output does not match configured range {kicad_range}: {output}"
    if expected_minor is not None and actual_minor != int(expected_minor):
        return f"KiCad version output does not match configured range {kicad_range}: {output}"
    return None


def _assert_version_matches_range(version_result: dict[str, object], kicad_range: str) -> None:
    error = _version_range_error(version_result, kicad_range)
    if error is not None:
        raise RuntimeError(error)


def run_canary(artifacts: Path, kicad_range: str) -> int:
    """Run the KiCad CLI canary plan and write reports and logs to artifacts."""
    artifacts = approved_runtime_path(artifacts)
    compatibility = _read_compatibility_matrix()
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        cli = _resolve_cli()
    except FileNotFoundError as exc:
        results: list[dict[str, object]] = [
            {
                "name": "resolve-cli",
                "fixture": "environment",
                "ok": False,
                "error": str(exc),
            }
        ]
        summary = {
            "kicadRange": kicad_range,
            "kicadCli": None,
            "manufacturingExports": supports_feature_gate(
                compatibility,
                "manufacturingExports",
                kicad_range,
            ),
            "results": results,
            "failingFixtures": ["environment"],
        }
        _write_text(
            artifacts / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        _write_text(artifacts / "failing-fixtures.txt", "environment\n")
        print(str(exc), file=sys.stderr)
        return 1

    steps = _command_plan(artifacts, compatibility, kicad_range)
    results = [_run_step(cli, step, artifacts) for step in steps]
    version = next(result for result in results if result["name"] == "version")
    version["stdout"] = str(artifacts / "logs" / "version.stdout.log")
    version["stderr"] = str(artifacts / "logs" / "version.stderr.log")
    version_error = _version_range_error(version, kicad_range)
    if version_error is not None:
        version["ok"] = False
        version["error"] = version_error

    failing_fixtures = sorted(
        {str(result["fixture"]) for result in results if not bool(result["ok"])}
    )
    summary = {
        "kicadRange": kicad_range,
        "kicadCli": str(cli),
        "manufacturingExports": supports_feature_gate(
            compatibility,
            "manufacturingExports",
            kicad_range,
        ),
        "results": results,
        "failingFixtures": failing_fixtures,
    }
    _write_text(artifacts / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_text(artifacts / "failing-fixtures.txt", "\n".join(failing_fixtures) + "\n")

    if failing_fixtures:
        print(f"KiCad canary failed for fixture(s): {', '.join(failing_fixtures)}", file=sys.stderr)
        return 1
    print(f"KiCad canary passed for {kicad_range}; artifacts written to {artifacts}.")
    return 0


def _write_matrix(include_manual: bool, required_only: bool) -> int:
    matrix = build_canary_matrix(
        _read_compatibility_matrix(),
        include_manual=include_manual,
        required_only=required_only,
    )
    print(json.dumps(matrix, separators=(",", ":")))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    matrix_parser = subcommands.add_parser("matrix", help="Print the GitHub Actions canary matrix.")
    matrix_parser.add_argument(
        "--include-manual",
        action="store_true",
        help="Include compatibility lanes marked manual.",
    )
    matrix_parser.add_argument(
        "--required-only",
        action="store_true",
        help="Only include required lanes for pull-request smoke checks.",
    )

    run_parser = subcommands.add_parser("run", help="Run KiCad CLI canary commands.")
    run_parser.add_argument("--artifacts", type=Path, required=True)
    run_parser.add_argument("--kicad-range", required=True)

    args = parser.parse_args(argv)
    if args.command == "matrix":
        return _write_matrix(args.include_manual, args.required_only)
    if args.command == "run":
        return run_canary(args.artifacts, args.kicad_range)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
