"""User-visible stackup resolution contract through the real MCP HTTP transport."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kicad_mcp.config import get_config
from kicad_mcp.tools import pcb
from kicad_mcp.utils.sexpr import iter_root_children
from tests.conftest import tool_text
from tests.integration.test_mcp_native_v2_protocol import (
    _configure_native_v2_server,
    _running_http_server,
)
from tests.unit.test_pcb_keepout_layer_intent import (
    ALL_ID,
    FIELD,
    ROOT_ID,
    _board,
    _footprint,
    _layers,
    _rule,
    _stackup,
)

SECOND_ID = "44444444-4444-4444-8444-444444444444"


def _masks(content: str) -> dict[str, set[str]]:
    result = {}
    for name, footprint in iter_root_children(content):
        if name != "footprint":
            continue
        children = list(iter_root_children(footprint))
        identity = next(value.split('"')[1] for key, value in children if key == "uuid")
        zone = next(value for key, value in children if key == "zone")
        result[identity] = _layers(zone)
    return result


@pytest.mark.asyncio
async def test_ambiguous_legacy_rules_require_independent_explicit_decisions(
    sample_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two instances share a library rule UUID but have distinct footprint UUIDs.
    rule = _rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna")
    first = _footprint(rule)
    second = _footprint(rule, root_id=SECOND_ID).replace('"U1"', '"U2"', 1)
    board = sample_project / "demo.kicad_pcb"
    board.write_text(_board(first + second), encoding="utf-8")
    state_path = sample_project / "output/stackup_profile.json"
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text("[]", encoding="utf-8")
    board_before = board.read_bytes()
    state_before = state_path.read_bytes()
    monkeypatch.setattr(pcb, "_board_is_open", lambda: False)
    get_config().filter_runtime_tools = False
    server = _configure_native_v2_server(sample_project, profile="pcb_only")
    first_key = f"{ROOT_ID}/{ALL_ID}"
    second_key = f"{SECOND_ID}/{ALL_ID}"
    layers = [layer.model_dump() for layer in _stackup(4)]
    with _running_http_server(server.streamable_http_app()) as url:
        async with streamable_http_client(url + "/mcp") as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                refused = await session.call_tool("pcb_set_stackup", {"layers": layers})
                assert refused.is_error
                assert "Ambiguous copper keepout intent" in tool_text(refused)
                assert first_key in tool_text(refused)
                assert board.read_bytes() == board_before
                assert state_path.read_bytes() == state_before

                # Resolving only one does not partially mutate the board.
                partial = await session.call_tool(
                    "pcb_set_stackup",
                    {"layers": layers, "keepout_layer_intents": {first_key: "all_copper"}},
                )
                assert partial.is_error
                assert second_key in tool_text(partial)
                assert board.read_bytes() == board_before
                assert state_path.read_bytes() == state_before

                decisions = {first_key: "all_copper", second_key: "fixed_layers"}
                unknown = await session.call_tool(
                    "pcb_set_stackup",
                    {
                        "layers": layers,
                        "keepout_layer_intents": {**decisions, "unknown": "fixed_layers"},
                    },
                )
                assert unknown.is_error
                assert "Unknown footprint/rule identity" in tool_text(unknown)
                assert board.read_bytes() == board_before
                assert state_path.read_bytes() == state_before

                accepted = await session.call_tool(
                    "pcb_set_stackup", {"layers": layers, "keepout_layer_intents": decisions}
                )
                assert not accepted.is_error
                assert "Configured stackup" in tool_text(accepted)
                saved = board.read_text(encoding="utf-8")
                assert saved.count(f'(property "{FIELD}"') == 2
                assert _masks(saved) == {
                    ROOT_ID: {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"},
                    SECOND_ID: {"F.Cu", "B.Cu"},
                }
                assert state_path.read_bytes() != state_before

                grown = await session.call_tool(
                    "pcb_set_stackup",
                    {"layers": [layer.model_dump() for layer in _stackup(6)]},
                )
                assert not grown.is_error
                assert _masks(board.read_text(encoding="utf-8")) == {
                    ROOT_ID: {"F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"},
                    SECOND_ID: {"F.Cu", "B.Cu"},
                }
