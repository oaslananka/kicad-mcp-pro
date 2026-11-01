"""Offline read lifecycle: replay, expiry, unauthorized operations and close race."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.cloud_read_dispatch import MAX_READS_PER_SESSION, LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="No-follow read boundary is POSIX-only")

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "44444444-4444-4444-8444-444444444444"
REQUEST = "33333333-3333-4333-8333-333333333333"
NOW = 1_800_000_000_000


def packet(
    request_id: str = REQUEST,
    device: str = DEVICE,
    project: str = PROJECT,
    operation: str = "project_summary",
    deadline: int = NOW + 1000,
) -> bytes:
    return json.dumps(
        {
            "kind": "connector.read_request",
            "version": 1,
            "requestId": request_id,
            "deviceId": device,
            "projectId": project,
            "operation": operation,
            "deadlineUnixMs": deadline,
        },
        separators=(",", ":"),
    ).encode()


@pytest.fixture
def subject(tmp_path: Path) -> LocalReadDispatch:
    folder = tmp_path / "approved"
    folder.mkdir()
    (folder / "board.kicad_pro").write_text("private user file", encoding="utf-8")
    (folder / "board.kicad_pcb").write_text("private board", encoding="utf-8")
    return LocalReadDispatch(
        verified=VerifiedLocalBinding(
            DEVICE, PROJECT, frozenset({"project_summary"}), SESSION, NOW + 60_000
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, folder, "board"),
        current_authorization=lambda: True,
        clock_ms=lambda: NOW,
    )


@pytest.mark.parametrize("limit", [0, -1, 33, True, 1.0, "1"])
def test_read_budget_rejects_invalid_configurations(
    subject: LocalReadDispatch, limit: object
) -> None:
    with pytest.raises(LocalReadDeniedError):
        LocalReadDispatch(
            verified=subject._verified,
            operator_project=subject._project,
            current_authorization=lambda: True,
            max_reads=limit,
        )


def test_read_budget_one_denies_second_request_even_with_active_grant(
    subject: LocalReadDispatch,
) -> None:
    one_shot = LocalReadDispatch(
        verified=subject._verified,
        operator_project=subject._project,
        current_authorization=lambda: True,
        clock_ms=lambda: NOW,
        max_reads=1,
    )
    assert one_shot.read(packet(), sequence=1)["files"]["projectPresent"] is True
    later = packet("55555555-5555-4555-8555-555555555555")
    with pytest.raises(LocalReadDeniedError):
        one_shot.read(later, sequence=2)


def test_only_metadata_returned_and_no_write(subject: LocalReadDispatch) -> None:
    reply = subject.read(packet(), sequence=1)
    assert reply["files"] == {
        "projectPresent": True,
        "boardPresent": True,
        "schematicPresent": False,
    }
    assert "board.kicad_pro" not in json.dumps(reply)
    assert "board.kicad_pcb" not in json.dumps(reply)
    assert "private" not in json.dumps(reply)


def test_replay_and_out_of_order_denied(subject: LocalReadDispatch) -> None:
    assert subject.read(packet(), sequence=1)
    for seq in (1, 3, True, 0, -1, 1.0):
        _raise_argument_8 = packet()
        with pytest.raises(LocalReadDeniedError):
            subject.read(_raise_argument_8, sequence=seq)
    assert subject.read(packet("55555555-5555-4555-8555-555555555555"), sequence=2)


@pytest.mark.parametrize(
    "bad",
    [
        packet(operation="run_drc"),
        packet(operation="run_erc"),
        packet(device="66666666-6666-4666-8666-666666666666"),
        packet(project="77777777-7777-4777-8777-777777777777"),
        packet(deadline=NOW),
        b"{",
    ],
)
def test_denial_consumes_sequence_and_never_executes(
    subject: LocalReadDispatch, bad: bytes
) -> None:
    with pytest.raises(LocalReadDeniedError):
        subject.read(bad, sequence=1)
    _raise_argument_1 = packet()
    with pytest.raises(LocalReadDeniedError):
        subject.read(_raise_argument_1, sequence=1)
    assert subject.read(packet("55555555-5555-4555-8555-555555555555"), sequence=2)


def test_close_is_permanent(subject: LocalReadDispatch) -> None:
    assert subject.read(packet(), sequence=1)
    subject.close()
    subject.close()
    _raise_argument_2 = packet()
    with pytest.raises(LocalReadDeniedError):
        subject.read(_raise_argument_2, sequence=2)


def test_session_request_budget(subject: LocalReadDispatch) -> None:
    for n in range(1, MAX_READS_PER_SESSION + 1):
        assert subject.read(packet(f"{n:08x}-3333-4333-8333-333333333333"), sequence=n)
    _raise_argument_3 = packet()
    with pytest.raises(LocalReadDeniedError):
        subject.read(_raise_argument_3, sequence=MAX_READS_PER_SESSION + 1)


def test_expiry_between_start_and_return_denied(tmp_path: Path) -> None:
    now = iter([NOW, NOW + 1200])
    folder = tmp_path / "approved"
    folder.mkdir()
    subject = LocalReadDispatch(
        verified=VerifiedLocalBinding(
            DEVICE, PROJECT, frozenset({"project_summary"}), SESSION, NOW + 60_000
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, folder, "board"),
        current_authorization=lambda: True,
        clock_ms=lambda: next(now),
    )
    _raise_argument_4 = packet()
    with pytest.raises(LocalReadDeniedError):
        subject.read(_raise_argument_4, sequence=1)


def test_close_race_drops_in_flight_result(subject: LocalReadDispatch) -> None:
    inspecting = threading.Event()
    resume = threading.Event()
    failures: list[Exception] = []

    def blocking_inspect(*args: object, **kwargs: object) -> dict[str, object]:
        inspecting.set()
        assert resume.wait(timeout=4)
        return {
            "kind": "connector.local_read_preview",
            "requestId": REQUEST,
            "projectId": PROJECT,
            "version": 1,
            "operation": "project_summary",
            "files": {"projectPresent": True, "boardPresent": True, "schematicPresent": False},
        }

    def worker() -> None:
        try:
            subject.read(packet(), sequence=1)
        except Exception as exc:
            failures.append(exc)

    with patch("kicad_mcp.cloud_read_dispatch.inspect_readonly", blocking_inspect):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            assert inspecting.wait(timeout=4)
            _raise_argument_13 = packet()
            with pytest.raises(LocalReadDeniedError):
                subject.read(_raise_argument_13, sequence=2)
            subject.close()
        finally:
            resume.set()
            thread.join(timeout=4)
    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], LocalReadDeniedError)


def test_unexpected_inspection_error_releases_busy_state(subject: LocalReadDispatch) -> None:
    with patch(
        "kicad_mcp.cloud_read_dispatch.inspect_readonly",
        side_effect=LocalReadDeniedError("request denied"),
    ):
        _raise_argument_9 = packet()
        with pytest.raises(LocalReadDeniedError):
            subject.read(_raise_argument_9, sequence=1)
    assert subject.read(packet("55555555-5555-4555-8555-555555555555"), sequence=2)


def test_reused_request_id_denied_with_correct_next_sequence(
    subject: LocalReadDispatch,
) -> None:
    assert subject.read(packet(), sequence=1)
    _raise_argument_5 = packet()
    with pytest.raises(LocalReadDeniedError):
        subject.read(_raise_argument_5, sequence=2)
    # A duplicate has consumed sequence 2; a fresh ID at sequence 3 still works.
    assert subject.read(packet("55555555-5555-4555-8555-555555555555"), sequence=3)


def test_revoked_grant_before_first_read_denies_without_touching_project(
    subject: LocalReadDispatch,
) -> None:
    with patch.object(subject, "_current_authorization", return_value=False):
        with patch("kicad_mcp.cloud_read_dispatch.inspect_readonly") as inspector:
            _raise_argument_14 = packet()
            with pytest.raises(LocalReadDeniedError):
                subject.read(_raise_argument_14, sequence=1)
            inspector.assert_not_called()


def test_bad_or_failing_grant_supplier_denied(
    subject: LocalReadDispatch,
) -> None:
    with patch.object(subject, "_current_authorization", return_value=1):
        _raise_argument_10 = packet()
        with pytest.raises(LocalReadDeniedError):
            subject.read(_raise_argument_10, sequence=1)
    with patch.object(subject, "_current_authorization", side_effect=RuntimeError("denied")):
        _raise_argument_11 = packet()
        with pytest.raises(LocalReadDeniedError, match="request denied"):
            subject.read(_raise_argument_11, sequence=2)


def test_missing_grant_supplier_fails_closed(tmp_path: Path) -> None:
    _raise_argument_6 = VerifiedLocalBinding(
        DEVICE, PROJECT, frozenset({"project_summary"}), SESSION, NOW + 60000
    )
    _raise_argument_7 = OperatorProject(DEVICE, PROJECT, tmp_path, "board")
    with pytest.raises(LocalReadDeniedError):
        LocalReadDispatch(
            verified=_raise_argument_6,
            operator_project=_raise_argument_7,
            current_authorization=None,  # type: ignore[arg-type]
            clock_ms=lambda: NOW,
        )


def test_revoke_while_inspecting_drops_metadata_even_if_socket_stays_open(
    subject: LocalReadDispatch,
) -> None:
    inspecting = threading.Event()
    resume = threading.Event()
    delivered: list[dict[str, object]] = []
    denied: list[Exception] = []
    grant = {"valid": True}

    def blocking_inspect(*args: object, **kwargs: object) -> dict[str, object]:
        inspecting.set()
        assert resume.wait(timeout=4)
        return {
            "kind": "connector.local_read_preview",
            "requestId": REQUEST,
            "projectId": PROJECT,
            "version": 1,
            "operation": "project_summary",
            "files": {"projectPresent": True, "boardPresent": True, "schematicPresent": False},
        }

    def worker() -> None:
        try:
            delivered.append(subject.read(packet(), sequence=1))
        except Exception as exc:
            denied.append(exc)

    with patch.object(subject, "_current_authorization", side_effect=lambda: grant["valid"]):
        with patch("kicad_mcp.cloud_read_dispatch.inspect_readonly", blocking_inspect):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                assert inspecting.wait(timeout=4)
                grant["valid"] = False
            finally:
                resume.set()
                thread.join(timeout=4)
    assert not thread.is_alive()
    assert delivered == []
    assert len(denied) == 1
    assert isinstance(denied[0], LocalReadDeniedError)


def test_result_delivery_rechecks_grant_and_request_deadline(
    subject: LocalReadDispatch,
) -> None:
    """A once-valid read must not become a delivery capability after expiry."""
    active = {"grant": True, "now": NOW}
    with (
        patch.object(subject, "_current_authorization", side_effect=lambda: active["grant"]),
        patch.object(subject, "_clock_ms", side_effect=lambda: active["now"]),
    ):
        request = packet()
        response = subject.read(request, sequence=1)
        assert response["requestId"] == REQUEST
        active["grant"] = False
        with pytest.raises(LocalReadDeniedError):
            subject.assert_delivery_authorized(request, device_id=DEVICE, session_id=SESSION)
        active["grant"] = True
        active["now"] = NOW + 1_001
        with pytest.raises(LocalReadDeniedError):
            subject.assert_delivery_authorized(request, device_id=DEVICE, session_id=SESSION)


def test_revoke_after_inspection_but_before_reply_denies(
    subject: LocalReadDispatch,
) -> None:
    grants_checked = 0

    def revoke_on_second_check() -> bool:
        nonlocal grants_checked
        grants_checked += 1
        return grants_checked == 1

    with patch.object(subject, "_current_authorization", side_effect=revoke_on_second_check):
        _raise_argument_12 = packet()
        with pytest.raises(LocalReadDeniedError):
            subject.read(_raise_argument_12, sequence=1)
    assert grants_checked == 2


def test_parallel_project_sessions_do_not_share_local_project_state(tmp_path: Path) -> None:
    """Two concurrent Cloud reads must remain bound to their own local PCB."""
    from concurrent.futures import ThreadPoolExecutor

    second_project = "77777777-7777-4777-8777-777777777777"
    second_session = "88888888-8888-4888-8888-888888888888"
    roots = [tmp_path / "board_a", tmp_path / "board_b"]
    for root in roots:
        root.mkdir()
    (roots[0] / "alpha.kicad_pro").write_text("", encoding="utf-8")
    (roots[0] / "alpha.kicad_pcb").write_text("", encoding="utf-8")
    (roots[1] / "beta.kicad_pro").write_text("", encoding="utf-8")
    sessions = [
        LocalReadDispatch(
            verified=VerifiedLocalBinding(
                DEVICE, project_id, frozenset({"project_summary"}), session_id, NOW + 60_000
            ),
            operator_project=OperatorProject(DEVICE, project_id, root, stem),
            current_authorization=lambda: True,
            clock_ms=lambda: NOW,
        )
        for project_id, session_id, root, stem in [
            (PROJECT, SESSION, roots[0], "alpha"),
            (second_project, second_session, roots[1], "beta"),
        ]
    ]
    for session, other_project, other_session in [
        (sessions[0], second_project, second_session),
        (sessions[1], PROJECT, SESSION),
    ]:
        with pytest.raises(LocalReadDeniedError):
            session.assert_transport_session(device_id=DEVICE, session_id=other_session)
        with pytest.raises(LocalReadDeniedError):
            session.read(packet(project=other_project), sequence=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda pair: pair[0].read(
                    packet(
                        request_id="99999999-9999-4999-8999-999999999999",
                        project=pair[1],
                    ),
                    sequence=2,
                ),
                [(sessions[0], PROJECT), (sessions[1], second_project)],
            )
        )
    assert responses[0]["projectId"] == PROJECT
    assert responses[1]["projectId"] == second_project
    assert responses[0]["files"]["boardPresent"] is True
    assert responses[1]["files"]["boardPresent"] is False
