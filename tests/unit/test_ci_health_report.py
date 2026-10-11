"""Pure CI health report statistics; no external GitHub access required."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.ci_health_report import build_report, format_summary


def test_ci_health_report_separates_pr_and_main_and_classifies_failures() -> None:
    runs = [
        {
            "id": 1,
            "created_at": "2026-10-10T10:00:00Z",
            "run_started_at": "2026-10-10T10:00:00Z",
            "updated_at": "2026-10-10T10:10:00Z",
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request",
        },
        {
            "id": 2,
            "created_at": "2026-10-10T11:00:00Z",
            "run_started_at": "2026-10-10T11:00:00Z",
            "updated_at": "2026-10-10T11:20:00Z",
            "status": "completed",
            "conclusion": "failure",
            "event": "pull_request",
        },
        {
            "id": 3,
            "created_at": "2026-10-09T12:00:00Z",
            "run_started_at": "2026-10-09T12:00:00Z",
            "updated_at": "2026-10-09T12:12:00Z",
            "status": "completed",
            "conclusion": "cancelled",
            "event": "push",
        },
        {
            "id": 4,
            "created_at": "2026-09-01T10:00:00Z",
            "run_started_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-01T10:00:30Z",
            "status": "completed",
            "conclusion": "failure",
            "event": "pull_request",
        },
        {
            "id": 5,
            "created_at": "2026-10-11T10:00:00Z",
            "status": "in_progress",
            "conclusion": None,
            "event": "push",
        },
    ]
    jobs = {
        2: [
            {
                "name": "CI Tests / Coverage",
                "conclusion": "failure",
                "started_at": "2026-10-10T11:02:00Z",
                "completed_at": "2026-10-10T11:15:00Z",
            },
        ],
        1: [
            {
                "name": "SonarCloud Scan",
                "conclusion": "success",
                "started_at": "2026-10-10T10:11:00Z",
                "completed_at": "2026-10-10T10:13:00Z",
            },
        ],
    }
    report = build_report(runs, jobs, now=datetime(2026, 10, 11, 11, tzinfo=UTC))
    assert report["observed_runs"] == 4
    assert report["completed_runs"] == 3
    assert report["run_conclusions"] == {"cancelled": 1, "failure": 1, "success": 1}
    assert report["durations"]["pull_request"] == {
        "samples": 2,
        "p50_minutes": 10.0,
        "p95_minutes": 20.0,
    }
    assert report["durations"]["push"]["p50_minutes"] == 12.0
    assert report["top_failed_jobs"] == [("CI Tests / Coverage", 1)]
    text = format_summary(report)
    assert "CI Health" in text and "p95" in text
    assert "CI Tests / Coverage" in text


def test_ci_health_report_handles_no_history() -> None:
    report = build_report([], {}, now=datetime(2026, 10, 11, tzinfo=UTC))
    assert report["completed_runs"] == 0
    assert report["durations"]["push"]["p95_minutes"] is None
    assert "n/a" in format_summary(report)
