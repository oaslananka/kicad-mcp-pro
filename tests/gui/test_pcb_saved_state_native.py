"""Opt-in Linux GUI save acceptance with a private IPC/display/mount namespace."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import statistics
import struct
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path

import pytest

from scripts.benchmark_kicad_large_demo import (
    SYSTEM_PYTHON,
    _trusted_system_python,
    nearest_rank_p95,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/native_hierarchy"
PRIVATE = Path("/mnt")  # Existing mount point; only the disposable fixture is bound here.
_NATIVE_BOARD = """
import pcbnew, sys
board = pcbnew.BOARD()
for reference, x in (("R1", 10), ("R2", 30)):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(reference)
    footprint.SetValue("10k")
    footprint.SetPosition(pcbnew.VECTOR2I(x * 1000000, 20000000))
    board.Add(footprint)
assert pcbnew.SaveBoard(sys.argv[1], board)
"""


def _prepare_project(scratch: Path) -> None:
    project = scratch / "project"
    project.mkdir()
    profile = scratch / "home/.config/kicad/10.0"
    profile.mkdir(parents=True)
    (scratch / "runtime").mkdir(mode=0o700)
    for name in ("main.kicad_sch", "child.kicad_sch"):
        shutil.copyfile(FIXTURE / name, project / name)
    (project / "main.kicad_pro").write_text("{}\n", encoding="utf-8")
    for name in ("sym-lib-table", "fp-lib-table"):
        shutil.copyfile(Path("/usr/share/kicad/template") / name, profile / name)
    (profile / "design-block-lib-table").write_text(
        "(design_block_lib_table (version 7))\n", encoding="utf-8"
    )
    (profile / "kicad_common.json").write_text(
        json.dumps(
            {
                "api": {"enable_server": True},
                "graphics": {"canvas_type": 2},
                "do_not_show_again": {
                    "update_check_prompt": True,
                    "data_collection_prompt": True,
                },
            }
        ),
        encoding="utf-8",
    )
    _trusted_system_python(Path(SYSTEM_PYTHON))
    subprocess.run(  # nosec B603
        [
            "/usr/bin/python3",
            "-I",
            "-c",
            _NATIVE_BOARD,
            str(project / "main.kicad_pcb"),
        ],
        check=True,
        timeout=20,
    )


def _system_temp_root() -> Path:
    """Use the standard Linux temp root required by KiCad's native IPC endpoint."""
    root = Path(tempfile.gettempdir()).resolve(strict=True)
    if root.parent != Path("/") or root.name != "tmp":
        raise RuntimeError("native GUI acceptance requires the standard Linux temporary root")
    return root


def _private_ipc_endpoint() -> Path:
    return _system_temp_root() / "kicad" / "api.sock"


def _require_private_tmpfs() -> None:
    """Require a fresh private tmpfs mount before launching the native editor."""
    root = _system_temp_root()
    mounts = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    for entry in mounts:
        before, separator, after = entry.partition(" - ")
        if separator and before.split()[4] == str(root) and after.split()[0] == "tmpfs":
            if os.path.ismount(root):
                return
    raise RuntimeError("native GUI acceptance requires an isolated temporary filesystem")


def _private_environment() -> dict[str, str]:
    root = PRIVATE / "project"
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": str(PRIVATE / "home"),
        "XDG_CONFIG_HOME": str(PRIVATE / "home/.config"),
        "XDG_CACHE_HOME": str(PRIVATE / "home/.cache"),
        "XDG_RUNTIME_DIR": str(PRIVATE / "runtime"),
        "KICAD_CONFIG_HOME": str(PRIVATE / "home/.config/kicad"),
        "KICAD_API_SOCKET": f"ipc://{_private_ipc_endpoint()}",
        "TMPDIR": str(_system_temp_root()),
        "KICAD_MCP_PROJECT_DIR": str(root),
        "KICAD_MCP_PROJECT_FILE": str(root / "main.kicad_pro"),
        "KICAD_MCP_PCB_FILE": str(root / "main.kicad_pcb"),
        "KICAD_MCP_SCH_FILE": str(root / "main.kicad_sch"),
        "KICAD_MCP_WORKSPACE_ROOT": str(root),
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_ENABLE_PERSISTENT_PCB_STATE": "true",
        "KICAD_MCP_TRANSPORT": "stdio",
        "KICAD_MCP_KICAD_CLI": "/usr/bin/kicad-cli",
        "KICAD_MCP_IPC_CONNECTION_TIMEOUT": "2",
        "KICAD_MCP_RETRIES": "0",
        "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "KICAD_MCP_PRIVATE_SAVE_WORKER": "1",
    }


