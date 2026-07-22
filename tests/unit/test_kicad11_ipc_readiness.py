"""KiCad 11 headless IPC readiness lane tests (issue #192).

Verifies that the capability-negotiation seam correctly differentiates between:
- KiCad 10 (GUI-bound IPC: live_pcb_read requires open board context)
- KiCad 11+ (headless IPC: live_pcb_read/write available without GUI context)

Domain logic should be unaware of which channel served a request; the
``KiCadIpcCapabilityState`` properties encapsulate that decision.
"""

from __future__ import annotations

from kicad_mcp.ipc.capabilities import (
    KICAD_11_HEADLESS_IPC_MIN_VERSION,
    KiCadIpcCapabilityState,
    _operation_states,
)
from kicad_mcp.ipc.discovery import KiCadIpcEndpoint


def _make_state(
    *,
    major: int | None,
    reachable: bool = True,
    live_pcb_context: bool = False,
    live_schematic_context: bool = False,
    headless_requested: bool = False,
) -> KiCadIpcCapabilityState:
    endpoint = KiCadIpcEndpoint(
        socket_path=None,
        source="default",
        token_configured=False,
        timeout_ms=2000,
    )
    ops = _operation_states(
        reachable=reachable,
        major_version=major,
        live_pcb_context=live_pcb_context,
        live_schematic_context=live_schematic_context,
        headless_requested=headless_requested,
    )
    return KiCadIpcCapabilityState(
        endpoint=endpoint,
        reachable=reachable,
        version=f"{major}.0.0" if major else None,
        api_version=None,
        major_version=major,
        live_pcb_context=live_pcb_context,
        live_schematic_context=live_schematic_context,
        headless_requested=headless_requested,
        operations=ops,
        diagnostics=(),
    )


def test_kicad11_min_version_constant() -> None:
    assert KICAD_11_HEADLESS_IPC_MIN_VERSION == 11


# ---------------------------------------------------------------------------
# KiCad 10: GUI-bound IPC
# ---------------------------------------------------------------------------


def test_kicad10_no_gui_context_pcb_read_false() -> None:
    state = _make_state(major=10, live_pcb_context=False)
    assert state.headless_ipc_available is False
    assert state.live_pcb_read is False


def test_kicad10_with_gui_context_pcb_read_true() -> None:
    state = _make_state(major=10, live_pcb_context=True)
    assert state.headless_ipc_available is False
    assert state.live_pcb_read is True


def test_kicad10_no_gui_context_schematic_read_false() -> None:
    state = _make_state(major=10, live_schematic_context=False)
    assert state.live_schematic_read is False


def test_kicad10_with_gui_schematic_read_true() -> None:
    state = _make_state(major=10, live_schematic_context=True)
    assert state.live_schematic_read is True


# ---------------------------------------------------------------------------
# KiCad 11: headless IPC — no GUI context required
# ---------------------------------------------------------------------------


def test_kicad11_gui_session_does_not_imply_headless_ipc() -> None:
    state = _make_state(
        major=11,
        live_pcb_context=True,
        live_schematic_context=True,
        headless_requested=False,
    )

    assert state.headless_ipc_available is False
    assert state.ipc_backend() == "kicad-ipc"
    assert state.live_pcb_read is True
    assert state.live_schematic_read is True


def test_kicad11_headless_ipc_available() -> None:
    state = _make_state(major=11, live_pcb_context=False, headless_requested=True)
    assert state.headless_ipc_available is True


def test_kicad11_pcb_read_without_gui_context() -> None:
    state = _make_state(major=11, live_pcb_context=False, headless_requested=True)
    assert state.live_pcb_read is True


def test_kicad11_pcb_write_without_gui_context() -> None:
    state = _make_state(major=11, live_pcb_context=False, headless_requested=True)
    assert state.live_pcb_write is True


def test_kicad11_schematic_read_without_gui_context() -> None:
    state = _make_state(major=11, live_schematic_context=False, headless_requested=True)
    assert state.live_schematic_read is True


def test_kicad11_schematic_write_without_gui_context() -> None:
    state = _make_state(major=11, live_schematic_context=False, headless_requested=True)
    assert state.live_schematic_write is True


def test_kicad11_ipc_backend_label() -> None:
    state = _make_state(major=11, headless_requested=True)
    assert state.ipc_backend() == "kicad-ipc-headless"


def test_kicad10_ipc_backend_label() -> None:
    state = _make_state(major=10, live_pcb_context=True)
    assert state.ipc_backend() == "kicad-ipc"


# ---------------------------------------------------------------------------
# KiCad 11: operation states use headless backend
# ---------------------------------------------------------------------------


def test_kicad11_operations_use_headless_backend() -> None:
    ops = _operation_states(
        reachable=True,
        major_version=11,
        live_pcb_context=False,
        live_schematic_context=False,
        headless_requested=True,
    )
    pcb_ops = [op for name, op in ops.items() if name != "pcb_set_design_rules"]
    assert all(op.backend == "kicad-ipc-headless" for op in pcb_ops), (
        "Expected all PCB ops to use kicad-ipc-headless, got: "
        + ", ".join(f"{name}={op.backend}" for name, op in ops.items())
    )
    assert all(op.available for op in ops.values()), "All ops should be available with KiCad 11"


def test_kicad10_operations_use_gui_backend() -> None:
    ops = _operation_states(
        reachable=True,
        major_version=10,
        live_pcb_context=True,
        live_schematic_context=False,
    )
    pcb_ops = [
        (name, op)
        for name, op in ops.items()
        if name not in {"pcb_set_design_rules"}
        and name not in {"sch_add_component", "sch_add_wire", "sch_modify_property"}
    ]
    assert all(op.backend == "kicad-ipc" for _, op in pcb_ops)


# ---------------------------------------------------------------------------
# Unreachable state
# ---------------------------------------------------------------------------


def test_unreachable_headless_ipc_false() -> None:
    state = _make_state(major=11, reachable=False, headless_requested=True)
    assert state.headless_ipc_available is False
    assert state.live_pcb_read is False
