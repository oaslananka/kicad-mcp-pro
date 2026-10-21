"""Fail a same-repository PR if its completed SonarCloud analysis finds new Code Smells.

Run after the required SonarCloud scan's qualitygate.wait=true step. A project
maintainability rating of A is not equivalent to zero new Code Smells.
Main branch historical maintainability debt is not a release blocker.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_PROJECT_KEY = "oaslananka_kicad-mcp-pro"


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
    # SonarCloud presently returns "periods" for this project. Some newer
    # SonarQube versions use "period"; reject ambiguous responses rather than
    # silently treating a missing result as zero.
    measure = matched[0]
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
        raise ValueError("SonarCloud new Code Smell count is invalid")
    return int(value)


def check_pr_new_smells(pr_number: int) -> int:
    if pr_number <= 0:
        raise ValueError("valid PR number required")
    query = urlencode(
        {"component": _PROJECT_KEY, "pullRequest": pr_number, "metricKeys": "new_code_smells"}
    )
    # Public-project measure: no CI secrets are transmitted by this check.
    url = f"https://sonarcloud.io/api/measures/component?{query}"
    request = Request(url, headers={"Accept": "application/json"})  # noqa: S310 - fixed HTTPS host
    with urlopen(request, timeout=25) as response:  # noqa: S310 - fixed HTTPS host
        if response.geturl() != url:
            raise ValueError("unexpected SonarCloud response origin")
        return _new_code_smells(json.load(response))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull-request", type=int, required=True)
    args = parser.parse_args()
    try:
        count = check_pr_new_smells(args.pull_request)
    except (OSError, ValueError) as exc:
        print(
            "SonarCloud PR Code Smell gate FAILED "
            f"(cannot verify latest analysis): {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    if count:
        print(f"SonarCloud PR has {count} new Code Smell(s); zero required.", file=sys.stderr)
        return 1
    print("SonarCloud PR: 0 new Code Smells (PASS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
