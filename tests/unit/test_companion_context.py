"""Unit tests for the KiCad companion-plugin context helpers (issue #157)."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from kicad_mcp.companion.context import (
    BoardInfo,
    StudioContextClient,
    build_studio_context,
    requires_confirmation,
)


def test_build_studio_context_maps_fields() -> None:
    info = BoardInfo(
        file_name="/proj/board.kicad_pcb",
        file_type="pcb",
        project_root="/proj",
        project_file="/proj/board.kicad_pro",
        selected_reference="U3",
        selected_net="VBUS",
        cursor=(12.5, 34.0),
        drc_errors=("clearance", "unconnected"),
    )
    args = build_studio_context(info)
    assert args["active_file"] == "/proj/board.kicad_pcb"
    assert args["file_type"] == "pcb"
    assert args["selected_reference"] == "U3"
    assert args["selected_net"] == "VBUS"
    assert args["cursor_position"] == {"x": 12.5, "y": 34.0}
    assert args["drc_errors"] == ["clearance", "unconnected"]
    assert args["snapshot"] == {"projectRoot": "/proj", "projectFile": "/proj/board.kicad_pro"}


def test_build_studio_context_omits_empty_fields() -> None:
    args = build_studio_context(BoardInfo(file_name="x.kicad_sch", file_type="schematic"))
    assert args == {"file_type": "schematic", "active_file": "x.kicad_sch"}


def test_build_studio_context_normalizes_unknown_file_type() -> None:
    args = build_studio_context(BoardInfo(file_type="gerber"))
    assert args["file_type"] == "other"


def test_requires_confirmation() -> None:
    assert requires_confirmation("move_footprint") is True
    assert requires_confirmation("apply_patch") is True
    assert requires_confirmation("read_board") is False


def test_client_builds_jsonrpc_body() -> None:
    client = StudioContextClient()
    body = client.build_request_body({"file_type": "pcb"})
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "studio_push_context"
    assert body["params"]["arguments"] == {"file_type": "pcb"}


def test_client_builds_generic_tool_call_body() -> None:
    client = StudioContextClient()
    body = client.build_tool_call_body("sch_render_png", {"sheet": "Power"}, request_id=7)
    assert body["id"] == 7
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "sch_render_png"
    assert body["params"]["arguments"] == {"sheet": "Power"}


def test_client_rejects_non_loopback_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        StudioContextClient("https://example.com")


def test_client_push_posts_to_mcp_endpoint() -> None:
    captured: dict[str, object] = {}
    closed: list[bool] = []

    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps({"result": {"status": "ok"}}).encode("utf-8")

        def close(self) -> None:
            closed.append(True)

    def fake_opener(request: urllib.request.Request) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        captured["auth"] = request.headers.get("Authorization")
        captured["accept"] = request.headers.get("Accept")
        return _FakeResponse()

    client = StudioContextClient(
        "http://127.0.0.1:9999",
        "/mcp",
        auth_token="secret",  # noqa: S106 - test fixture, not a real credential
        opener=fake_opener,
    )
    result = client.push({"file_type": "pcb", "active_file": "b.kicad_pcb"})

    assert result == {"result": {"status": "ok"}}
    assert captured["url"] == "http://127.0.0.1:9999/mcp"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer secret"
    # MCP Streamable HTTP rejects a JSON-only Accept header with HTTP 400.
    accept = str(captured["accept"])
    assert "application/json" in accept and "text/event-stream" in accept
    body = captured["body"]
    assert body["params"]["name"] == "studio_push_context"  # type: ignore[index]
    assert body["params"]["arguments"]["active_file"] == "b.kicad_pcb"  # type: ignore[index]
    assert closed == [True], "the HTTP response must be closed after reading"


def test_client_push_raises_when_mcp_tool_result_is_error() -> None:
    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "MODE_FORBIDDEN: studio_push_context is disabled in read mode"
                                ),
                            }
                        ],
                        "isError": True,
                    },
                }
            ).encode("utf-8")

        def close(self) -> None:
            pass

    client = StudioContextClient(opener=lambda _request: _FakeResponse())

    with pytest.raises(RuntimeError, match="MODE_FORBIDDEN"):
        client.push({"file_type": "pcb", "active_file": "b.kicad_pcb"})


def test_client_push_uses_generic_error_for_malformed_error_content() -> None:
    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps({"result": {"content": ["unexpected"], "isError": True}}).encode(
                "utf-8"
            )

        def close(self) -> None:
            pass

    client = StudioContextClient(opener=lambda _request: _FakeResponse())

    with pytest.raises(RuntimeError, match="MCP tool call failed"):
        client.push({"file_type": "pcb"})


def test_client_render_and_highlight_helpers_call_expected_tools() -> None:
    bodies: list[dict[str, object]] = []

    class _FakeResponse:
        def read(self) -> bytes:
            return json.dumps({"result": "ok"}).encode("utf-8")

        def close(self) -> None:
            pass

    def fake_opener(request: urllib.request.Request) -> _FakeResponse:
        bodies.append(json.loads(request.data.decode("utf-8")))  # type: ignore[union-attr]
        return _FakeResponse()

    client = StudioContextClient(opener=fake_opener)

    assert client.request_render_artifact(sheet="Power") == {"result": "ok"}
    assert client.request_highlight_net("VBUS") == {"result": "ok"}

    assert bodies[0]["params"]["name"] == "sch_render_png"  # type: ignore[index]
    assert bodies[0]["params"]["arguments"] == {"sheet": "Power"}  # type: ignore[index]
    assert bodies[1]["params"]["name"] == "pcb_highlight_net"  # type: ignore[index]
    assert bodies[1]["params"]["arguments"] == {"net_name": "VBUS"}  # type: ignore[index]


def test_companion_plugin_loads_adjacent_context_when_imported_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    import sys
    import types
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"

    class _ActionPlugin:
        pass

    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))
    monkeypatch.syspath_prepend(str(plugin_dir))
    monkeypatch.delitem(sys.modules, "context", raising=False)

    spec = importlib.util.spec_from_file_location(
        "kicad_mcp_companion_top_level_test",
        plugin_dir / "kicad_mcp_companion.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ctx = module._load_context()

    assert ctx.__name__ == "context"
    assert hasattr(ctx, "BoardInfo")


def _compat_contract() -> dict[str, object]:
    return {
        "schema_version": "kicad-mcp-companion-compat.v1",
        "plugin_version": "3.33.3",
        "backend": {"minimum": "3.33.0", "maximum_exclusive": "3.34.0"},
        "kicad": {"minimum": "10.0", "runtime": "swig"},
    }


def test_backend_compatibility_accepts_reviewed_release_window() -> None:
    from kicad_mcp.companion.context import backend_version_is_compatible

    contract = _compat_contract()
    assert backend_version_is_compatible("3.33.0", contract) is True
    assert backend_version_is_compatible("3.33.9", contract) is True
    assert backend_version_is_compatible("3.32.99", contract) is False
    assert backend_version_is_compatible("3.34.0", contract) is False


@pytest.mark.parametrize("backend_version", ["", "3.33", "3.33.0rc1", "v3.33.3", "3.x.3"])
def test_backend_compatibility_rejects_malformed_versions(backend_version: str) -> None:
    from kicad_mcp.companion.context import backend_version_is_compatible

    assert backend_version_is_compatible(backend_version, _compat_contract()) is False


def test_health_ready_requires_healthy_compatible_backend() -> None:
    from kicad_mcp.companion.context import classify_backend_health

    status = classify_backend_health(
        {"ok": True, "status": "ok", "version": "3.33.7"},
        _compat_contract(),
    )
    assert status.state == "ready"
    assert status.backend_version == "3.33.7"


def test_health_rejects_unhealthy_incompatible_and_runtime_unavailable() -> None:
    from kicad_mcp.companion.context import classify_backend_health

    unhealthy = classify_backend_health(
        {"ok": False, "status": "degraded", "version": "3.33.3"},
        _compat_contract(),
    )
    incompatible = classify_backend_health(
        {"ok": True, "status": "ok", "version": "3.34.0"},
        _compat_contract(),
    )
    runtime = classify_backend_health(
        {
            "ok": True,
            "status": "ok",
            "version": "3.33.3",
            "kicadRuntime": {"available": False},
        },
        _compat_contract(),
    )

    assert unhealthy.state == "backend_unhealthy"
    assert incompatible.state == "backend_incompatible"
    assert runtime.state == "runtime_unavailable"


def test_health_get_uses_loopback_api_health_and_closes_response() -> None:
    from kicad_mcp.companion.context import StudioContextClient

    captured: dict[str, object] = {}
    closed: list[bool] = []

    class _FakeResponse:
        status = 200

        def read(self) -> bytes:
            return json.dumps({"ok": True, "status": "ok", "version": "3.33.3"}).encode()

        def close(self) -> None:
            closed.append(True)

    def fake_opener(request: urllib.request.Request) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return _FakeResponse()

    client = StudioContextClient("http://127.0.0.1:9999", opener=fake_opener)
    status = client.health(_compat_contract())

    assert status.state == "ready"
    assert captured == {"url": "http://127.0.0.1:9999/api/health", "method": "GET"}
    assert closed == [True]


def test_health_network_failure_is_backend_unreachable() -> None:
    import urllib.error

    from kicad_mcp.companion.context import StudioContextClient

    def unavailable(_: urllib.request.Request) -> object:
        raise urllib.error.URLError("offline")

    status = StudioContextClient(opener=unavailable).health(_compat_contract())
    assert status.state == "backend_unreachable"


def test_health_unauthorized_is_authentication_required() -> None:
    import urllib.error

    from kicad_mcp.companion.context import StudioContextClient

    def unauthorized(request: urllib.request.Request) -> object:
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    status = StudioContextClient(opener=unauthorized).health(_compat_contract())
    assert status.state == "authentication_required"


def test_load_compatibility_contract_fails_closed_for_missing_or_invalid_file(
    tmp_path: Path,
) -> None:
    from kicad_mcp.companion.context import load_compatibility_contract

    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="compatibility"):
        load_compatibility_contract(missing)

    invalid = tmp_path / "compatibility.json"
    invalid.write_text('{"schema_version":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="compatibility"):
        load_compatibility_contract(invalid)


def test_backend_compatibility_rejects_invalid_contract_shape() -> None:
    from kicad_mcp.companion.context import backend_version_is_compatible

    assert backend_version_is_compatible("3.33.3", {"schema_version": "unsupported"}) is False
    assert (
        backend_version_is_compatible(
            "3.33.3",
            {
                "schema_version": "kicad-mcp-companion-compat.v1",
                "backend": "invalid",
            },
        )
        is False
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "schema_version": "kicad-mcp-companion-compat.v1",
                "plugin_version": 333,
                "backend": {"minimum": "3.33.0", "maximum_exclusive": "3.34.0"},
                "kicad": {"minimum": "10.0", "runtime": "swig"},
            },
            "incomplete",
        ),
        (
            {
                "schema_version": "kicad-mcp-companion-compat.v1",
                "plugin_version": "3.33.3",
                "backend": {"minimum": "3.34.0", "maximum_exclusive": "3.34.0"},
                "kicad": {"minimum": "10.0", "runtime": "swig"},
            },
            "backend range",
        ),
        (
            {
                "schema_version": "kicad-mcp-companion-compat.v1",
                "plugin_version": "3.33.3",
                "backend": {"minimum": "3.33.0", "maximum_exclusive": "3.34.0"},
                "kicad": {"minimum": "10.0", "runtime": "python"},
            },
            "runtime",
        ),
    ],
)
def test_load_compatibility_contract_rejects_unsafe_contract_variants(
    tmp_path: Path, payload: dict[str, object], message: str
) -> None:
    from kicad_mcp.companion.context import load_compatibility_contract

    contract = tmp_path / "compatibility.json"
    contract.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_compatibility_contract(contract)


def test_load_compatibility_contract_accepts_reviewed_contract(tmp_path: Path) -> None:
    from kicad_mcp.companion.context import load_compatibility_contract

    contract = tmp_path / "compatibility.json"
    contract.write_text(json.dumps(_compat_contract()), encoding="utf-8")

    assert load_compatibility_contract(contract) == _compat_contract()


def test_health_rejects_non_object_payload() -> None:
    from kicad_mcp.companion.context import classify_backend_health

    status = classify_backend_health("not-an-object", _compat_contract())

    assert status.state == "backend_unhealthy"


def test_health_http_failure_is_backend_unhealthy() -> None:
    import urllib.error

    from kicad_mcp.companion.context import StudioContextClient

    def failed(request: urllib.request.Request) -> object:
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    status = StudioContextClient(opener=failed).health(_compat_contract())

    assert status.state == "backend_unhealthy"
    assert "503" in status.message


def test_health_invalid_json_is_backend_unhealthy() -> None:
    from kicad_mcp.companion.context import StudioContextClient

    class _FakeResponse:
        def read(self) -> bytes:
            return b"{invalid-json"

        def close(self) -> None:
            pass

    status = StudioContextClient(opener=lambda _request: _FakeResponse()).health(_compat_contract())

    assert status.state == "backend_unhealthy"
    assert "decoded" in status.message


def _run_companion_worker_inline(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    class _ImmediateThread:
        def __init__(
            self,
            *,
            target: object,
            args: tuple[object, ...] = (),
            kwargs: dict[str, object] | None = None,
            **_: object,
        ) -> None:
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            assert callable(self._target)
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(
        module,
        "threading",
        __import__("types").SimpleNamespace(Thread=_ImmediateThread),
        raising=False,
    )


def test_action_plugin_defers_backend_io_off_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    import sys
    import types
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"
    health_calls: list[bool] = []
    scheduled: list[object] = []

    class _ActionPlugin:
        pass

    class _Client:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def health(self, _: dict[str, object]) -> object:
            health_calls.append(True)
            return types.SimpleNamespace(state="ready", message="ready")

        def push(self, _payload: object) -> None:
            pass

    class _DeferredThread:
        def __init__(self, *, target: object, **_: object) -> None:
            scheduled.append(target)

        def start(self) -> None:
            pass

    fake_ctx = types.SimpleNamespace(
        BoardInfo=object,
        StudioContextClient=_Client,
        build_studio_context=lambda info: {"active_file": str(info)},
        load_compatibility_contract=lambda: _compat_contract(),
    )
    fake_wx = types.SimpleNamespace(
        ICON_ERROR=1,
        ICON_INFORMATION=2,
        MessageBox=lambda *_args: None,
        CallAfter=lambda func, *args: func(*args),
    )
    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))
    monkeypatch.setitem(sys.modules, "wx", fake_wx)

    spec = importlib.util.spec_from_file_location(
        "kicad_mcp_companion_async_test", plugin_dir / "kicad_mcp_companion.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_context", lambda: fake_ctx)
    monkeypatch.setattr(
        module, "threading", types.SimpleNamespace(Thread=_DeferredThread), raising=False
    )
    plugin = module.KiCadMcpCompanionPlugin()
    monkeypatch.setattr(plugin, "_read_board_info", lambda _: "fixture-board")

    plugin.Run()

    assert health_calls == []
    assert len(scheduled) == 1


def test_action_plugin_does_not_push_context_when_backend_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    import sys
    import types
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"
    pushes: list[object] = []
    messages: list[str] = []

    class _ActionPlugin:
        pass

    class _Client:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def health(self, _: dict[str, object]) -> object:
            return types.SimpleNamespace(
                state="backend_incompatible",
                message="Backend version is incompatible with this KiCad companion release.",
            )

        def push(self, payload: object) -> None:
            pushes.append(payload)

    fake_ctx = types.SimpleNamespace(
        BoardInfo=object,
        StudioContextClient=_Client,
        build_studio_context=lambda info: {"active_file": str(info)},
        load_compatibility_contract=lambda: _compat_contract(),
    )
    fake_wx = types.SimpleNamespace(
        ICON_ERROR=1,
        ICON_INFORMATION=2,
        ICON_WARNING=4,
        YES_NO=8,
        YES=16,
        CallAfter=lambda func, *args: func(*args),
        MessageBox=lambda message, *_args: messages.append(str(message)),
    )
    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))
    monkeypatch.setitem(sys.modules, "wx", fake_wx)

    spec = importlib.util.spec_from_file_location(
        "kicad_mcp_companion_health_gate_test",
        plugin_dir / "kicad_mcp_companion.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_context", lambda: fake_ctx)

    _run_companion_worker_inline(monkeypatch, module)
    plugin = module.KiCadMcpCompanionPlugin()
    monkeypatch.setattr(plugin, "_read_board_info", lambda _: "fixture-board")
    plugin.Run()

    assert pushes == []
    assert messages
    assert "incompatible" in messages[-1].lower()


def test_action_plugin_surfaces_compatibility_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    import sys
    import types
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"
    messages: list[str] = []

    class _ActionPlugin:
        pass

    fake_ctx = types.SimpleNamespace(
        BoardInfo=object,
        StudioContextClient=object,
        build_studio_context=lambda _info: {},
        load_compatibility_contract=lambda: (_ for _ in ()).throw(
            ValueError("compatibility contract is malformed")
        ),
    )
    fake_wx = types.SimpleNamespace(
        ICON_ERROR=1,
        ICON_INFORMATION=2,
        ICON_WARNING=4,
        YES_NO=8,
        YES=16,
        CallAfter=lambda func, *args: func(*args),
        MessageBox=lambda message, *_args: messages.append(str(message)),
    )
    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))
    monkeypatch.setitem(sys.modules, "wx", fake_wx)

    spec = importlib.util.spec_from_file_location(
        "kicad_mcp_companion_compatibility_error_test",
        plugin_dir / "kicad_mcp_companion.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_context", lambda: fake_ctx)

    _run_companion_worker_inline(monkeypatch, module)
    plugin = module.KiCadMcpCompanionPlugin()
    monkeypatch.setattr(plugin, "_read_board_info", lambda _: "fixture-board")
    plugin.Run()

    assert messages
    assert "compatibility" in messages[-1].lower()
    assert "malformed" in messages[-1].lower()


def test_action_plugin_pushes_only_after_ready_health(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    import sys
    import types
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"
    pushes: list[object] = []

    class _ActionPlugin:
        pass

    class _Client:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def health(self, _: dict[str, object]) -> object:
            return types.SimpleNamespace(state="ready", message="ready")

        def push(self, payload: object) -> None:
            pushes.append(payload)

    fake_ctx = types.SimpleNamespace(
        BoardInfo=object,
        StudioContextClient=_Client,
        build_studio_context=lambda info: {"active_file": str(info)},
        load_compatibility_contract=lambda: _compat_contract(),
    )
    fake_wx = types.SimpleNamespace(
        ICON_ERROR=1,
        ICON_INFORMATION=2,
        ICON_WARNING=4,
        YES_NO=8,
        YES=16,
        CallAfter=lambda func, *args: func(*args),
        MessageBox=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "pcbnew", types.SimpleNamespace(ActionPlugin=_ActionPlugin))
    monkeypatch.setitem(sys.modules, "wx", fake_wx)

    spec = importlib.util.spec_from_file_location(
        "kicad_mcp_companion_ready_gate_test",
        plugin_dir / "kicad_mcp_companion.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_load_context", lambda: fake_ctx)

    _run_companion_worker_inline(monkeypatch, module)
    plugin = module.KiCadMcpCompanionPlugin()
    monkeypatch.setattr(plugin, "_read_board_info", lambda _: "fixture-board")
    plugin.Run()

    assert pushes == [{"active_file": "fixture-board"}]
