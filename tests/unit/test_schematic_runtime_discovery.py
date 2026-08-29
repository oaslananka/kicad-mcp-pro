# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.types import Tool

from kicad_mcp.server import _filter_ipc_runtime_tools


class _ClosedSchematicState:
    reachable = True
    live_pcb_read = True
    live_pcb_write = True
    live_schematic_read = False
    live_schematic_write = False
    operations: dict[str, object] = {}

    def tool_available(self, _tool_name: str) -> bool:
        return False


def test_file_backed_schematic_tools_remain_visible_when_editor_is_closed() -> None:
    names = [
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
        "sch_reload",
    ]
    tools = [Tool(name=name, inputSchema={}) for name in names]

    visible = {
        tool.name
        for tool in _filter_ipc_runtime_tools(
            tools,
            _ClosedSchematicState(),  # type: ignore[arg-type]
        )
    }

    assert {
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
    }.issubset(visible)
    assert "sch_reload" not in visible


def test_non_ipc_tool_filter_does_not_probe_runtime(monkeypatch) -> None:
    import kicad_mcp.server as server_module

    def unexpected_probe() -> object:
        raise AssertionError("non-IPC discovery must not probe KiCad runtime")

    monkeypatch.setattr(server_module, "get_ipc_capability_state", unexpected_probe)
    tools = [Tool(name="studio_push_context", inputSchema={})]

    assert _filter_ipc_runtime_tools(tools) == tools