@pytest.mark.gui
@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("KICAD_MCP_NATIVE_PCB_SAVE_GUI") != "1",
    reason="explicit Linux private GUI opt-in",
)
def test_native_gui_saved_pcb_graph(tmp_path: Path) -> None:
    # Refuse to use any host GUI/socket, even if the caller has a live editor.
    temp_root = _system_temp_root()
    assert not ROOT.is_relative_to(temp_root)
    assert not Path(sys.executable).is_relative_to(temp_root)
    for executable in ("/usr/bin/bwrap", "/usr/bin/xvfb-run", "/usr/bin/pcbnew"):
        assert Path(executable).is_file()
    originals = {
        name: sha256_file(FIXTURE / name) for name in ("main.kicad_sch", "child.kicad_sch")
    }
    _prepare_project(tmp_path)
    result = subprocess.run(  # nosec B603
        [
            "/usr/bin/bwrap",
            "--die-with-parent",
            "--unshare-pid",
            "--unshare-net",
            "--ro-bind",
            "/",
            "/",
            "--dev-bind",
            "/dev",
            "/dev",
            "--proc",
            "/proc",
            "--bind",
            str(tmp_path),
            str(PRIVATE),
            "--tmpfs",
            str(temp_root),
            "--chdir",
            str(ROOT),
            "--",
            "/usr/bin/xvfb-run",
            "-a",
            "-s",
            "-screen 0 1440x900x24",
            sys.executable,
            str(Path(__file__).resolve()),
        ],
        env=_private_environment(),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    lines = [
        line for line in result.stdout.splitlines() if line.startswith("NATIVE_GUI_PCB_STATE:")
    ]
    assert len(lines) == 1
    evidence = json.loads(lines[0].split(":", 1)[1])
    assert evidence["work_units"] == [1, 1, 1]
    assert evidence["reopened"] is True
    assert all(sha256_file(FIXTURE / name) == digest for name, digest in originals.items())
    print(lines[0], flush=True)


def _wait_private_board(process: subprocess.Popen) -> None:
    from kipy.kicad import KiCad

    endpoint = _private_ipc_endpoint()
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("private editor exited")
        if endpoint.is_socket():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    client.connect(str(endpoint))
                    pid, uid, _ = struct.unpack(
                        "3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    )
                if pid != process.pid or uid != os.getuid():
                    raise RuntimeError("private IPC peer mismatch")
            except OSError:
                time.sleep(0.5)
                continue
            try:
                board = KiCad(socket_path=f"ipc://{endpoint}", timeout_ms=1500).get_board()
                if (
                    board.name == "main.kicad_pcb"
                    and Path(board.get_project().path) == PRIVATE / "project"
                ):
                    return
            except Exception as exc:  # noqa: BLE001 - bounded readiness probe only
                print("private IPC not ready:", type(exc).__name__, flush=True)
        time.sleep(0.5)
    raise RuntimeError("private editor IPC not ready; no mutation attempted")


async def _run_cycles() -> None:
    from kicad_mcp.server import build_server
    from tests.conftest import call_tool_text

    sidecar = PRIVATE / "project/.kicad-mcp-cache/physical.json"
    server = build_server("full")

    async def call(name: str, arguments: dict[str, object]) -> str:
        return await call_tool_text(server, name, arguments)

    assert not sidecar.exists()
    initial_sha = sha256_file(PRIVATE / "project/main.kicad_pcb")
    start = time.perf_counter()
    assert "rebuilt" in await call("pcb_save", {})
    cold_ms = (time.perf_counter() - start) * 1000
    doc = json.loads(sidecar.read_text())
    physical = [item for item in doc["graph"]["entities"] if item["kind"] == "pcb_footprint"]
    assert len(physical) == 2
    target = next(item for item in physical if item["attributes"]["reference"] == "R1")
    uuid = target["native_links"][0]["uuid"]
    units = []
    times = []
    for generation, x in enumerate((11, 12, 13), start=1):
        before = sidecar.read_bytes()
        assert "verified rotation" in await call(
            "pcb_move_footprint", {"reference": uuid, "x_mm": x, "y_mm": 20}
        )
        assert sidecar.read_bytes() == before
        start = time.perf_counter()
        result = await call("pcb_save", {})
        times.append(round((time.perf_counter() - start) * 1000, 3))
        assert "1 updated" in result, result
        doc = json.loads(sidecar.read_text())
        assert doc["generation"] == generation
        units.append(doc["journal"][-1]["work_units"])
        updated = next(
            item for item in doc["graph"]["entities"] if item["entity_id"] == target["entity_id"]
        )
        assert updated["attributes"]["x_mm"] == x
    saved = sidecar.read_bytes()
    # A fresh server must independently verify the sidecar against native files.
    start = time.perf_counter()
    assert "reopened" in await call_tool_text(build_server("full"), "pcb_save", {})
    reopen_ms = (time.perf_counter() - start) * 1000
    assert sidecar.read_bytes() == saved
    # Independent native file read-back, not the graph projection.
    native = subprocess.run(  # nosec B603
        [
            "/usr/bin/python3",  # Verified by the parent; host filesystem is read-only in bwrap.
            "-I",
            "-c",
            "import pcbnew,sys,json; b=pcbnew.LoadBoard(sys.argv[1]); "
            "print(json.dumps(sorted((str(f.m_Uuid.AsString()),f.GetReference(),"
            "int(f.GetPosition().x),int(f.GetPosition().y)) for f in b.GetFootprints())))",
            str(PRIVATE / "project/main.kicad_pcb"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    actual = json.loads(native.stdout.strip().splitlines()[-1])
    assert actual == sorted(
        [
            item["native_links"][0]["uuid"],
            item["attributes"]["reference"],
            round(item["attributes"]["x_mm"] * 1_000_000),
            round(item["attributes"]["y_mm"] * 1_000_000),
        ]
        for item in doc["graph"]["entities"]
        if item["kind"] == "pcb_footprint"
    )
    import resource

    from kicad_mcp.tools.export_support import _run_cli

    version_code, version, _ = _run_cli("version", timeout=15)
    assert version_code == 0
    print(
        "NATIVE_GUI_PCB_STATE:"
        + json.dumps(
            {
                "work_units": units,
                "save_ms": times,
                "save_p50_ms": statistics.median(times),
                "save_p95_ms": nearest_rank_p95(times),
                "cold_save_ms": round(cold_ms, 3),
                "reopen_save_ms": round(reopen_ms, 3),
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "kicad_version": version.strip(),
                "generated_initial_pcb_sha256": initial_sha,
                "native_reload_parity": True,
                "reopened": True,
                "unsaved_sidecar_unchanged": True,
                "footprints": 2,
            }
        ),
        flush=True,
    )


def _private_worker() -> None:
    if os.environ.get("KICAD_MCP_PRIVATE_SAVE_WORKER") != "1" or not PRIVATE.is_dir():
        raise RuntimeError("private worker must use the isolated test launcher")
    # A host invocation must not be able to select a running editor.
    _require_private_tmpfs()
    if _private_ipc_endpoint().exists():
        raise RuntimeError("private socket is not initially empty")
    with (PRIVATE / "editor.log").open("w") as log:
        process = subprocess.Popen(  # nosec B603
            ["/usr/bin/pcbnew", str(PRIVATE / "project/main.kicad_pcb")],
            cwd=PRIVATE / "project",
            stdout=log,
            stderr=log,
        )
        try:
            _wait_private_board(process)
            asyncio.run(_run_cycles())
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    _private_worker()
