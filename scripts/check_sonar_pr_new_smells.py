"""Fail when SonarCloud's completed PR analysis reports any new Code Smells.

CI fetches public JSON with curl (HTTPS-only, redirects forbidden), then pipes
it to this *network-free* parser. Main's historical issue backlog is excluded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import cast


def _unique_smell_measure(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("SonarCloud analysis response is not a JSON object")
    component = cast(dict[str, object], data).get("component")
    if not isinstance(component, dict):
        raise ValueError("SonarCloud analysis component missing")
    measures = cast(dict[str, object], component).get("measures")
    if not isinstance(measures, list):
        raise ValueError("SonarCloud analysis measures missing")
    matched: list[dict[str, object]] = []
    for item in cast(list[object], measures):
        if isinstance(item, dict):
            entry = cast(dict[str, object], item)
            if entry.get("metric") == "new_code_smells":
                matched.append(entry)
    if len(matched) != 1:
        raise ValueError("SonarCloud new_code_smells metric missing or ambiguous")
    return matched[0]


def _single_new_code_period(measure: dict[str, object]) -> dict[str, object]:
    # SonarCloud uses "periods"; some other installations use "period".
    if ("period" in measure) == ("periods" in measure):
        raise ValueError("SonarCloud new-code period missing or ambiguous")
    if "period" in measure:
        period = measure["period"]
    else:
        periods = measure["periods"]
        if not isinstance(periods, list) or len(cast(list[object], periods)) != 1:
            raise ValueError("SonarCloud new-code period missing or ambiguous")
        period = cast(list[object], periods)[0]
    if not isinstance(period, dict):
        raise ValueError("SonarCloud new-code period is not a JSON object")
    return cast(dict[str, object], period)


def _new_code_smells(data: object) -> int:
    period = _single_new_code_period(_unique_smell_measure(data))
    value = period.get("value")
    if not isinstance(value, str) or not value.isdecimal():
        raise ValueError("SonarCloud new Code Smell count invalid")
    return int(value)


def _analyzed_pr_sha(data: object, pr_number: int) -> str:
    """Require a uniquely identified completed SonarCloud PR revision."""
    if not isinstance(data, dict):
        raise ValueError("SonarCloud PR metadata is not an object")
    items = cast(dict[str, object], data).get("pullRequests")
    if not isinstance(items, list):
        raise ValueError("SonarCloud PR metadata list missing")
    matched: list[dict[str, object]] = []
    for item in cast(list[object], items):
        if isinstance(item, dict):
            entry = cast(dict[str, object], item)
            if entry.get("key") == str(pr_number):
                matched.append(entry)
    if len(matched) != 1:
        raise ValueError("SonarCloud PR analysis missing or ambiguous")
    analysis = matched[0]
    commit = analysis.get("commit")
    if not isinstance(commit, dict) or not isinstance(analysis.get("analysisDate"), str):
        raise ValueError("SonarCloud PR revision or analysis date missing")
    sha = cast(dict[str, object], commit).get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("SonarCloud PR analysis revision invalid")
    return sha


def check_pr_new_smells(
    pr_number: int,
    report: object,
    *,
    expected_sha: str,
    before: object,
    after: object,
) -> int:
    if pr_number <= 0 or re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ValueError("valid PR number and exact GitHub head SHA required")
    if _analyzed_pr_sha(before, pr_number) != expected_sha:
        raise ValueError("SonarCloud PR analysis does not match the GitHub head SHA")
    count = _new_code_smells(report)
    if _analyzed_pr_sha(after, pr_number) != expected_sha:
        raise ValueError("SonarCloud PR analysis changed while reading results")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    try:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        report = json.load(sys.stdin)
        after = json.loads(args.after.read_text(encoding="utf-8"))
        count = check_pr_new_smells(
            args.pull_request,
            report,
            expected_sha=args.expected_sha,
            before=before,
            after=after,
        )
    except (ValueError, OSError) as exc:
        print(
            f"SonarCloud new Code Smell gate FAILED (invalid analysis): {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    if count:
        print(f"SonarCloud PR has {count} new Code Smell(s); zero required.", file=sys.stderr)
        return 1
    print(f"SonarCloud PR #{args.pull_request}: exact head SHA matched; 0 new Code Smells (PASS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
