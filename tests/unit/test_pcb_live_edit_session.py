from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from kicad_mcp.ipc.command_queue import AmbiguousMutationError
from kicad_mcp.pcb.live_edit_evidence import LiveMutationReceipt
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


def test_begin_rejects_missing_or_incomplete_board_identity() -> None:
    board = FakeBoard()
    service = _service([board])
    board.get_project = None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="does not expose project identity"):
        service.begin()

    incomplete = FakeBoard(project_path="")
    with pytest.raises(RuntimeError, match="identity is incomplete"):
        _service([incomplete]).begin()


def test_begin_rejects_missing_or_invalid_verification_snapshot() -> None:
    board = FakeBoard()
    board.get_as_string = None  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="cannot provide a verification snapshot"):
        _service([board]).begin()

    invalid = FakeBoard()
    invalid.get_as_string = lambda: b"not-text"  # type: ignore[method-assign,return-value]
    with pytest.raises(RuntimeError, match="invalid verification snapshot"):
        _service([invalid]).begin()


def test_terminal_evidence_requires_identity_and_epoch_guard_allows_idle() -> None:
    service = _service([FakeBoard()])

    service._assert_connection_epoch()
    with pytest.raises(RuntimeError, match="without board identity"):
        service._terminal_evidence("committed")


def test_abort_drop_handles_unavailable_transaction_or_drop_capability() -> None:
    board = FakeBoard()
    service = _service([board])
    assert service._drop_for_abort(board) is False

    assert service.begin().startswith("Transaction group started")
    board.drop_commit = None  # type: ignore[method-assign]
    assert service._drop_for_abort(board) is False


def test_abort_drop_marks_recovery_when_pre_state_cannot_be_restored() -> None:
    board = FakeBoard()
    service = _service([board])
    assert service.begin().startswith("Transaction group started")
    board.contents = "(kicad_pcb changed)"
    board.drop_commit = lambda _commit: None  # type: ignore[method-assign]

    assert service._drop_for_abort(board) is False
    assert service.status_payload()["state"] == "recovery_required"
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"


def test_begin_treats_none_commit_handle_as_unsupported() -> None:
    board = FakeBoard()
    board.begin_commit = lambda: None  # type: ignore[method-assign]
    service = _service([board])

    result = service.begin()

    assert "not supported" in result
    assert service.status_payload()["transaction_supported"] is False


def test_recovery_required_blocks_push_and_revert() -> None:
    service = _service([FakeBoard()])
    service._recovery_required = True

    assert "state is ambiguous" in service.push().casefold()
    assert "state is ambiguous" in service.revert().casefold()


def test_push_rejects_unsafe_receipt_before_publication() -> None:
    board = FakeBoard()
    service = _service([board])
    assert service.begin().startswith("Transaction group started")
    service._receipts.append(
        LiveMutationReceipt(
            mutation_id="live-mutation-1",
            operation="pcb_add_track",
            execution_state="failed",
            recovery_required=True,
            recovery_succeeded=None,
            duplicate_application_detected=False,
            state_divergence_detected=False,
            corruption_detected=False,
            final_state_verified=False,
        )
    )

    with pytest.raises(RuntimeError, match="unsafe state"):
        service.push()
    assert not any(call[0] == "push" for call in board.calls)


def test_push_and_drop_report_missing_native_control_methods() -> None:
    push_board = FakeBoard()
    push_service = _service([push_board])
    assert push_service.begin().startswith("Transaction group started")
    push_board.push_commit = None  # type: ignore[method-assign]
    assert push_service.push() == "No active transaction group to commit."

    drop_board = FakeBoard()
    drop_service = _service([drop_board])
    assert drop_service.begin().startswith("Transaction group started")
    drop_board.drop_commit = None  # type: ignore[method-assign]
    assert drop_service.drop() == "No active transaction group to discard."


def test_push_fails_closed_when_published_board_cannot_be_reread() -> None:
    board = FakeBoard()
    board_ref: list[object] = [board]

    def get_board() -> object:
        return board_ref[0]

    def direct(_operation: str, command: Callable[[], object]) -> object:
        return command()

    service = PcbTransactionLifecycleService(
        get_board=get_board,  # type: ignore[arg-type]
        run_mutation=direct,
        connection_errors=(OSError,),
        get_connection_epoch=lambda: 0,
    )
    assert service.begin().startswith("Transaction group started")

    def publish_then_lose_board(commit: object, message: str = "") -> None:
        board.calls.append(("push", commit, message))
        board_ref[0] = SimpleNamespace(name="unverified.kicad_pcb")

    board.push_commit = publish_then_lose_board  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="could not be re-read safely"):
        service.push()
    assert service.status_payload()["state"] == "recovery_required"


def test_drop_rejects_missing_pre_state_digest() -> None:
    board = FakeBoard()
    service = _service([board])
    assert service.begin().startswith("Transaction group started")
    service._pre_state_digest = None

    with pytest.raises(RuntimeError, match="pre-operation state is unavailable"):
        service.drop()


def test_failed_active_mutation_preserves_primary_error_when_abort_also_fails() -> None:
    board = FakeBoard()

    def runner(operation: str, command: Callable[[], object]) -> object:
        if operation == "pcb_add_track":
            raise ValueError("mutation failed")
        if operation == "pcb_drop_commit":
            raise OSError("drop transport failed")
        return command()

    service = _service([board], runner=runner)
    assert service.begin().startswith("Transaction group started")

    with pytest.raises(ValueError, match="mutation failed"):
        service.execute_board_mutation(
            "pcb_add_track",
            lambda _board: "never-returned",
            verifier=lambda _board, _result: True,
            participates_in_live_session=True,
        )

    assert service.status_payload()["state"] == "recovery_required"
    assert service.last_evidence is not None
    assert service.last_evidence.outcome == "recovery_required"


def test_standalone_verifier_exception_is_actionable() -> None:
    service = _service([FakeBoard()])

    with pytest.raises(RuntimeError, match="verification could not complete"):
        service.execute_board_mutation(
            "pcb_add_track",
            lambda _board: "created",
            verifier=lambda _board, _result: (_ for _ in ()).throw(ValueError("bad reread")),
            participates_in_live_session=True,
        )
