"""Read-only weekly CI health report from GitHub Actions (no PR writes)."""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _minutes(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    duration = (_utc(end) - _utc(start)).total_seconds() / 60
    return round(duration, 2) if duration >= 0 else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def build_report(
    runs: list[dict[str, Any]], jobs_by_run: dict[int, list[dict[str, Any]]], *, now: datetime
) -> dict[str, object]:
    cutoff = now - timedelta(days=7)
    recent = [run for run in runs if run.get("created_at") and _utc(run["created_at"]) >= cutoff]
    complete = [run for run in recent if run.get("status") == "completed"]
    duration_by_event: dict[str, dict[str, object]] = {}
    for event in ("pull_request", "push"):
        sample = [
            value
            for run in complete
            if run.get("event") == event
            if (value := _minutes(run.get("run_started_at"), run.get("updated_at"))) is not None
        ]
        duration_by_event[event] = {
            "samples": len(sample),
            "p50_minutes": _percentile(sample, 0.50),
            "p95_minutes": _percentile(sample, 0.95),
        }
    conclusions = Counter(run.get("conclusion") or "unknown" for run in complete)
    job_failures: Counter[str] = Counter()
    job_durations: dict[str, list[float]] = {}
    for job_list in jobs_by_run.values():
        for job in job_list:
            name = str(job.get("name", "unknown"))
            if job.get("conclusion") in ("failure", "timed_out"):
                job_failures[name] += 1
            duration = _minutes(job.get("started_at"), job.get("completed_at"))
            if duration is not None:
                job_durations.setdefault(name, []).append(duration)
    longest = sorted(
        (
            {"name": name, "max_minutes": max(values), "samples": len(values)}
            for name, values in job_durations.items()
        ),
        key=lambda item: (-float(item["max_minutes"]), str(item["name"])),
    )[:5]
    return {
        "window_days": 7,
        "observed_runs": len(recent),
        "completed_runs": len(complete),
        "running_runs": len(recent) - len(complete),
        "run_conclusions": dict(sorted(conclusions.items())),
        "durations": duration_by_event,
        "top_failed_jobs": job_failures.most_common(5),
        "longest_observed_jobs": longest,
        "note": (
            "Run duration uses run_started_at to updated_at; may include queue/metadata delay. "
            "Job-level samples cover at most the 12 most recent completed runs. "
            "A maximum of 100 workflow runs is queried; do not interpret samples "
            "as exhaustive if the seven-day volume exceeds that limit."
        ),
    }


def format_summary(report: dict[str, object]) -> str:
    def text(value: object) -> str:
        return "n/a" if value is None else str(value)

    lines = [
        "## CI Health — last 7 days (read-only)",
        "",
        f"Completed: **{report['completed_runs']}** / observed: {report['observed_runs']}",
        "",
        "| Event | Samples | p50 (min) | p95 (min) |",
        "|-------|---------|-----------|-----------|",
    ]
    durations = report["durations"]
    if not isinstance(durations, dict):
        raise ValueError("CI duration report must be a mapping")
    for event, item in durations.items():
        lines.append(
            f"| {event} | {item['samples']} | {text(item['p50_minutes'])} "
            f"| {text(item['p95_minutes'])} |"
        )
    lines += ["", "### Completed run outcomes", ""]
    conclusions = report["run_conclusions"]
    if not isinstance(conclusions, dict):
        raise ValueError("CI conclusion report must be a mapping")
    for name, count in conclusions.items():
        lines.append(f"- {name}: **{count}**")
    lines += ["", "### Most frequent failing jobs (recent sample)", ""]
    for name, count in report["top_failed_jobs"]:
        lines.append(f"- {name}: {count}")
    if not report["top_failed_jobs"]:
        lines.append("- No failing jobs sampled")
    lines += ["", "### Longest observed jobs (recent sample)", ""]
    for item in report["longest_observed_jobs"]:
        lines.append(f"- {item['name']}: {item['max_minutes']} min")
    lines += ["", f"_Sampling caveat: {report['note']}_", ""]
    return "\n".join(lines)


def _api_json(path: str, *, token: str) -> dict[str, Any]:
    request = Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kicad-ci-health-readonly",
        },
    )
    with urlopen(request, timeout=25) as response:  # noqa: S310 — fixed GitHub API domain
        return json.load(response)


def main() -> int:
    token = os.environ.get("GH_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository or repository.count("/") != 1:
        raise SystemExit("GH_TOKEN and GITHUB_REPOSITORY required")
    runs = _api_json(
        f"/repos/{repository}/actions/workflows/ci.yml/runs?per_page=100", token=token
    ).get("workflow_runs", [])
    complete = [run for run in runs if run.get("status") == "completed"]
    jobs_by_run: dict[int, list[dict[str, Any]]] = {}
    for run in complete[:12]:
        run_id = int(run["id"])
        jobs_by_run[run_id] = _api_json(
            f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100", token=token
        ).get("jobs", [])
    report = build_report(runs, jobs_by_run, now=datetime.now(UTC))
    Path("ci-health.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = format_summary(report)
    print(summary)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"GitHub CI health report failed: {exc}") from exc
