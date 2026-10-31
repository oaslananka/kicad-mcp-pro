"""The opt-in operator pilot only sends one presence-only result."""

from __future__ import annotations

import asyncio
import json
import os
import time
from argparse import Namespace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp import cloud_once, cloud_operator_pilot
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-only owner key")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
READ = "44444444-4444-4444-8444-444444444444"
ARGS = [
    "--cloud-origin",
    "https://cloud.example",
    "--owner-sub",
    "owner-fixture",
    "--device-id",
    DEVICE,
    "--project-id",
    PROJECT,
    "--allow-once",
]


def test_pilot_denies_headless_before_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_operator_pilot.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        cloud_operator_pilot,
        "resolve_registered_read",
        lambda **_: pytest.fail("headless runner must not see owner registry"),
    )
    assert cloud_operator_pilot.main(ARGS) == 1


def test_pilot_rejects_expired_consent_before_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = Namespace(
        allow_once=True,
        project_directory=tmp_path,
        private_key_file=tmp_path / "key",
        cloud_origin="https://cloud.example",
        device_id=DEVICE,
        project_id=PROJECT,
    )
    monkeypatch.setattr(
        cloud_once,
        "_load_bound_owner_key",
        lambda *_: pytest.fail("expired approval must not read owner key"),
    )
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        asyncio.run(
            cloud_operator_pilot._single_presence(
                options, (int(time.time() * 1000) + 1000, time.monotonic_ns() - 1)
            )
        )


def test_pilot_one_shot_only_three_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "owner-selected"
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text("PRIVATE PROJECT CONTENT")
    monkeypatch.setattr(
        cloud_once,
        "_load_bound_owner_key",
        lambda *_: Ed25519PrivateKey.generate(),
    )
    options = Namespace(
        allow_once=True,
        project_directory=folder,
        filename_stem="demo",
        private_key_file=tmp_path / "key",
        cloud_origin="https://cloud.example",
        owner_sub="owner-fixture",
        device_id=DEVICE,
        project_id=PROJECT,
    )
    output: list[object] = []

    async def fake_transport(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["origin"] == kwargs["trusted_origin"] == "https://cloud.example"
        dispatch = kwargs["dispatcher_factory"](HandshakeReceipt(DEVICE, SESSION))
        frame = json.dumps(
            {
                "kind": "connector.read_request",
                "version": 1,
                "deviceId": DEVICE,
                "projectId": PROJECT,
                "requestId": READ,
                "operation": "project_summary",
                "deadlineUnixMs": int(time.time() * 1000) + 1000,
            }
        ).encode()
        output.append(dispatch.read(frame, sequence=1))
        with pytest.raises(LocalReadDeniedError):
            dispatch.read(frame, sequence=2)
        dispatch.close()
        return HandshakeReceipt(DEVICE, SESSION)

    monkeypatch.setattr(cloud_operator_pilot, "execute_operator_presence_once", fake_transport)
    asyncio.run(
        cloud_operator_pilot._single_presence(
            options, (int(time.time() * 1000) + 30_000, time.monotonic_ns() + 30_000_000_000)
        )
    )
    data = json.dumps(output)
    assert '"projectPresent": true' in data
    assert '"boardPresent": false' in data
    assert '"schematicPresent": false' in data
    assert "PRIVATE PROJECT CONTENT" not in data
    assert str(folder) not in data


def test_higher_assurance_command_remains_hard_stopped() -> None:
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._require_independent_owner_authority()
