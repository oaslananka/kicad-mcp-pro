from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.ipc.command_queue import AmbiguousMutationError
from kicad_mcp.pcb.transaction_lifecycle import PcbTransactionLifecycleService


class FakeBoard:
    def __init__(
        self,
        *,
        project_path: str = "/private/workspaces/customer/demo.kicad_pro",
        name: str = "demo.kicad_pcb",
        contents: str = "(kicad_pcb (version 20250114))",
    ) -> None:
        self.project = SimpleNamespace(path=project_path, name="demo")
        self.name = name
        self.contents = contents
        self.pre_commit_contents = contents
        self.commit = object()
        self.calls: list[tuple[object, ...]] = []

    def get_project(self) -> object:
        return self.project

    def get_as_string(self) -> str:
        return self.contents

    def begin_commit(self) -> object:
        self.pre_commit_contents = self.contents
        self.calls.append(("begin",))
        return self.commit

    def push_commit(self, commit: object, message: str = "") -> None:
        self.calls.append(("push", commit, message))

    def drop_commit(self, commit: object) -> None:
        self.calls.append(("drop", commit))
        self.contents = self.pre_commit_contents

    def revert(self) -> None:
        self.calls.append(("revert",))


def _service(
    board_ref: list[FakeBoard],
    *,
    runner: Callable[[str, Callable[[], object]], object] | None = None,
    epoch_ref: list[int] | None = None,
) -> PcbTransactionLifecycleService:
    def direct(operation: str, command: Callable[[], object]) -> object:
        del operation
        return command()

    active_epoch = epoch_ref if epoch_ref is not None else [0]
    return PcbTransactionLifecycleService(
        get_board=lambda: board_ref[0],
        run_mutation=runner or direct,
        connection_errors=(OSError,),
        get_connection_epoch=lambda: active_epoch[0],
    )


def test_begin_binds_board_identity_without_exposing_private_path() -> None:
    private_path = "/private/workspaces/customer/demo.kicad_pro"
    board = FakeBoard(project_path=private_path)
    service = _service([board])

    assert service.begin().startswith("Transaction group started.")
    payload = service.status_payload()

    assert payload["state"] == "active"
    assert payload["transaction_supported"] is True
    assert payload["board_name"] == "demo.kicad_pcb"
    assert isinstance(payload["board_fingerprint"], str)
    assert len(payload["board_fingerprint"]) == 64
    assert payload["mutation_count"] == 0
    assert private_path not in str(payload)
    assert board.contents not in str(payload)


def test_active_session_rejects_non_participating_mutation_before_side_effect() -> None:
    board = FakeBoard()
    service = _service([board])
    calls = {"n": 0}
    service.begin()

    def command(_board: object) -> str:
        calls["n"] += 1
        return "changed"

    with pytest.raises(RuntimeError, match="does not participate"):
        service.execute_board_mutation(
            "pcb_add_zone",
            command,
            verifier=lambda _board, _result: True,
            participates_in_live_session=False,
        )

    assert calls["n"] == 0


def test_active_session_rejects_unverified_participating_mutation_before_side_effect() -> None:
    board = FakeBoard()
    service = _service([board])
    calls = {"n": 0}
    service.begin()

    def command(_board: object) -> str:
        calls["n"] += 1
        return "changed"

    with pytest.raises(RuntimeError, match="postcondition verifier"):
        service.execute_board_mutation(
            "pcb_add_track",
            command,
            verifier=None,
            participates_in_live_session=True,
        )

    assert calls["n"] == 0


def test_connection_epoch_change_fails_closed_before_mutation_side_effect() -> None:
    board = FakeBoard()
    epoch = [0]
    service = _service([board], epoch_ref=epoch)
    effects: list[str] = []
    assert service.begin().startswith("Transaction group started.")

    epoch[0] += 1
    with pytest.raises(RuntimeError, match="IPC session changed"):
        service.execute_board_mutation(
            "pcb_add_track",
            lambda _board: effects.append("mutated"),
            verifier=lambda _board, _result: True,
            participates_in_live_session=True,
        )

    assert effects == []
    assert service.status_payload()["state"] == "recovery_required"
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"


