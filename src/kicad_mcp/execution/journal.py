"""Run journal for KiCad MCP Pro.

The journal persists tool call records to a per-session JSONL file so that failed runs can
be replayed, rollback tokens can be resolved, and tool sequences can be evaluated.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class JournalEntry(BaseModel):
    """A single tool-call record in the run journal."""

    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    tool_name: str
    call_id: str
    dry_run: bool = False
    ok: bool
    changed: bool
    pre_snapshot_path: str | None = None
    post_snapshot_path: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    error_summary: str | None = None
    rollback_token: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RunJournal:
    """Append-only JSONL journal for a single MCP server session."""

    def __init__(self, journal_path: Path) -> None:
        """Initialize the journal file and snapshot directory."""
        self._path = journal_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        self._snapshots_dir = journal_path.parent / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, dict[str, object]] = {}

    @classmethod
    def for_session(cls, base_dir: Path | None = None) -> RunJournal:
        """Create a journal in a temp directory scoped to this process."""
        if base_dir is None:
            base_dir = Path(tempfile.gettempdir()) / "kicad_mcp_journal"
        session_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
        journal_path = base_dir / f"run_{session_id}.jsonl"
        return cls(journal_path)

    @property
    def path(self) -> Path:
        """Return the journal path."""
        return self._path

    def snapshot_file(self, source_path: str | Path) -> str | None:
        """Copy a file to the snapshots directory and return the snapshot path."""
        src = Path(source_path)
        if not src.exists():
            return None
        snap_name = f"{uuid4().hex}_{src.name}"
        dest = self._snapshots_dir / snap_name
        shutil.copy2(src, dest)
        return str(dest)

    def begin(
        self,
        tool_name: str,
        call_id: str,
        source_files: list[str | Path] | None = None,
    ) -> str:
        """Begin a journal entry, snapshotting source files before mutation."""
        token = str(uuid4())
        snapshot_map: dict[str, str] = {}
        if source_files:
            for source_file in source_files:
                snap = self.snapshot_file(source_file)
                if snap:
                    snapshot_map[str(source_file)] = snap

        self._pending[token] = {
            "tool_name": tool_name,
            "call_id": call_id,
            "pre_snapshot_paths": list(snapshot_map.values()),
            "snapshot_map": snapshot_map,
            "started_at": _utc_now().isoformat(),
        }
        return token

    def commit(
        self,
        token: str,
        *,
        ok: bool,
        changed: bool,
        dry_run: bool = False,
        changed_files: list[str] | None = None,
        error_summary: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Commit a journal entry after a mutation attempt."""
        pending = self._pending.pop(token, {})
        pre_snaps = pending.get("pre_snapshot_paths", [])
        snapshot_map = pending.get("snapshot_map", {})
        entry_extra = dict(extra or {})
        if snapshot_map:
            entry_extra["snapshot_map"] = snapshot_map

        entry = JournalEntry(
            tool_name=str(pending.get("tool_name", "unknown")),
            call_id=str(pending.get("call_id", token)),
            dry_run=dry_run,
            ok=ok,
            changed=changed,
            pre_snapshot_path=pre_snaps[0] if isinstance(pre_snaps, list) and pre_snaps else None,
            changed_files=changed_files or [],
            error_summary=error_summary,
            rollback_token=token if changed and not dry_run else None,
            extra=entry_extra,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def rollback(self, token: str) -> list[str]:
        """Restore pre-mutation file snapshots for the given rollback token."""
        restored: list[str] = []
        if not self._path.exists():
            return restored

        for entry in self.load_entries():
            if entry.rollback_token != token:
                continue
            snapshot_map = entry.extra.get("snapshot_map", {})
            if isinstance(snapshot_map, dict):
                for changed_file in entry.changed_files:
                    snap_path = snapshot_map.get(changed_file) or entry.pre_snapshot_path
                    if snap_path is None:
                        continue
                    snap = Path(str(snap_path))
                    dest = Path(changed_file)
                    if snap.exists() and dest.parent.exists():
                        shutil.copy2(snap, dest)
                        restored.append(str(dest))
        return restored

    def load_entries(self) -> list[JournalEntry]:
        """Load all entries from this journal."""
        entries: list[JournalEntry] = []
        if not self._path.exists():
            return entries
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(JournalEntry.model_validate_json(line))
        return entries
