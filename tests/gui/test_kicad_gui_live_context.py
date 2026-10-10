"""OASLANA-44 real KiCad GUI smoke coverage for GitHub issue #35.

The suite is skipped unless ``KICAD_MCP_ENABLE_GUI_SMOKE=1`` is set. It is
intended for scheduled/manual CI where a real KiCad GUI can be launched, not for
the normal PR path.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from kicad_mcp.connection import reset_connection
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

pytestmark = [pytest.mark.anyio, pytest.mark.gui, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_SMOKE_FIXTURE_ID = "clean-led-kicad10"
FIXTURE_ROOT = REPO_ROOT / "packages" / "kicad-fixtures" / "fixtures" / GUI_SMOKE_FIXTURE_ID
SMOKE_TOOLS = (
    "pcb_get_board_summary",
    "pcb_get_tracks",
    "pcb_get_footprints",
    "pcb_get_nets",
)
LIVE_TIMEOUT_SECONDS = 150


@dataclass(frozen=True)
class KiCadExecutables:
    """Discovered KiCad GUI executables used by the smoke suite."""

    project_manager: Path | None
    pcb_editor: Path | None
    schematic_editor: Path | None
    searched: tuple[str, ...]


@dataclass
class ManagedProcess:
    """A spawned KiCad GUI process plus its captured output."""

    name: str
    process: subprocess.Popen[str]
    log_dir: Path


def _require_enabled() -> None:
    if os.environ.get("KICAD_MCP_ENABLE_GUI_SMOKE") != "1":
        pytest.skip("Set KICAD_MCP_ENABLE_GUI_SMOKE=1 to run real KiCad GUI smoke tests.")


def _required() -> bool:
    return os.environ.get("KICAD_MCP_GUI_SMOKE_REQUIRED") == "1"


def _launch_auxiliary_editors() -> bool:
    """Keep the Windows IPC probe single-editor when explicitly requested."""
    return os.environ.get("KICAD_GUI_SMOKE_PCB_ONLY") != "1"


def _artifact_root(tmp_path: Path) -> Path:
    raw_path = os.environ.get("KICAD_GUI_SMOKE_ARTIFACTS")
    root = Path(raw_path).expanduser() if raw_path else tmp_path / "kicad-gui-smoke-artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _executables_payload(executables: KiCadExecutables) -> dict[str, object]:
    return {
        "project_manager": str(executables.project_manager)
        if executables.project_manager is not None
        else None,
        "pcb_editor": str(executables.pcb_editor) if executables.pcb_editor is not None else None,
        "schematic_editor": str(executables.schematic_editor)
        if executables.schematic_editor is not None
        else None,
        "searched": list(executables.searched),
    }


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    destination = tmp_path / name
    shutil.copytree(FIXTURE_ROOT, destination)
    return destination


def _configure_project(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> dict[str, str]:
    stem = GUI_SMOKE_FIXTURE_ID
    env = {
        "KICAD_MCP_PROJECT_DIR": str(project_dir),
        "KICAD_MCP_PROJECT_FILE": str(project_dir / f"{stem}.kicad_pro"),
        "KICAD_MCP_PCB_FILE": str(project_dir / f"{stem}.kicad_pcb"),
        "KICAD_MCP_SCH_FILE": str(project_dir / f"{stem}.kicad_sch"),
        "KICAD_MCP_OUTPUT_DIR": str(project_dir / "mcp-output"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def _candidate_names(names: tuple[str, ...]) -> tuple[str, ...]:
    if platform.system() != "Windows":
        return names
    expanded: list[str] = []
    for name in names:
        expanded.append(name)
        if not name.lower().endswith(".exe"):
            expanded.append(f"{name}.exe")
    return tuple(expanded)


def _existing_file(path: Path) -> Path | None:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_file():
        return expanded
    return None


def _discover_one(
    env_names: tuple[str, ...],
    binary_names: tuple[str, ...],
    bin_dirs: tuple[Path, ...],
    searched: list[str],
) -> Path | None:
    for env_name in env_names:
        raw = os.environ.get(env_name, "").strip()
        if raw:
            searched.append(f"{env_name}={raw}")
            candidate = _existing_file(Path(raw))
            if candidate is not None:
                return candidate

    for bin_dir in bin_dirs:
        for binary_name in _candidate_names(binary_names):
            candidate_path = bin_dir / binary_name
            searched.append(str(candidate_path))
            candidate = _existing_file(candidate_path)
            if candidate is not None:
                return candidate

    for binary_name in _candidate_names(binary_names):
        discovered = shutil.which(binary_name)
        searched.append(f"PATH:{binary_name}")
        if discovered:
            return Path(discovered)
    return None


def _discover_executables() -> KiCadExecutables:
    searched: list[str] = []
    bin_dirs: list[Path] = []
    for env_name in ("KICAD_GUI_SMOKE_BIN_DIR", "KICAD_INSTALL_BIN_DIR"):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            bin_dirs.append(Path(raw).expanduser())
            searched.append(f"{env_name}={raw}")

    for env_name in ("KICAD_GUI_SMOKE_KICAD_CLI", "KICAD_MCP_KICAD_CLI", "KICAD_CLI_PATH"):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            bin_dirs.append(Path(raw).expanduser().parent)
            searched.append(f"{env_name}={raw}")

    project_manager = _discover_one(
        ("KICAD_GUI_PATH", "KICAD_PROJECT_MANAGER_PATH"),
        ("kicad",),
        tuple(bin_dirs),
        searched,
    )
    pcb_editor = _discover_one(
        ("KICAD_PCBNEW_PATH", "KICAD_PCB_EDITOR_PATH"),
        ("pcbnew",),
        tuple(bin_dirs),
        searched,
    )
    schematic_editor = _discover_one(
        ("KICAD_EESCHEMA_PATH", "KICAD_SCHEMATIC_EDITOR_PATH"),
        ("eeschema",),
        tuple(bin_dirs),
        searched,
    )
    return KiCadExecutables(
        project_manager=project_manager,
        pcb_editor=pcb_editor,
        schematic_editor=schematic_editor,
        searched=tuple(searched),
    )


def _launch_process(
    name: str,
    executable: Path,
    target: Path,
    log_dir: Path,
) -> ManagedProcess:
    log_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(executable), str(target)],
        cwd=target.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    (log_dir / f"{name}-pid.txt").write_text(str(process.pid), encoding="utf-8")
    return ManagedProcess(name=name, process=process, log_dir=log_dir)


def _stop_processes(processes: list[ManagedProcess]) -> None:
    for managed in reversed(processes):
        _stop_process(managed)


def _stop_process(managed: ManagedProcess) -> None:
    process = managed.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
    (managed.log_dir / f"{managed.name}-stdout.log").write_text(stdout or "", encoding="utf-8")
    (managed.log_dir / f"{managed.name}-stderr.log").write_text(stderr or "", encoding="utf-8")
    (managed.log_dir / f"{managed.name}-returncode.txt").write_text(
        str(process.returncode),
        encoding="utf-8",
    )


def _classify_tool_output(text: str) -> str:
    if "- Source: live-gui" in text:
        return "live-gui"
    if "file-backed fallback" in text or "- Source: file-backed" in text:
        return "file-backed"
    if "Error executing tool" in text:
        return "error"
    return "other"


def _capture_screenshot(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            destination.with_suffix(".txt").write_text(
                "Screenshot unavailable: PowerShell was not found.",
                encoding="utf-8",
            )
            return
        script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save('{destination}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    else:
        import_binary = shutil.which("import")
        if import_binary is None:
            destination.with_suffix(".txt").write_text(
                "Screenshot unavailable: ImageMagick import was not found.",
                encoding="utf-8",
            )
            return
        result = subprocess.run(
            [import_binary, "-window", "root", str(destination)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    if result.returncode != 0:
        destination.with_suffix(".txt").write_text(
            f"Screenshot command failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            encoding="utf-8",
        )


async def _call_smoke_tools(server: object) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for tool_name in SMOKE_TOOLS:
        text = await call_tool_text(server, tool_name, {})
        outputs[tool_name] = {
            "classification": _classify_tool_output(text),
            "text": text,
        }
    return outputs


def _editor_readiness_snapshot(editor: ManagedProcess) -> dict[str, object]:
    """Capture ONLY bounded lifecycle/window metadata, never titles or host paths."""
    exit_code = editor.process.poll()
    result: dict[str, object] = {
        "processRunning": exit_code is None,
        "processExitCode": exit_code,
        "windowCount": 0,
        "visibleWindowCount": 0,
        "enabledVisibleWindowCount": 0,
        "disabledVisibleWindowCount": 0,
        "standardDialogWindowCount": 0,
    }
    if platform.system() != "Windows":
        return result

    # A healthy socket can return KiCad AS_NOT_READY if its GUI frame never
    # finishes initializing. Inspect *only* window counts for the launched
    # PCB Editor PID; do not record usernames, window titles or screenshots.
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    enum_callback_type = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    user32.EnumWindows.argtypes = [enum_callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    counts = {
        "windowCount": 0,
        "visibleWindowCount": 0,
        "enabledVisibleWindowCount": 0,
        "disabledVisibleWindowCount": 0,
        "standardDialogWindowCount": 0,
    }

    def visit(hwnd: int, _unused: int) -> bool:
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != editor.process.pid:
            return True
        counts["windowCount"] += 1
        if user32.IsWindowVisible(hwnd):
            counts["visibleWindowCount"] += 1
            if user32.IsWindowEnabled(hwnd):
                counts["enabledVisibleWindowCount"] += 1
            else:
                counts["disabledVisibleWindowCount"] += 1
        window_class = ctypes.create_unicode_buffer(128)
        if user32.GetClassNameW(hwnd, window_class, len(window_class)):
            if window_class.value == "#32770":
                counts["standardDialogWindowCount"] += 1
        return True

    callback = enum_callback_type(visit)
    if not user32.EnumWindows(callback, 0):
        # Fail closed on diagnostics failure; do not invent window counts.
        result["windowEnumerationFailed"] = True
    else:
        result.update(counts)
    return result


async def _wait_for_live_context(
    server: object, artifacts: Path, editor: ManagedProcess | None = None
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + LIVE_TIMEOUT_SECONDS
    last_outputs: dict[str, dict[str, str]] = {}
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if editor is not None and editor.process.poll() is not None:
            _write_json(artifacts / "editor-readiness.json", _editor_readiness_snapshot(editor))
            raise AssertionError("PCB Editor exited before live GUI IPC became ready.")
        last_outputs = await _call_smoke_tools(server)
        _write_json(
            artifacts / "live-context-attempts" / f"attempt-{attempt:03d}.json",
            last_outputs,
        )
        if all(value["classification"] == "live-gui" for value in last_outputs.values()):
            return last_outputs
        await asyncio.sleep(3)
    _write_json(artifacts / "live-context-timeout.json", last_outputs)
    if editor is not None:
        _write_json(artifacts / "editor-readiness.json", _editor_readiness_snapshot(editor))
    raise AssertionError("Timed out waiting for every OASLANA-44 read tool to use live-gui.")


async def test_gui_closed_reports_structured_file_backed_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GUI closed/unavailable must be distinguishable from valid file-backed fallback."""
    _require_enabled()
    project_dir = _copy_fixture(tmp_path, "gui-closed")
    env = _configure_project(monkeypatch, project_dir)
    monkeypatch.setenv("KICAD_API_SOCKET", str(tmp_path / "closed-gui.sock"))
    artifacts = _artifact_root(tmp_path) / "gui-closed"
    artifacts.mkdir(parents=True, exist_ok=True)

    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project_dir)})
    outputs = await _call_smoke_tools(server)
    _write_json(
        artifacts / "fallback-summary.json",
        {"env": env, "outputs": outputs, "issue": "OASLANA-44 / GitHub issue #35"},
    )

    for tool_name, result in outputs.items():
        assert result["classification"] == "file-backed", result["text"]
        assert "Diagnostics:" in result["text"], tool_name
        assert "IPC endpoint:" in result["text"], tool_name
        assert "Fallback status: using file-backed .kicad_pcb parser" in result["text"], tool_name


