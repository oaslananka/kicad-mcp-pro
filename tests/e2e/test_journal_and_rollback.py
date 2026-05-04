from __future__ import annotations

from kicad_mcp.execution.journal import JournalEntry, RunJournal


def test_for_session_creates_journal_file(tmp_path) -> None:
    journal = RunJournal.for_session(tmp_path)

    assert journal.path.exists()
    assert journal.path.parent == tmp_path


def test_begin_and_commit_create_entry(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")
    source = tmp_path / "demo.kicad_sch"
    source.write_text("original", encoding="utf-8")

    token = journal.begin("sch_update_properties", "call-1", [source])
    entry = journal.commit(
        token,
        ok=True,
        changed=True,
        changed_files=[str(source)],
        extra={"note": "test"},
    )

    assert entry.tool_name == "sch_update_properties"
    assert entry.call_id == "call-1"
    assert entry.rollback_token == token
    assert entry.pre_snapshot_path is not None
    assert entry.extra["note"] == "test"
    assert len(journal.path.read_text(encoding="utf-8").splitlines()) == 1


def test_rollback_restores_file_content(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")
    source = tmp_path / "demo.kicad_sch"
    source.write_text("original content", encoding="utf-8")
    token = journal.begin("sch_update_properties", "call-1", [source])

    source.write_text("corrupted content", encoding="utf-8")
    journal.commit(token, ok=True, changed=True, changed_files=[str(source)])

    restored = journal.rollback(token)

    assert restored == [str(source)]
    assert source.read_text(encoding="utf-8") == "original content"


def test_rollback_is_idempotent(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")
    source = tmp_path / "demo.kicad_pcb"
    source.write_text("original board", encoding="utf-8")
    token = journal.begin("pcb_move_footprint", "call-2", [source])
    source.write_text("modified board", encoding="utf-8")
    journal.commit(token, ok=True, changed=True, changed_files=[str(source)])

    first = journal.rollback(token)
    second = journal.rollback(token)

    assert first == [str(source)]
    assert second == [str(source)]
    assert source.read_text(encoding="utf-8") == "original board"


def test_load_entries_round_trips_entries(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")
    source = tmp_path / "demo.kicad_sch"
    source.write_text("content", encoding="utf-8")
    token = journal.begin("sch_add_label", "call-3", [source])
    journal.commit(token, ok=True, changed=False, dry_run=True)

    entries = journal.load_entries()

    assert len(entries) == 1
    assert isinstance(entries[0], JournalEntry)
    assert entries[0].tool_name == "sch_add_label"
    assert entries[0].dry_run is True
    assert entries[0].rollback_token is None


def test_snapshot_file_missing_source_returns_none(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")

    assert journal.snapshot_file(tmp_path / "missing.kicad_sch") is None


def test_rollback_missing_journal_returns_empty_list(tmp_path) -> None:
    journal = RunJournal(tmp_path / "run.jsonl")
    journal.path.unlink()

    assert journal.rollback("missing-token") == []