def test_board_switch_is_rejected_before_mutation_side_effect() -> None:
    first = FakeBoard(project_path="/workspace/fixture-a/demo.kicad_pro", name="a.kicad_pcb")
    second = FakeBoard(project_path="/workspace/fixture-b/demo.kicad_pro", name="b.kicad_pcb")
    board_ref = [first]
    service = _service(board_ref)
    calls = {"n": 0}
    service.begin()
    board_ref[0] = second

    def command(_board: object) -> str:
        calls["n"] += 1
        return "changed"

    with pytest.raises(RuntimeError, match="active board changed"):
        service.execute_board_mutation(
            "pcb_add_track",
            command,
            verifier=lambda _board, _result: True,
            participates_in_live_session=True,
        )

    assert calls["n"] == 0
    assert service.status_payload()["recovery_required"] is True


def test_active_mutation_is_staged_until_push_rechecks_live_state() -> None:
    board = FakeBoard()
    service = _service([board])
    verifier_calls = {"n": 0}
    service.begin()

    def verifier(current: object, value: object) -> bool:
        verifier_calls["n"] += 1
        return value == "created-1" and "changed" in current.contents

    result = service.execute_board_mutation(
        "pcb_add_track",
        lambda current: setattr(current, "contents", "(kicad_pcb changed)") or "created-1",
        verifier=verifier,
        participates_in_live_session=True,
    )

    assert result == "created-1"
    assert verifier_calls["n"] == 0
    payload = service.status_payload()
    assert payload["mutation_count"] == 1
    assert payload["verified_mutation_count"] == 0
    assert service.push() == "Transaction group committed successfully."
    assert verifier_calls["n"] == 1
    assert service.status_payload()["transaction_supported"] is True
    evidence = service.last_evidence
    assert evidence is not None
    assert evidence.outcome == "committed"
    assert evidence.mutations[0].final_state_verified is True


def test_post_push_verification_failure_never_reports_commit_success() -> None:
    board = FakeBoard()
    service = _service([board])
    service.begin()

    service.execute_board_mutation(
        "pcb_add_track",
        lambda current: setattr(current, "contents", "(kicad_pcb changed)") or "created",
        verifier=lambda _board, _result: False,
        participates_in_live_session=True,
    )

    with pytest.raises(RuntimeError, match="published as one KiCad undo step.*verification failed"):
        service.push()

    assert [call[0] for call in board.calls].count("push") == 1
    payload = service.status_payload()
    assert payload["state"] == "recovery_required"
    assert payload["verified_mutation_count"] == 0
    evidence = service.last_evidence
    assert evidence is not None
    assert evidence.outcome == "recovery_required"
    assert evidence.mutations[0].recovery_required is True
    assert evidence.mutations[0].final_state_verified is False
    assert evidence.mutations[0].state_divergence_detected is True


def test_post_push_verifier_exception_never_reports_commit_success() -> None:
    board = FakeBoard()
    service = _service([board])
    service.begin()

    service.execute_board_mutation(
        "pcb_add_track",
        lambda current: setattr(current, "contents", "(kicad_pcb changed)") or "created",
        verifier=lambda _board, _result: (_ for _ in ()).throw(RuntimeError("reread exploded")),
        participates_in_live_session=True,
    )

    with pytest.raises(RuntimeError, match="published as one KiCad undo step.*could not complete"):
        service.push()

    assert service.status_payload()["state"] == "recovery_required"
    evidence = service.last_evidence
    assert evidence is not None
    assert evidence.outcome == "recovery_required"
    assert evidence.mutations[0].recovery_required is True
    assert evidence.mutations[0].state_divergence_detected is False
    assert evidence.mutations[0].final_state_verified is False


