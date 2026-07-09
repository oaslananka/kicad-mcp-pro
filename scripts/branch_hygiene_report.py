from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

DEFAULT_REPO = "oaslananka/kicad-mcp-pro"
PROTECTED_BRANCHES = {"main", "master", "develop", "gh-pages"}
PROTECTED_PREFIXES = ("release/", "hotfix/")


@dataclass(frozen=True)
class StaleBranch:
    name: str
    last_commit: str


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    gh_exe = shutil.which("gh")
    if gh_exe is None:
        raise RuntimeError("gh CLI not found on PATH")
    return subprocess.run([gh_exe, *args], text=True, capture_output=True, check=False)


def _require_gh(args: list[str]) -> str:
    result = _run_gh(args)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "gh command failed"
        raise RuntimeError(stderr)
    return result.stdout


def _candidate_branch(name: str) -> bool:
    return name not in PROTECTED_BRANCHES and not name.startswith(PROTECTED_PREFIXES)


def _parse_iso(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _gh_json(args: list[str]) -> object:
    return json.loads(_require_gh(args))


def _paginated_api(repo: str, path: str) -> list[dict[str, object]]:
    page = 1
    records: list[dict[str, object]] = []
    while True:
        payload = _gh_json(
            [
                "api",
                "-X",
                "GET",
                f"/repos/{repo}/{path}",
                "-f",
                "per_page=100",
                "-f",
                f"page={page}",
            ]
        )
        if not payload:
            return records
        if not isinstance(payload, list):
            msg = f"expected list response for {path}"
            raise RuntimeError(msg)
        records.extend(record for record in payload if isinstance(record, dict))
        if len(payload) < 100:
            return records
        page += 1


def _open_pr_heads(repo: str) -> set[str]:
    output = _require_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "headRefName",
            "--jq",
            ".[].headRefName",
        ]
    )
    return {line.strip() for line in output.splitlines() if line.strip()}


def find_stale_branches(repo: str, days: int) -> list[StaleBranch]:
    branches = _paginated_api(repo, "branches")
    open_pr_heads = _open_pr_heads(repo)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stale: list[StaleBranch] = []

    for branch_info in branches:
        branch = str(branch_info.get("name", "")).strip()
        if not branch or not _candidate_branch(branch):
            continue
        if branch in open_pr_heads:
            continue

        encoded_branch = quote(branch, safe="")
        branch_sha = _run_gh(
            ["api", f"/repos/{repo}/branches/{encoded_branch}", "--jq", ".commit.sha"]
        )
        if branch_sha.returncode != 0:
            continue

        commit_date = _run_gh(
            [
                "api",
                f"/repos/{repo}/commits/{branch_sha.stdout.strip()}",
                "--jq",
                ".commit.committer.date",
            ]
        )
        if commit_date.returncode != 0:
            continue

        last_commit = commit_date.stdout.strip()
        if last_commit and _parse_iso(last_commit) < cutoff:
            stale.append(StaleBranch(name=branch, last_commit=last_commit))

    return stale


def _old_prs(repo: str) -> str:
    result = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,updatedAt,author",
            "--jq",
            (
                ".[] | select(.updatedAt < (now - 60*86400 | todate)) | "
                '"- #\\(.number) \\(.title) - last: \\(.updatedAt) by @\\(.author.login)"'
            ),
        ]
    )
    if result.returncode != 0:
        return f"unable to list old PRs: {result.stderr.strip()}"
    return result.stdout.strip()


def render_report(repo: str, days: int) -> tuple[str, int]:
    stale = find_stale_branches(repo, days)
    lines = [
        f"# Branch hygiene report - {datetime.now(UTC).date().isoformat()}",
        "",
        f"## Branches older than {days} days without open PRs",
    ]

    if stale:
        lines.extend(f"- `{branch.name}` (last commit: {branch.last_commit})" for branch in stale)
    else:
        lines.append("no stale branches found")

    lines.extend(["", "## Open PRs older than 60 days"])
    old_prs = _old_prs(repo)
    lines.append(old_prs if old_prs else "no old open PRs found")
    return "\n".join(lines) + "\n", len(stale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a branch hygiene report.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 1 when the stale branch section has no matches, preserving old "
            "grep-pipeline behavior."
        ),
    )
    args = parser.parse_args(argv)

    try:
        report, stale_count = render_report(args.repo, args.days)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(report, end="")
    if args.strict and stale_count == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
