"""Offline regression tests. No native design mutation or Cloud connection."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import (
    MAX_WRITE_FRAME_BYTES,
    LocalWriteDeniedError,
    parse_local_write_contract,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
NOW = 1_800_000_000_000
BINDING = VerifiedLocalBinding(
    device_id=DEVICE,
    project_id=PROJECT,
    operations=frozenset({"pcb_move_footprint"}),
    session_id=SESSION,
    session_expires_unix_ms=NOW + 20_000,
)
POLICY = OperatorProject(
    device_id=DEVICE,
    project_id=PROJECT,
    directory=Path("/no-project-is-accessed"),
    filename_stem="no-files",
)


def fixture() -> dict[str, object]:
    return {
        "kind": "connector.write_request",
        "version": 1,
        "requestId": REQUEST,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "sessionId": SESSION,
        "deadlineUnixMs": NOW + 1000,
        "command": {
            "operation": "pcb_move_footprint",
            "reference": "R12",
            "xMm": 42.5,
            "yMm": 10.25,
            "rotationDeg": None,
            "expectedBoardSha256": "a" * 64,
        },
    }


def fixture_v2() -> dict[str, object]:
    """Distinct signed disk/live revisions, never an execution authorization."""
    body = fixture()
    body["version"] = 2
    command = cast(dict[str, object], body["command"])
    command["expectedLiveBoardSha256"] = "b" * 64
    return body


def parse(
    payload: bytes,
    *,
    binding: VerifiedLocalBinding = BINDING,
    policy: OperatorProject = POLICY,
    now: int = NOW,
) -> dict[str, object]:
    return parse_local_write_contract(
        payload,
        verified=binding,
        operator_project=policy,
        now_unix_ms=now,
    )


def test_one_narrow_command_is_validated_without_mutating_a_file() -> None:
    expected = fixture()
    assert parse(json.dumps(expected).encode()) == expected


def test_v2_distinct_disk_and_live_snapshots_are_exactly_validated() -> None:
    body = fixture_v2()
    result = parse(json.dumps(body).encode())
    assert result == body
    command = cast(dict[str, object], result["command"])
    assert command["expectedBoardSha256"] != command["expectedLiveBoardSha256"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_live",
        "invalid_live",
        "uppercase_live",
        "short_live",
        "nonstring_live",
        "extra_live_field",
        "version_one_with_live",
        "version_bool",
        "v2_with_extra_command",
        "v2_with_extra_frame",
    ],
)
def test_v2_hostile_revision_fields_are_denied(mutation: str) -> None:
    body = fixture_v2()
    command = cast(dict[str, object], body["command"])
    if mutation == "missing_live":
        del command["expectedLiveBoardSha256"]
    elif mutation == "invalid_live":
        command["expectedLiveBoardSha256"] = "g" * 64
    elif mutation == "uppercase_live":
        command["expectedLiveBoardSha256"] = "B" * 64
    elif mutation == "short_live":
        command["expectedLiveBoardSha256"] = "b" * 63
    elif mutation == "nonstring_live":
        command["expectedLiveBoardSha256"] = True
    elif mutation == "extra_live_field":
        command["expectedUnapprovedRevision"] = "c" * 64
    elif mutation == "version_one_with_live":
        body["version"] = 1
    elif mutation == "version_bool":
        body["version"] = True
    elif mutation == "v2_with_extra_command":
        command["path"] = "../../other"
    else:
        body["path"] = "/unsafe"
    payload = json.dumps(body).encode()
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        parse(payload)


def test_v2_local_binding_and_expiry_still_fail_closed() -> None:
    body = fixture_v2()
    payload = json.dumps(body).encode()
    for binding, policy, clock in (
        (replace(BINDING, session_id=PROJECT), POLICY, NOW),
        (replace(BINDING, operations=frozenset()), POLICY, NOW),
        (BINDING, replace(POLICY, project_id=DEVICE), NOW),
        (BINDING, POLICY, NOW + 1000),
    ):
        with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
            parse(payload, binding=binding, policy=policy, now=clock)


@pytest.mark.parametrize(
    "where,key,value",
    [
        ("frame", "version", 2),
        ("frame", "kind", "connector.read_request"),
        ("frame", "sessionId", PROJECT),
        ("frame", "projectId", DEVICE),
        ("frame", "deadlineUnixMs", NOW),
        ("frame", "deadlineUnixMs", NOW + 10_001),
        ("frame", "deadlineUnixMs", True),
        ("command", "operation", "pcb_delete_all"),
        ("command", "reference", "../../x"),
        ("command", "xMm", 1001),
        ("command", "xMm", 10**500),
        ("command", "yMm", True),
        ("command", "rotationDeg", 361),
        ("command", "expectedBoardSha256", "A" * 64),
        ("command", "path", "/etc/passwd"),
        ("frame", "shell", "rm -rf /"),
    ],
)
def test_untrusted_fields_are_denied(where: str, key: str, value: object) -> None:
    data = fixture()
    target = data if where == "frame" else cast(dict[str, object], data["command"])
    target[key] = value
    payload = json.dumps(data).encode()
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        parse(payload)


def test_replay_binding_and_noncanonical_json_are_denied() -> None:
    value = json.dumps(fixture()).encode()
    invalid_session_binding = replace(BINDING, session_id=PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        parse(value, binding=invalid_session_binding)
    unauthorized_binding = replace(BINDING, operations=frozenset())
    with pytest.raises(LocalWriteDeniedError):
        parse(value, binding=unauthorized_binding)
    mismatched_policy = replace(POLICY, project_id=DEVICE)
    with pytest.raises(LocalWriteDeniedError):
        parse(value, policy=mismatched_policy)
    with pytest.raises(LocalWriteDeniedError):
        parse(value, now=NOW + 1000)
    with pytest.raises(LocalWriteDeniedError):
        parse(b'{"kind": "connector.write_request", "kind": "connector.write_request"}')
    with pytest.raises(LocalWriteDeniedError):
        parse(value + b" " * (MAX_WRITE_FRAME_BYTES + 1))
    invalid_numeric_payload = value.replace(b"42.5", b"NaN")
    with pytest.raises(LocalWriteDeniedError):
        parse(invalid_numeric_payload)


def test_cloud_and_local_v1_contract_share_golden_fixture() -> None:
    golden = (
        Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
    ).read_bytes()
    assert parse(golden) == fixture()
