"""Opt-in signed Cloud / real native KiCad DRC acceptance worker.

Consumes a test-only post-handshake frame; device, session and source folder
are fixed independently of the untrusted Cloud wire payload.
Never reads or writes a user-selected KiCad project.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    device, project, session, request_json = sys.argv[1:]
    fixture = (
        Path(__file__).resolve().parents[2] / "packages/kicad-fixtures/fixtures/clean-led-kicad10"
    )
    files = tuple(p for p in fixture.iterdir() if p.is_file())
    before = {p.name: hashlib.sha256(p.read_bytes()).digest() for p in files}
    assert "clean-led-kicad10.kicad_pcb" in before
    with tempfile.TemporaryDirectory(prefix="kicad-managed-drc-accept-") as temp:
        destination = Path(temp)
        for item in files:
            shutil.copyfile(item, destination / item.name)
        now_ms = time.time_ns() // 1_000_000
        dispatcher = LocalReadDispatch(
            verified=VerifiedLocalBinding(
                device, project, frozenset({"run_drc"}), session, now_ms + 120_000
            ),
            operator_project=OperatorProject(device, project, destination, "clean-led-kicad10"),
            current_authorization=lambda: True,
            max_reads=1,
            native_drc=True,
            managed_native_drc=True,
        )
        frame = request_json.encode("utf-8")
        try:
            response = dispatcher.read(frame, sequence=1)
            dispatcher.assert_delivery_authorized(frame, device_id=device, session_id=session)
        finally:
            dispatcher.close()
        assert set(response) == {"kind", "version", "requestId", "projectId", "operation", "counts"}
        assert response["kind"] == "connector.local_drc_preview"
        assert response["operation"] == "run_drc"
        assert set(response["counts"]) == {"violations", "unconnectedItems"}
        assert all(type(n) is int and n >= 0 for n in response["counts"].values())
        assert {p.name: hashlib.sha256(p.read_bytes()).digest() for p in files} == before
        assert {
            p.name: hashlib.sha256(p.read_bytes()).digest() for p in destination.iterdir()
        } == before
        print(json.dumps(response, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
