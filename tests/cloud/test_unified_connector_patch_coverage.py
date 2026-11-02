"""Exercise real denial and bounded dispatch paths in the unified Cloud bridge."""

from __future__ import annotations

import asyncio
import sys
import time
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from websockets.asyncio.client import ClientConnection

from kicad_mcp import cloud_once, cloud_operator_pilot, cloud_outbound_handshake
from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _complete_authorized_inspection,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.project.http_binding import HttpProjectBinding
from kicad_mcp.project.stdio_worker import (
    LocalProjectWorkerRouter,
    ProjectInspectionSession,
    ProjectWorkerDeniedError,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
RECEIPT = HandshakeReceipt(device_id=DEVICE, session_id=SESSION)


def _options(root: Path, **flags: bool) -> Namespace:
    return Namespace(
        allow_once=True,
        project_directory=root,
        filename_stem="fixture",
        private_key_file=root / "owner-key",
        cloud_origin="https://cloud.example",
        owner_sub="owner-fixture",
        device_id=DEVICE,
        project_id=PROJECT,
        **flags,
    )


@pytest.mark.parametrize(
    ("flag", "transport_name", "allowed_operation"),
    [
        ("inspection_once", "execute_operator_inspection_once", "project_worker_inspection"),
        ("board_counts_once", "execute_operator_board_counts_once", "project_board_counts"),
        (
            "schematic_counts_once",
            "execute_operator_schematic_counts_once",
            "project_schematic_counts",
        ),
    ],
)
def test_owner_selected_one_shot_operation_binds_only_that_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    transport_name: str,
    allowed_operation: str,
) -> None:
    """An owner-selected operation cannot be exchanged for a broader MCP permission."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(cloud_once, "_load_bound_owner_key", lambda *_: key)
    dispatched: list[str] = []

    async def fake_transport(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["signing_key"] is key
        assert kwargs["device_id"] == DEVICE
        assert kwargs["owner_sub"] == "owner-fixture"
        factory = cast(
            Callable[[HandshakeReceipt], BoundConnectorProjectWorker], kwargs["inspector_factory"]
        )
        worker = factory(RECEIPT)
        assert isinstance(worker, BoundConnectorProjectWorker)
        worker.assert_session_authorized(device_id=DEVICE, project_id=PROJECT, session_id=SESSION)
        worker.assert_operation_authorized(allowed_operation)
        with pytest.raises(ProjectWorkerDeniedError):
            worker.assert_operation_authorized("kicad_set_project")
        dispatched.append(allowed_operation)
        return RECEIPT

    monkeypatch.setattr(cloud_operator_pilot, transport_name, fake_transport)
    lease = (int(time.time() * 1000) + 60_000, time.monotonic_ns() + 60_000_000_000)
    assert (
        asyncio.run(
            cloud_operator_pilot._single_presence(_options(tmp_path, **{flag: True}), lease)
        )
        == RECEIPT
    )
    assert dispatched == [allowed_operation]


def test_one_shot_rejects_combined_scopes_before_reading_owner_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cloud_once,
        "_load_bound_owner_key",
        lambda *_: pytest.fail("combined scope must not access credentials"),
    )
    lease = (int(time.time() * 1000) + 60_000, time.monotonic_ns() + 60_000_000_000)
    with pytest.raises(LocalApprovalDeniedError):
        asyncio.run(
            cloud_operator_pilot._single_presence(
                _options(tmp_path, inspection_once=True, board_counts_once=True), lease
            )
        )


@pytest.mark.parametrize(
    ("flag", "message"),
    [
        ("--inspection-once", "KiCad engine inspection"),
        ("--board-counts-once", "PCB summary"),
        ("--schematic-counts-once", "schematic component summary"),
        ("--native-drc-once", "native DRC count"),
    ],
)
def test_operator_cli_reports_only_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    message: str,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        cloud_operator_pilot,
        "resolve_registered_read",
        lambda **_: SimpleNamespace(
            project_directory=tmp_path, filename_stem="fixture", key_file=tmp_path / "owner-key"
        ),
    )
    monkeypatch.setattr(
        cloud_once,
        "_confirm_local_read",
        lambda _: (int(time.time() * 1000) + 60_000, time.monotonic_ns() + 60_000_000_000),
    )

    async def completed(_: Namespace, __: tuple[int, int]) -> HandshakeReceipt:
        return RECEIPT

    monkeypatch.setattr(cloud_operator_pilot, "_single_presence", completed)
    assert (
        cloud_operator_pilot.main(
            [
                "--cloud-origin",
                "https://cloud.example",
                "--owner-sub",
                "owner-fixture",
                "--device-id",
                DEVICE,
                "--project-id",
                PROJECT,
                "--allow-once",
                flag,
            ]
        )
        == 0
    )
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    "entrypoint",
    [
        "execute_operator_board_counts_once",
        "execute_operator_schematic_counts_once",
        "execute_operator_inspection_once",
    ],
)
def test_inspection_wrappers_reject_non_callable_worker_factory_before_network(
    entrypoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cloud_outbound_handshake,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("must not open a connection"),
    )
    runner = getattr(cloud_outbound_handshake, entrypoint)(
        origin="https://cloud.example",
        trusted_origin="https://cloud.example",
        owner_sub="owner-fixture",
        device_id=DEVICE,
        signing_key=Ed25519PrivateKey.generate(),
        inspector_factory=None,
    )
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(runner)


@pytest.mark.parametrize("invalid", ["combined", "factory"])
def test_inspection_transport_rejects_invalid_mode_and_factory_without_io(
    invalid: str,
) -> None:
    broken_factory = cast(
        Callable[[HandshakeReceipt], BoundConnectorProjectWorker],
        lambda _: None,
    )
    if invalid == "combined":
        runner = _complete_authorized_inspection(
            cast(ClientConnection, None),
            RECEIPT,
            broken_factory,
            board_counts=True,
            schematic_counts=True,
        )
    else:
        runner = _complete_authorized_inspection(
            cast(ClientConnection, None),
            RECEIPT,
            broken_factory,
        )
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(runner)


def test_bound_worker_fail_closed_on_faulty_clock_and_grant(tmp_path: Path) -> None:
    def failed_clock() -> int:
        raise RuntimeError("clock unavailable")

    def failed_grant() -> bool:
        raise RuntimeError("permission store unavailable")

    for clock, grant in [
        (failed_clock, lambda: True),
        (lambda: int(time.time() * 1000), failed_grant),
    ]:
        worker = BoundConnectorProjectWorker(
            verified=VerifiedLocalBinding(
                device_id=DEVICE,
                project_id=PROJECT,
                operations=frozenset({"project_worker_inspection"}),
                session_id=SESSION,
                session_expires_unix_ms=int(time.time() * 1000) + 60_000,
            ),
            operator_project=OperatorProject(
                device_id=DEVICE,
                project_id=PROJECT,
                directory=tmp_path,
                filename_stem="fixture",
            ),
            current_authorization=grant,
            clock_ms=clock,
        )
        with pytest.raises(ProjectWorkerDeniedError):
            worker.assert_session_authorized(
                device_id=DEVICE, project_id=PROJECT, session_id=SESSION
            )


def test_router_fails_closed_when_authorization_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalProjectWorkerRouter({}, current_authorization=cast(Callable[[str], bool], None))

    def failed_auth(_: str) -> bool:
        raise RuntimeError("authorization unavailable")

    router = LocalProjectWorkerRouter({"allowed": tmp_path}, current_authorization=failed_auth)

    async def denied(project_id: object) -> None:
        async with router.connect(cast(str, project_id)):
            pytest.fail("untrusted request spawned local MCP subprocess")

    for project_id in [None, "allowed"]:
        with pytest.raises(ProjectWorkerDeniedError):
            asyncio.run(denied(project_id))


def test_inspection_session_rejects_authorization_exceptions() -> None:
    def failed_auth(_: str) -> bool:
        raise RuntimeError("grant unavailable")

    worker = ProjectInspectionSession(
        cast(ClientSession, object()),
        "approved",
        failed_auth,
    )
    with pytest.raises(ProjectWorkerDeniedError):
        worker._check_grant()


def test_http_project_binding_reports_unbound_before_first_call() -> None:
    """Avoid treating a newly initialized shared HTTP server as a pinned project."""
    assert HttpProjectBinding().is_bound is False
