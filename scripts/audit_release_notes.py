#!/usr/bin/env python3
"""Auditable, read-only release-note coverage against immutable Git history.

Does not publish releases, modify Git references, or infer platform qualification.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from git import Git, GitCommandError

MATERIAL = {"feat", "fix", "perf", "security", "compat", "revert"}
INTERNAL = {"test", "style"}
SHA_LINK = re.compile(r"/commit/([0-9a-f]{7,40})(?![0-9a-f])")
TYPE = re.compile(r"^(?P<kind>[a-z]+)(?:\([^)]+\))?!?\s*:")
HEADER = re.compile(r"^## \[?(?P<version>\d+\.\d+\.\d+)\]?(?:\(|\s|$)", re.M | re.ASCII)
FAMILIES = {"mcp-server", "mcp-npm", "kicad-mcp-gui"}


class AuditError(Exception):
    """An invalid or incomplete evidence input; never interpreted as success."""


def git(repo: Path, *args: str) -> str:
    try:
        # Existing pinned GitPython dependency; an argument vector, never a shell.
        return Git(repo).execute(["git", "-C", str(repo), *args]).strip()
    except GitCommandError as exc:
        raise AuditError(f"git {args[0]} failed: {str(exc)[:300]}") from exc


def verified_commit(repo: Path, ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise AuditError("invalid commit ref")
    sha = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AuditError("commit must resolve to exact SHA-1")
    return sha


def blob(repo: Path, sha: str, path: str) -> str:
    return git(repo, "show", f"{sha}:{path}")


def version_notes(changelog: str, version: str) -> str:
    headings = list(HEADER.finditer(changelog))
    matches = [i for i, match in enumerate(headings) if match.group("version") == version]
    if len(matches) != 1:
        raise AuditError(f"expected exactly one changelog section for {version}")
    index = matches[0]
    start = headings[index].end()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    return changelog[start:end]


def changed_paths(repo: Path, sha: str) -> list[str]:
    # For merge commits include all parent diffs; deduplicate filenames.
    result = git(repo, "diff-tree", "--root", "-m", "--no-commit-id", "--name-only", "-r", sha)
    return sorted(set(result.splitlines())) if result else []


def scope_applies(package_path: str, paths: list[str]) -> bool:
    if package_path == ".":
        return True  # server is the root release; reviewer classifies shared changes
    return any(p.startswith(f"{package_path}/") for p in paths)


def change_classification(subject: str, package_path: str, paths: list[str]) -> tuple[str, str]:
    match = TYPE.match(subject)
    kind = match.group("kind") if match else "unclassified"
    if kind in INTERNAL:
        return "excluded", f"conventional {kind}: test/style-only unless manually overridden"
    if kind == "chore" and re.match(r"^chore\(main\): release ", subject):
        return "excluded", "version-bump release metadata commit; not a product feature"
    if kind not in MATERIAL:
        return (
            "needs_review",
            "docs/CI/chore/refactor or unclassified: human impact review required",
        )
    if not scope_applies(package_path, paths):
        return (
            "cross_component_review",
            "no direct package-path changes; shared impact not automatically excluded",
        )
    return "missing", f"{kind} change has no matching immutable commit link in release notes"


def audit_commit_rows(repo: Path, commits: list[str], refs: list[str], path: str) -> list[dict]:
    rows = []
    for sha in commits:
        subject = git(repo, "show", "-s", "--format=%s", sha)
        paths = changed_paths(repo, sha)
        if any(sha.startswith(ref) for ref in refs):
            status, reason = "matched", "explicit commit permalink in versioned notes"
        else:
            status, reason = change_classification(subject, path, paths)
        rows.append(
            {"sha": sha, "subject": subject, "status": status, "reason": reason, "paths": paths}
        )
    return rows


def audit_family(
    repo: Path, packages: dict, component: str, previous: str, candidate_sha: str, version: str
) -> dict:
    matches = [
        (path, setting)
        for path, setting in packages.items()
        if setting.get("component") == component
    ]
    if len(matches) != 1:
        raise AuditError(f"expected one config entry for {component}")
    path, setting = matches[0]
    prefix = setting.get("tag-prefix")
    if not isinstance(prefix, str) or not prefix:
        raise AuditError(f"missing tag prefix for {component}")
    tag = f"{prefix}{previous}"
    base_sha = verified_commit(repo, f"refs/tags/{tag}")
    git(repo, "merge-base", "--is-ancestor", base_sha, candidate_sha)
    changelog_path = ("" if path == "." else path + "/") + setting.get(
        "changelog-path", "CHANGELOG.md"
    )
    notes = version_notes(blob(repo, candidate_sha, changelog_path), version)
    refs = SHA_LINK.findall(notes)
    commits = git(repo, "rev-list", "--reverse", f"{base_sha}..{candidate_sha}").splitlines()
    for ref in refs:
        linked = [s for s in commits if s.startswith(ref)]
        if len(linked) > 1:
            raise AuditError(f"ambiguous changelog commit link: {ref}")
    rows = audit_commit_rows(repo, commits, refs, path)
    summary = {
        status: sum(row["status"] == status for row in rows)
        for status in (
            "matched",
            "missing",
            "needs_review",
            "cross_component_review",
            "excluded",
        )
    }
    return {
        "package_path": path,
        "changelog_path": changelog_path,
        "previous_tag": tag,
        "previous_sha": base_sha,
        "candidate_sha": candidate_sha,
        "summary": summary,
        "commits": rows,
    }


def audit(repo: Path, version: str, previous: str, candidate: str, families: set[str]) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version, re.ASCII) or not re.fullmatch(
        r"\d+\.\d+\.\d+", previous, re.ASCII
    ):
        raise AuditError("versions must be numeric X.Y.Z")
    candidate_sha = verified_commit(repo, candidate)
    config = json.loads(blob(repo, candidate_sha, "release-please-config.json"))
    packages = config.get("packages")
    if not isinstance(packages, dict):
        raise AuditError("release config lacks packages mapping")
    output = {
        "schema": 1,
        "release_version": version,
        "previous_version": previous,
        "candidate_sha": candidate_sha,
        "families": {},
    }
    for component in sorted(families):
        output["families"][component] = audit_family(
            repo, packages, component, previous, candidate_sha, version
        )
    return output


def markdown_report(result: dict) -> str:
    lines = [
        "# Release-note coverage audit",
        "",
        f"- Candidate: `{result['candidate_sha']}`",
        f"- Release: `{result['release_version']}`",
        f"- Comparison baseline version: `{result['previous_version']}`",
        "",
        "This is a deterministic commit-link coverage review, **not** a product,",
        "native-platform, manufacturing, or publication approval. A missing link",
        "requires human classification; code paths and conventional commit types",
        "are heuristics, not proof of user-visible impact.",
        "",
    ]
    for family, data in result["families"].items():
        lines.extend(
            [
                f"## {family}",
                "",
                f"Base: `{data['previous_tag']}` (`{data['previous_sha']}`); "
                f"notes: `{data['changelog_path']}`.",
                "",
            ]
        )
        lines.append("| Classification | Count |")
        lines.append("| --- | ---: |")
        for label, count in data["summary"].items():
            lines.append(f"| {label} | {count} |")
        lines.append("")
        for row in data["commits"]:
            if row["status"] == "matched":
                continue
            title = row["subject"].replace("|", "\\|").replace("`", "'")
            lines.append(f"- **{row['status']}** `{row['sha']}` — {title} — {row['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument(
        "--candidate", required=True, help="immutable tag or commit ref, resolved to SHA"
    )
    parser.add_argument("--families", nargs="+", choices=sorted(FAMILIES), default=sorted(FAMILIES))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()
    try:
        result = audit(
            args.repo.resolve(),
            args.version,
            args.previous_version,
            args.candidate,
            set(args.families),
        )
    except (AuditError, json.JSONDecodeError, OSError) as exc:
        print(f"release audit ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    md_text = markdown_report(result)
    if args.json_out:
        args.json_out.write_text(json_text, encoding="utf-8")
    else:
        print(json_text, end="")
    if args.markdown_out:
        args.markdown_out.write_text(md_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
