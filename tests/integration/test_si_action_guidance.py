"""Exercise SI next actions against registered MCP tools on a disposable USB board."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mcp.types import CallToolResult

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from kicad_mcp.tools.pcb import _parse_stackup_specs_from_board_text
from tests.conftest import tool_text

USB_BOARD = """(kicad_pcb
  (version 20240108)
  (generator "si-guidance-test")
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 1 "USB_DP")
  (net 2 "USB_DM")
  (net 3 "GND")
  (segment (start 10 10) (end 15 10) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 10 11) (end 15 11) (width 0.2) (layer "F.Cu") (net 2))
  (gr_rect (start 0 0) (end 40 30) (stroke (width 0.1) (type solid))
    (fill none) (layer "Edge.Cuts"))
)
"""


def _actions(report: str) -> list[dict]:
    return [json.loads(x) for x in re.findall(r"```json\n(.*?)\n```", report, re.S)]


def _hashes(files: tuple[Path, ...]) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


@pytest.mark.anyio
@pytest.mark.parametrize("native", [False, True], ids=["registered", "native"])
async def test_usb_guidance_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_cli: Path, native: bool
) -> None:
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(fake_cli))
    if native:
        configured = os.environ.get("KICAD_NATIVE_SI_CLI")
        if not configured:
            pytest.skip("Explicit native KiCad CLI required")
        cli = Path(configured).resolve(strict=True)
        assert cli.is_file()
        monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(cli))
    project = tmp_path / "project"
    project.mkdir()
    board = project / "usb.kicad_pcb"
    board.write_text(USB_BOARD, encoding="utf-8")
    pro = project / "usb.kicad_pro"
    pro.write_text('{"meta":{"filename":"usb.kicad_pro","version":1}}', encoding="utf-8")
    dru = project / "usb.kicad_dru"
    dru.write_text("(version 1)\n", encoding="utf-8")
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("KICAD_DOCUMENTS_HOME", str(tmp_path / "documents"))
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project))
    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(project))
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    monkeypatch.setenv("KICAD_MCP_KICAD_SOCKET_PATH", str(tmp_path / "unbound.sock"))
    # The opt-in native test exposes the registered file-backed tool contract
    # in an isolated process; ordinary runtime discovery remains unchanged.
    monkeypatch.setenv("KICAD_MCP_FILTER_RUNTIME_TOOLS", "false" if native else "true")
    reset_config()
    if native:
        version, stdout, stderr = _run_cli("version")
        assert version == 0, stderr
        assert stdout.startswith("10."), stdout
    server = build_server("full")
    schemas = {tool.name: tool.input_schema for tool in await server.list_tools()}
    files = (board, pro, dru)
    before = _hashes(files)
    interfaces = [
        {"kind": "usb2", "differential": True, "impedance_target_ohm": 90, "net_prefix": "USB_"}
    ]

    async def call(name: str, arguments: dict) -> str:
        Draft202012Validator(schemas[name]).validate(arguments)
        result = await server.call_tool(name, arguments)
        assert isinstance(result, CallToolResult)
        assert not result.is_error, tool_text(result)
        return tool_text(result)

    synthesis = await call("si_synthesize_stackup_for_interfaces", {"interfaces": interfaces})
    assert "Layer count: **4**" in synthesis
    assert "not verified physical impedance" in synthesis
    stackup, bind = _actions(synthesis)
    assert stackup["tool"] == "pcb_set_stackup"
    assert stackup["arguments"]["allow_open_board"] is False
    assert bind["tool"] == "si_bind_interfaces_to_net_classes"
    assert bind["arguments"]["dry_run"] is True
    if native:
        Draft202012Validator(schemas[stackup["tool"]]).validate(stackup["arguments"])
    else:
        assert stackup["tool"] not in schemas
        assert "tools/list" in synthesis
        assert "if absent" in synthesis.casefold()
        registered = {tool.name: tool.parameters for tool in server._tool_manager.list_tools()}
        Draft202012Validator(registered[stackup["tool"]]).validate(stackup["arguments"])
    plan = await call(bind["tool"], bind["arguments"])
    inspect, apply_rules = _actions(plan)
    assert inspect["tool"] == "pcb_get_nets"
    nets = await call(inspect["tool"], inspect["arguments"])
    assert "USB_DP" in nets and "USB_DM" in nets
    assert "exact net" in plan.casefold()
    assert "does not assign" in plan.casefold()
    assert apply_rules["tool"] == "si_bind_interfaces_to_net_classes"
    assert apply_rules["arguments"]["dry_run"] is False
    Draft202012Validator(schemas[apply_rules["tool"]]).validate(apply_rules["arguments"])
    assert _hashes(files) == before
    if not native:
        return
    applied = await call(stackup["tool"], stackup["arguments"])
    assert "Copper layers: 4" in applied, applied
    code, stdout, stderr = _run_cli("pcb", "upgrade", "--force", str(board))
    assert code == 0, stderr or stdout
    parsed = _parse_stackup_specs_from_board_text(board.read_text(encoding="utf-8"))
    assert parsed is not None
    assert [x.name for x in parsed if x.name.endswith("_Cu")] == [
        "F_Cu",
        "In1_Cu",
        "In2_Cu",
        "B_Cu",
    ]
    assert sum(x.thickness_mm for x in parsed) == pytest.approx(1.6, abs=0.001)
    reread = await call("pcb_get_stackup", {})
    assert "In1" in reread and "In2" in reread
    assert _hashes((pro, dru)) == {name: before[name] for name in (pro.name, dru.name)}
    board_before_rules = _hashes((board, pro))
    applied_rules = await call(apply_rules["tool"], apply_rules["arguments"])
    assert "**Applied** 1 net class rule(s)" in applied_rules
    assert "does not assign" in applied_rules
    assert "A.NetClass == 'USB2'" in dru.read_text(encoding="utf-8")
    assert _hashes((board, pro)) == board_before_rules
