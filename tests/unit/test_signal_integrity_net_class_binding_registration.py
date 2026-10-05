from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer as FastMCP


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def bind(
        self,
        interfaces: list[dict[str, object]],
        dry_run: bool,
        rule_writer: Callable[[str, float, float, float | None], str],
    ) -> str:
        self.calls.append((interfaces, dry_run, rule_writer))
        return "binding-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.signal_integrity_net_class_binding")
    server = FastMCP("si-net-class-binding-registration")
    service = FakeService()

    def writer(_name: str, _clearance: float, _width: float, _gap: float | None) -> str:
        return "fixture.kicad_dru"

    adapter.register(
        server,
        adapter.SignalIntegrityNetClassBindingDependencies(
            service=service,
            rule_writer=writer,
        ),
    )

    tool_list = server._tool_manager.list_tools()
    assert [tool.name for tool in tool_list] == ["si_bind_interfaces_to_net_classes"]

    tool = tool_list[0]
    assert str(inspect.signature(tool.fn)) == (
        "(interfaces: 'list[dict[str, object]]', dry_run: 'bool' = True) -> 'str'"
    )
    assert tool.fn.__doc__ is not None
    assert tool.fn.__doc__.startswith(
        "Map interface specs from the project design intent to KiCad net classes."
    )

    interfaces = [{"kind": "usb3", "differential": True}]
    assert tool.fn(interfaces, False) == "binding-result"
    assert service.calls == [(interfaces, False, writer)]
