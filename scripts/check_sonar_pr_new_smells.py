"""Fail when SonarCloud's completed PR analysis reports any new Code Smells.

CI fetches public JSON with curl (HTTPS-only, redirects forbidden), then pipes
it to this *network-free* parser. Main's historical issue backlog is excluded.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import cast


def _new_code_smells(data: object) -> int:
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
    measure = matched[0]
    # SonarCloud currently uses "periods"; newer SonarQube may use "period".
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
    value = cast(dict[str, object], period).get("value")
    if not isinstance(value, str) or not value.isdecimal():
        raise ValueError("SonarCloud new Code Smell count invalid")
    return int(value)


def check_pr_new_smells(pr_number: int, report: object) -> int:
    if pr_number <= 0:
        raise ValueError("valid SonarCloud pull request number required")
    return _new_code_smells(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", type=int, required=True)
    args = parser.parse_args()
    try:
        count = check_pr_new_smells(args.pull_request, json.load(sys.stdin))
    except (ValueError, OSError) as exc:
        print(
            f"SonarCloud new Code Smell gate FAILED (invalid analysis): {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    if count:
        print(f"SonarCloud PR has {count} new Code Smell(s); zero required.", file=sys.stderr)
        return 1
    print(f"SonarCloud PR #{args.pull_request}: 0 new Code Smells (PASS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