def test_ambiguous_mutation_is_not_replayed_and_is_dropped_when_same_board_is_proven() -> None:
    board = FakeBoard()
    calls = {"n": 0}

    def runner(operation: str, command: Callable[[], object]) -> object:
        if operation == "pcb_add_track":
            calls["n"] += 1
            raise AmbiguousMutationError("response lost")
        return command()

    service = _service([board], runner=runner)
    service.begin()

    with pytest.raises(AmbiguousMutationError):
        service.execute_board_mutation(
            "pcb_add_track",
            lambda _board: "created",
            verifier=lambda _board, _result: True,
            participates_in_live_session=True,
        )

    assert calls["n"] == 1
    evidence = service.last_evidence
    assert evidence is not None
    assert evidence.outcome == "aborted"
    assert evidence.mutations[0].execution_state == "interrupted"
    assert evidence.mutations[0].recovery_required is True
    assert evidence.mutations[0].recovery_succeeded is True
    assert evidence.mutations[0].final_state_verified is True


def test_drop_requires_precondition_equivalence() -> None:
    board = FakeBoard()
    service = _service([board])
    service.begin()
    board.contents = "(kicad_pcb changed outside transaction)"

    def broken_drop(_commit: object) -> None:
        board.calls.append(("drop-broken",))

    board.drop_commit = broken_drop  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="pre-operation state"):
        service.drop()

    payload = service.status_payload()
    assert payload["state"] == "recovery_required"
    assert payload["recovery_required"] is True


def test_ambiguous_begin_enters_recovery_required_and_blocks_mutations() -> None:
    board = FakeBoard()
    effects: list[str] = []

    def runner(operation: str, command: Callable[[], object]) -> object:
        if operation == "pcb_begin_commit":
            raise AmbiguousMutationError("begin response lost")
        return command()

    service = _service([board], runner=runner)

    with pytest.raises(AmbiguousMutationError, match="begin response lost"):
        service.begin()

    payload = service.status_payload()
    assert payload["state"] == "recovery_required"
    assert payload["recovery_required"] is True
    assert payload["board_name"] == "demo.kicad_pcb"
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"

    with pytest.raises(RuntimeError, match="recovery is required"):
        service.execute_board_mutation(
            "pcb_add_track",
            lambda _board: effects.append("mutated"),
            verifier=lambda _board, _result: True,
            participates_in_live_session=True,
        )
    assert effects == []
    assert "transaction state is ambiguous after an ipc failure" in service.begin().casefold()


def test_ambiguous_push_enters_recovery_required_without_reusing_commit_handle() -> None:
    board = FakeBoard()

    def runner(operation: str, command: Callable[[], object]) -> object:
        if operation == "pcb_push_commit":
            raise AmbiguousMutationError("push response lost")
        return command()

    service = _service([board], runner=runner)
    service.begin()
    service.execute_board_mutation(
        "pcb_add_track",
        lambda current: setattr(current, "contents", "(kicad_pcb changed)") or "created",
        verifier=lambda _board, _result: True,
        participates_in_live_session=True,
    )

    with pytest.raises(AmbiguousMutationError, match="push response lost"):
        service.push()

    payload = service.status_payload()
    assert payload["state"] == "recovery_required"
    assert payload["recovery_required"] is True
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"
    assert service.drop() == (
        "Transaction state is ambiguous after an IPC failure; reconcile the active KiCad board "
        "before starting, committing, or discarding another native-live transaction."
    )
    assert [call[0] for call in board.calls].count("drop") == 0


def test_ambiguous_drop_never_reports_success_and_requires_reconciliation() -> None:
    board = FakeBoard()

    def runner(operation: str, command: Callable[[], object]) -> object:
        if operation == "pcb_drop_commit":
            raise AmbiguousMutationError("drop response lost")
        return command()

    service = _service([board], runner=runner)
    service.begin()

    with pytest.raises(AmbiguousMutationError, match="drop response lost"):
        service.drop()

    assert service.status_payload()["state"] == "recovery_required"
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"
    assert "transaction state is ambiguous after an ipc failure" in service.begin().casefold()
