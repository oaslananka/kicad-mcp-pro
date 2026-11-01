"""Synthetic Cloud policy lifecycle -> real offline local KiCad file boundary.

The simulated authority is NOT an OAuth verifier, a device key authenticator,
a WebSocket, a network protocol, or an authorization ticket. It only models
the already-described Cloud identity/grant/session preflight with mutable
fixture state to test local fail-closed dispatch and revocation interleavings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
    inspect_readonly,
)

OWNER = "owner-fixture"
CLIENT = "client-fixture"
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "44444444-4444-4444-8444-444444444444"
REQUEST = "33333333-3333-4333-8333-333333333333"
NOW = 1_800_000_000_000


def request(
    *, operation: str = "project_summary", device: str = DEVICE, project: str = PROJECT
) -> bytes:
    return json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": REQUEST,
            "deviceId": device,
            "projectId": project,
            "operation": operation,
            "deadlineUnixMs": NOW + 1200,
        },
        separators=(",", ":"),
    ).encode()


@dataclass
class SimulatedGrantState:
    """Fixture-only owner/client/device/project and session policy snapshot."""

    owner: str = OWNER
    client: str = CLIENT
    device: str = DEVICE
    project: str = PROJECT
    session: str = SESSION
    session_expires: int = NOW + 60_000
    device_enabled: bool = True
    project_enabled: bool = True
    client_grant_enabled: bool = True
    session_active: bool = True
    oauth_cutoff_active: bool = False
    last_sequence: int = 0

    def deliver(
        self,
        payload: bytes,
        *,
        owner: str,
        client: str,
        session: str,
        device: str,
        sequence: int,
        policy: OperatorProject,
        now: int = NOW,
    ) -> dict[str, object]:
        """Local integration fixture only; NEVER an authenticated adapter."""
        if (
            owner != self.owner
            or client != self.client
            or session != self.session
            or device != self.device
            or not self.session_active
            or not self.device_enabled
            or not self.project_enabled
            or not self.client_grant_enabled
            or self.oauth_cutoff_active
            or type(sequence) is not int
            or sequence != self.last_sequence + 1
        ):
            raise LocalReadDeniedError("request denied")
        # A real transport MUST supply this binding from independently
        # verified identity, current DB grant and server-owned socket state.
        binding = VerifiedLocalBinding(
            self.device,
            self.project,
            frozenset({"project_summary"}),
            self.session,
            self.session_expires,
        )
        result = inspect_readonly(
            payload, verified=binding, operator_project=policy, now_unix_ms=now
        )
        # No successful local read occurs if the fixture's live policy fails.
        self.last_sequence = sequence
        return result


@pytest.fixture
def target(tmp_path: Path) -> OperatorProject:
    # This uses a fresh synthetic directory, not any user's open KiCad design.
    folder = tmp_path / "owner-approved-test-project"
    folder.mkdir()
    for suffix in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
        (folder / ("fixture" + suffix)).write_text("private fixture contents", encoding="utf-8")
    return OperatorProject(DEVICE, PROJECT, folder, "fixture")


def deliver(
    state: SimulatedGrantState,
    target: OperatorProject,
    payload: bytes | None = None,
    *,
    owner: str = OWNER,
    client: str = CLIENT,
    session: str = SESSION,
    device: str = DEVICE,
    sequence: int = 1,
    now: int = NOW,
) -> dict[str, object]:
    return state.deliver(
        request() if payload is None else payload,
        owner=owner,
        client=client,
        session=session,
        device=device,
        sequence=sequence,
        policy=target,
        now=now,
    )


def test_synthetic_active_grant_allows_only_boolean_metadata(target: OperatorProject) -> None:
    state = SimulatedGrantState()
    result = deliver(state, target)
    assert state.last_sequence == 1
    assert result["files"] == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": True,
    }
    assert "fixture" not in json.dumps(result)


@pytest.mark.parametrize(
    "state_change",
    [
        {"device_enabled": False},
        {"project_enabled": False},
        {"client_grant_enabled": False},
        {"session_active": False},
        {"oauth_cutoff_active": True},
        {"session_expires": NOW},
    ],
)
def test_disabled_revoked_or_expired_fixture_denies(
    target: OperatorProject, state_change: dict[str, object]
) -> None:
    state = SimulatedGrantState()
    for name, value in state_change.items():
        setattr(state, name, value)
    with pytest.raises(LocalReadDeniedError):
        deliver(state, target)
    assert state.last_sequence == 0


@pytest.mark.parametrize(
    "actor_change",
    [
        {"owner": "other-owner"},
        {"client": "other-client"},
        {"session": "55555555-5555-4555-8555-555555555555"},
        {"device": "66666666-6666-4666-8666-666666666666"},
        {"sequence": 2},
        {"sequence": True},
    ],
)
def test_claim_changes_and_nonsequential_requests_denied(
    target: OperatorProject, actor_change: dict[str, object]
) -> None:
    _raise_argument_1 = SimulatedGrantState()
    with pytest.raises(LocalReadDeniedError):
        deliver(_raise_argument_1, target, **actor_change)


def test_grant_revocation_after_one_accepted_read_denies_next(
    target: OperatorProject,
) -> None:
    state = SimulatedGrantState()
    assert deliver(state, target)["files"]["projectPresent"]
    state.client_grant_enabled = False
    with pytest.raises(LocalReadDeniedError):
        deliver(state, target, sequence=2)
    assert state.last_sequence == 1


def test_disconnected_device_cannot_replay_earlier_read(target: OperatorProject) -> None:
    state = SimulatedGrantState()
    assert deliver(state, target)["files"]["boardPresent"]
    with pytest.raises(LocalReadDeniedError):
        deliver(state, target, sequence=1)
    state.session_active = False
    with pytest.raises(LocalReadDeniedError):
        deliver(state, target, sequence=2)


def test_grant_is_not_enough_to_authorize_other_project_or_drc(
    target: OperatorProject,
) -> None:
    for denied in (
        request(project="77777777-7777-4777-8777-777777777777"),
        request(operation="run_drc"),
        request(operation="run_erc"),
    ):
        _raise_argument_5 = SimulatedGrantState()
        with pytest.raises(LocalReadDeniedError):
            deliver(_raise_argument_5, target, denied)


def test_operator_selected_local_directory_not_from_cloud(
    target: OperatorProject, tmp_path: Path
) -> None:
    foreign = tmp_path / "other"
    foreign.mkdir()
    wrong_policy = OperatorProject(DEVICE, "99999999-9999-4999-8999-999999999999", foreign, "x")
    _raise_argument_2 = SimulatedGrantState()
    with pytest.raises(LocalReadDeniedError):
        deliver(_raise_argument_2, wrong_policy)
    tampered = json.loads(request())
    tampered["path"] = str(target.directory)
    _raise_argument_3 = SimulatedGrantState()
    _raise_argument_4 = json.dumps(tampered).encode()
    with pytest.raises(LocalReadDeniedError):
        deliver(_raise_argument_3, target, _raise_argument_4)


def test_short_live_session_cannot_authorize_longer_request(
    target: OperatorProject,
) -> None:
    state = SimulatedGrantState(session_expires=NOW + 500)
    with pytest.raises(LocalReadDeniedError):
        deliver(state, target)
    assert state.last_sequence == 0
