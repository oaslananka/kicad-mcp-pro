"""Fail closed when the current Windows job cannot upload its coverage report."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

PRODUCER_NAME = "mcp-server (windows-2025)"
UPLOAD_NAME = "Upload exact-run native Windows coverage"


def _objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Invalid workflow job evidence")
    return value


def _current_producer(
    payload: object, *, run_id: int, attempt: int, head: str
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        raise ValueError("Invalid workflow job listing")
    jobs = _objects(payload.get("jobs"))
    count = payload.get("total_count")
    if type(count) is not int or count != len(jobs):
        raise ValueError("Incomplete workflow job listing")
    matches = [job for job in jobs if job.get("name") == PRODUCER_NAME]
    if len(matches) > 1:
        raise ValueError("Ambiguous Windows coverage producer")
    if not matches:
        return None
    job = matches[0]
    if (job.get("run_id"), job.get("run_attempt"), job.get("head_sha")) != (run_id, attempt, head):
        raise ValueError("Windows coverage producer identity mismatch")
    return job


def check_producer(payload: object, *, run_id: int, attempt: int, head: str) -> None:
    """Return while an upload remains possible; reject definitive absence.

    A successful upload can become visible after the producer finishes, so the
    caller must continue its bounded artifact polling in that case.
    """
    job = _current_producer(payload, run_id=run_id, attempt=attempt, head=head)
    if job is None or job.get("status") != "completed":
        return
    uploads = [step for step in _objects(job.get("steps")) if step.get("name") == UPLOAD_NAME]
    if len(uploads) > 1:
        raise ValueError("Ambiguous Windows coverage upload step")
    if uploads:
        upload = uploads[0]
        if upload.get("status") != "completed" or upload.get("conclusion") == "success":
            return
        raise ValueError("Windows producer cannot produce coverage: upload did not succeed")
    if job.get("conclusion") not in (None, "success"):
        raise ValueError("Windows producer cannot produce coverage: job ended before upload")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        check_producer(
            json.load(sys.stdin), run_id=args.run_id, attempt=args.attempt, head=args.head
        )
    except (ValueError, TypeError) as exc:
        parser.exit(1, f"::error::{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