async def test_open_pcb_editor_uses_live_board_context_and_project_switches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launch real KiCad editors, verify live PCB tools, then guard project switching."""
    _require_enabled()
    artifacts = _artifact_root(tmp_path) / "open-editors"
    processes: list[ManagedProcess] = []
    executables = _discover_executables()
    _write_json(artifacts / "discovery.json", _executables_payload(executables))

    if executables.pcb_editor is None:
        message = "KiCad PCB Editor executable was not found for OASLANA-44 live GUI smoke."
        if _required():
            pytest.fail(f"{message} Searched: {executables.searched}")
        pytest.skip(message)

    first_project = _copy_fixture(tmp_path, "first-project")
    env = _configure_project(monkeypatch, first_project)
    server = build_server("pcb")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(first_project)})

    try:
        if _launch_auxiliary_editors() and executables.project_manager is not None:
            processes.append(
                _launch_process(
                    "project-manager",
                    executables.project_manager,
                    Path(env["KICAD_MCP_PROJECT_FILE"]),
                    artifacts / "processes",
                )
            )
        if _launch_auxiliary_editors() and executables.schematic_editor is not None:
            processes.append(
                _launch_process(
                    "schematic-editor",
                    executables.schematic_editor,
                    Path(env["KICAD_MCP_SCH_FILE"]),
                    artifacts / "processes",
                )
            )
        first_pcb = _launch_process(
            "pcb-editor-first-project",
            executables.pcb_editor,
            Path(env["KICAD_MCP_PCB_FILE"]),
            artifacts / "processes",
        )
        processes.append(first_pcb)

        live_outputs = await _wait_for_live_context(server, artifacts, first_pcb)
        _write_json(artifacts / "live-context-summary.json", live_outputs)

        tracks = live_outputs["pcb_get_tracks"]["text"]
        footprints = live_outputs["pcb_get_footprints"]["text"]
        nets = live_outputs["pcb_get_nets"]["text"]
        assert "Tracks (" in tracks and "LED_A" in tracks
        assert "R1" in footprints and "LED1" in footprints
        assert "LED_A" in nets and "GND" in nets

        _stop_process(first_pcb)
        processes.remove(first_pcb)
        reset_connection()

        second_project = _copy_fixture(tmp_path, "second-project")
        second_board = second_project / "clean-led-kicad10.kicad_pcb"
        second_board.write_text(
            second_board.read_text(encoding="utf-8")
            .replace("LED_A", "SWITCHED_PROJECT_NET")
            .replace("GND", "SWITCHED_PROJECT_GND"),
            encoding="utf-8",
        )
        second_env = _configure_project(monkeypatch, second_project)
        await call_tool_text(server, "kicad_set_project", {"project_dir": str(second_project)})
        second_pcb = _launch_process(
            "pcb-editor-second-project",
            executables.pcb_editor,
            Path(second_env["KICAD_MCP_PCB_FILE"]),
            artifacts / "processes",
        )
        processes.append(second_pcb)

        switched_outputs = await _wait_for_live_context(
            server, artifacts / "project-switch", second_pcb
        )
        switched_nets = switched_outputs["pcb_get_nets"]["text"]
        _write_json(artifacts / "project-switch-summary.json", switched_outputs)

        assert "SWITCHED_PROJECT_NET" in switched_nets
        assert "SWITCHED_PROJECT_GND" in switched_nets
    except Exception:
        _capture_screenshot(artifacts / "failure-screenshot.png")
        raise
    finally:
        _stop_processes(processes)
