"""Inventory and ratchet GitHub Release mutations made by workflows (upstream #1179).

GitHub immutable releases lock a release's assets once it is published. Any
workflow step that creates a non-draft release, or adds, replaces or deletes
assets on a release that is already published, is incompatible with that
setting. This checker statically inventories such steps in
``.github/workflows/*.y*ml`` and fails when a step mutates a published release
without an explicit allowlist entry in ``.github/actions-policy.json``
(``release_asset_mutations``). Allowlist entries that no longer match a step
also fail, so the migration to draft -> attach -> publish can only ratchet
forward.

The check is a deterministic text/YAML ratchet, not a proof: it recognises
``gh release``, ``gh api`` and ``curl`` release writes, and the known release
Actions. Indirect invocations (``eval``, variables holding ``gh``) are out of
scope; see ``docs/development/release-asset-immutability.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_KEY = "release_asset_mutations"
ISSUE = "#1179"
DOC_PATH = "docs/development/release-asset-immutability.md"

KINDS = frozenset(
    {
        "create_release",
        "upload_asset",
        "edit_release",
        "delete_release",
        "delete_asset",
        "api_write",
    }
)
_GH_RELEASE_KINDS = {
    "create": "create_release",
    "upload": "upload_asset",
    "edit": "edit_release",
    "delete": "delete_release",
    "delete-asset": "delete_asset",
}
_RELEASE_ACTIONS = {
    "googleapis/release-please-action",
    "softprops/action-gh-release",
    "ncipollo/release-action",
}
_SHELL_PREFIX_TOKENS = {
    "!",
    "(",
    "{",
    "if",
    "then",
    "else",
    "elif",
    "do",
    "while",
    "until",
    "time",
    "exec",
    "command",
}
# Wrappers that run the following command; their leading ``-x`` options are skipped too.
_WRAPPER_TOKENS = {"env", "sudo", "xargs", "nohup", "nice", "timeout"}
# Wrapper options whose value is a separate argument (``-n 10``), so it is skipped as well.
_WRAPPER_VALUE_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {
        "-u",
        "--user",
        "-g",
        "--group",
        "-C",
        "--close-from",
        "-D",
        "--chdir",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-r",
        "--role",
        "-t",
        "--type",
        "-T",
        "--command-timeout",
        "-U",
        "--other-user",
    },
    "xargs": {
        "-a",
        "--arg-file",
        "-d",
        "--delimiter",
        "-E",
        "-I",
        "-L",
        "-n",
        "--max-args",
        "-P",
        "--max-procs",
        "-s",
        "--max-chars",
        "--process-slot-var",
    },
    "nice": {"-n", "--adjustment"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
}
# Wrappers with required positional arguments before the command (``timeout DURATION``).
_WRAPPER_POSITIONALS = {"timeout": 1}
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=", re.ASCII)
_SEPARATORS = re.compile(r"\n|&&|\|\||;|\||\$\(|`")
_GHA_EXPRESSION = re.compile(r"\$\{\{.*?\}\}")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_EXPRESSION_PLACEHOLDER = "__GHA_EXPR__"
_SUBSTITUTION_PLACEHOLDER = "__SUBST__"
_WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
_GH_API_BODY_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
_CURL_BODY_FLAGS = {"-d", "--data", "--data-binary", "--data-raw", "-F", "--form", "-T"}
_ISSUE_REF = re.compile(r"^#[1-9]\d*$", re.ASCII)


@dataclass(frozen=True)
class ReleaseMutation:
    """One workflow step that writes to a GitHub Release."""

    workflow: str
    job: str
    step: str
    kind: str
    clobber: bool
    draft: bool
    target_state: str
    command: str

    @property
    def key(self) -> tuple[str, str, str, str, bool]:
        return (self.workflow, self.job, self.step, self.kind, self.clobber)

    @property
    def location(self) -> str:
        return f"{self.workflow}:{self.job}:{self.step}"


def _extract_substitution(found: list[str], match: re.Match[str]) -> str:
    found.append(match.group(1) if match.group(1) is not None else match.group(2))
    return _SUBSTITUTION_PLACEHOLDER


def split_shell_commands(script: str) -> list[str]:
    """Split a ``run`` script into simple command segments.

    Backslash continuations are joined and full-line comments are dropped.
    GitHub ``${{ ... }}`` expressions are replaced by a placeholder, and
    innermost ``$(...)``/backtick substitutions are replaced by a placeholder
    in the enclosing command while their contents are emitted as segments of
    their own. The rest is split on newlines, ``;``, ``&&``, ``||``, pipes and
    any remaining (nested) substitution openers. Quoting is not honoured when
    splitting; this only affects which segment a token lands in, not whether a
    command starts with ``gh``/``curl``.
    """

    joined = re.sub(r"\\\r?\n", " ", script)
    segments: list[str] = []
    for line in joined.splitlines():
        if line.strip().startswith("#"):
            continue
        pending = [_GHA_EXPRESSION.sub(_EXPRESSION_PLACEHOLDER, line)]
        while pending:
            text = pending.pop(0)
            inner: list[str] = []
            extract = partial(_extract_substitution, inner)
            previous = None
            while previous != text:
                previous = text
                text = _SUBSTITUTION.sub(extract, text)
            for part in _SEPARATORS.split(text):
                normalised = " ".join(part.split())
                if normalised:
                    segments.append(normalised)
            pending.extend(inner)
    return segments


def _skip_wrapper(wrapper: str, tokens: list[str]) -> list[str]:
    value_options = _WRAPPER_VALUE_OPTIONS.get(wrapper, set())
    while tokens and tokens[0].startswith("-"):
        option = tokens[0]
        tokens = tokens[1:]
        if option == "--":
            break
        if option in value_options and tokens:
            tokens = tokens[1:]
    return tokens[_WRAPPER_POSITIONALS.get(wrapper, 0) :]


def _tokens(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment, comments=False)
    except ValueError:
        tokens = segment.split()
    while tokens:
        head = tokens[0]
        if head in _SHELL_PREFIX_TOKENS or _ENV_ASSIGNMENT.match(head):
            tokens = tokens[1:]
        elif head.rsplit("/", 1)[-1] in _WRAPPER_TOKENS:
            tokens = _skip_wrapper(head.rsplit("/", 1)[-1], tokens[1:])
        else:
            break
    return tokens


def _flag_value(tokens: list[str], short: str | None, long: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == long or (short is not None and token == short):
            if index + 1 < len(tokens):
                return tokens[index + 1]
        if token.startswith(f"{long}="):
            return token.split("=", 1)[1]
        if short is not None and token.startswith(short) and len(token) > len(short):
            if not token.startswith("--"):
                return token[len(short) :]
    return None


def _draft_flag(tokens: list[str]) -> bool | None:
    """Return True for ``--draft``/``--draft=true``, None when absent, else False.

    Any other ``--draft=<value>`` (``0``, ``$VAR``, a ``${{ }}`` expression) is
    treated as published, so an unknown effect closes the draft window.
    """

    for arg in tokens:
        if arg in {"--draft", "-d"}:
            return True
        if arg.startswith("--draft="):
            return arg.split("=", 1)[1].lower() in {"1", "true"}
    return None


@dataclass(frozen=True)
class _Match:
    kind: str
    clobber: bool
    draft: bool | None
    command: str
    tag: str | None = None


def _classify_segment(segment: str) -> _Match | None:
    tokens = _tokens(segment)
    if len(tokens) < 2:
        return None
    program = tokens[0].rsplit("/", 1)[-1]
    if program == "gh" and tokens[1] == "release" and len(tokens) >= 3:
        kind = _GH_RELEASE_KINDS.get(tokens[2])
        if kind is None:
            return None
        rest = tokens[3:]
        tag = rest[0] if rest and not rest[0].startswith("-") else None
        return _Match(kind, "--clobber" in rest, _draft_flag(rest), segment, tag)
    if program == "gh" and tokens[1] == "api":
        rest = tokens[2:]
        if not any("releases" in token for token in rest):
            return None
        method = _flag_value(rest, "-X", "--method")
        if method is None:
            method = "POST" if any(token in _GH_API_BODY_FLAGS for token in rest) else "GET"
        if method.upper() in _WRITE_METHODS:
            return _Match("api_write", False, None, segment)
        return None
    if program == "curl":
        rest = tokens[1:]
        if any(_url_host(token) == "uploads.github.com" for token in rest):
            return _Match("upload_asset", False, None, segment)
        if any("/releases" in token for token in rest):
            method = _flag_value(rest, "-X", "--request")
            if method is None and any(token in _CURL_BODY_FLAGS for token in rest):
                method = "POST"
            if method is not None and method.upper() in _WRITE_METHODS:
                return _Match("api_write", False, None, segment)
    return None


def _url_host(token: str) -> str | None:
    if not token.startswith(("https://", "http://")):
        return None
    return urlsplit(token).hostname


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _release_please_config(root: Path, inputs: Mapping[str, object]) -> dict[str, object] | None:
    """Read only the trusted checkout manifest, never a remote/unknown source."""
    # The action may select another repository, branch or release strategy:
    # local config cannot certify what that invocation will actually use.
    if any(
        inputs.get(name) not in (None, "") for name in ("repo-url", "target-branch", "release-type")
    ):
        return None
    raw = inputs.get("config-file", "release-please-config.json")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        return None
    try:
        repo = root.resolve(strict=True)
        local = (repo / path).resolve(strict=True)
        local.relative_to(repo)
        config = json.loads(local.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return config if isinstance(config, dict) else None


def _release_package_is_draft(package: object, config: Mapping[str, object]) -> bool:
    if not isinstance(package, dict):
        return False
    if package.get("skip-github-release", config.get("skip-github-release")) is True:
        return True
    return (
        package.get("draft", config.get("draft")) is True
        and package.get("force-tag-creation", config.get("force-tag-creation")) is True
    )


def _release_please_is_draft(root: Path, inputs: Mapping[str, object]) -> bool:
    """Recognize only a fully tag-safe, all-packages draft configuration."""
    config = _release_please_config(root, inputs)
    if config is None:
        return False
    packages = config.get("packages")
    if not isinstance(packages, dict) or not packages:
        return False
    creates_release = any(
        isinstance(package, dict)
        and package.get("skip-github-release", config.get("skip-github-release")) is not True
        for package in packages.values()
    )
    return creates_release and all(
        _release_package_is_draft(package, config) for package in packages.values()
    )


def _classify_action(step: Mapping[str, object], *, root: Path | None = None) -> _Match | None:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return None
    action = uses.split("@", 1)[0].lower()
    if action not in _RELEASE_ACTIONS:
        return None
    raw_with = step.get("with")
    inputs: Mapping[str, object] = raw_with if isinstance(raw_with, dict) else {}
    if action == "googleapis/release-please-action":
        if _truthy(inputs.get("skip-github-release", False)):
            return None
        draft = _release_please_is_draft(root, inputs) if root is not None else False
        return _Match("create_release", False, draft, uses)
    draft = _truthy(inputs.get("draft", False))
    return _Match("create_release", False, draft, uses)


def _step_label(step: Mapping[str, object], index: int) -> str:
    for field in ("name", "id"):
        value = step.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"#{index}"


def _step_matches(step: Mapping[str, object], root: Path | None = None) -> list[_Match]:
    matches: list[_Match] = []
    action_match = _classify_action(step, root=root)
    if action_match is not None:
        matches.append(action_match)
    run = step.get("run")
    if isinstance(run, str):
        for segment in split_shell_commands(run):
            match = _classify_segment(segment)
            if match is not None:
                matches.append(match)
    return matches


def _literal_release_tag(tag: str | None) -> bool:
    return tag is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag) is not None


def _draft_target(match: _Match, draft_tag: str | None) -> tuple[str, str | None]:
    if match.kind == "create_release":
        draft = bool(match.draft)
        tag = match.tag if draft and _literal_release_tag(match.tag) else None
        return ("draft" if draft else "published", tag)
    if (
        draft_tag
        and match.tag == draft_tag
        and match.kind
        in {
            "upload_asset",
            "edit_release",
            "delete_asset",
        }
    ):
        if match.kind == "edit_release" and match.draft is False:
            return "draft", None
        return "draft", draft_tag
    # Cross-tag, expression, API write, or another release resets ownership.
    return "published", None


def _job_inventory(
    workflow: str, job: str, steps: Iterable[object], root: Path | None = None
) -> list[ReleaseMutation]:
    """Record every release write in a job, in order, with its draft/published target.

    A draft window is allowed only for a literal tag passed to a draft
    creation command. Following asset operations must use exactly that same
    literal tag. Unknown tags, other release targets, API writes, and
    publication close the inferred draft window. Every matched command is
    recorded individually.

    """

    entries: list[ReleaseMutation] = []
    draft_tag: str | None = None
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        label = _step_label(step, index)
        for match in _step_matches(step, root):
            draft = bool(match.draft)
            target, draft_tag = _draft_target(match, draft_tag)
            entry = ReleaseMutation(
                workflow=workflow,
                job=job,
                step=label,
                kind=match.kind,
                clobber=match.clobber,
                draft=draft,
                target_state=target,
                command=match.command,
            )
            entries.append(entry)
    return entries


def inventory(root: Path) -> list[ReleaseMutation]:
    """Return every GitHub Release mutation found in the repository workflows."""

    entries: list[ReleaseMutation] = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # Parse failures are reported by check_github_actions_policy.py.
            continue
        if not isinstance(data, dict):
            continue
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if isinstance(steps, list):
                entries.extend(_job_inventory(path.name, str(job_name), steps, root))
    return entries


_Key = tuple[str, str, str, str, bool]


def _allowlist_key(index: int, item: object, errors: list[str]) -> tuple[_Key, int] | None:
    prefix = f"actions-policy.json: {POLICY_KEY}[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return None
    problems: list[str] = []
    for field in ("workflow", "job", "step"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field} must be a non-empty string")
    if item.get("kind") not in KINDS:
        problems.append(f"kind must be one of {sorted(KINDS)}")
    if not isinstance(item.get("clobber"), bool):
        problems.append("clobber must be a boolean")
    issue = item.get("issue")
    if not isinstance(issue, str) or not _ISSUE_REF.fullmatch(issue):
        problems.append(f"issue must reference a tracking issue such as {ISSUE!r}")
    reason = item.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("reason must explain why the mutation is tolerated")
    count = item.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        problems.append("count must be a positive integer (default 1)")
    if problems:
        errors.append(f"{prefix}: " + "; ".join(problems))
        return None
    key = (
        str(item["workflow"]),
        str(item["job"]),
        str(item["step"]),
        str(item["kind"]),
        bool(item["clobber"]),
    )
    return key, int(count)


def validate(entries: Iterable[ReleaseMutation], allowlist: object) -> list[str]:
    """Return ratchet errors for post-publication mutations versus the allowlist."""

    if not isinstance(allowlist, list):
        return [f"actions-policy.json: {POLICY_KEY} must be a list"]

    errors: list[str] = []
    allowed: dict[_Key, int] = {}
    expected_counts: dict[_Key, int] = {}
    for index, item in enumerate(allowlist):
        parsed = _allowlist_key(index, item, errors)
        if parsed is None:
            continue
        key, count = parsed
        if key in allowed:
            errors.append(
                f"actions-policy.json: {POLICY_KEY}[{index}] duplicates entry {allowed[key]}"
            )
            continue
        allowed[key] = index
        expected_counts[key] = count

    matched: dict[_Key, int] = {}
    for entry in entries:
        if entry.target_state != "published":
            if entry.kind == "upload_asset" and entry.clobber:
                errors.append(
                    f"{entry.location}: draft asset uploads must never use --clobber "
                    f"({ISSUE}); preserve existing assets or fail closed."
                )
            continue
        if entry.key in allowed:
            matched[entry.key] = matched.get(entry.key, 0) + 1
            continue
        clobber = " with --clobber" if entry.clobber else ""
        errors.append(
            f"{entry.location}: {entry.kind}{clobber} mutates a published (non-draft) GitHub "
            f"Release and is not allowlisted in actions-policy.json {POLICY_KEY}. Immutable "
            f"releases ({ISSUE}) need draft -> attach -> publish: create the release as a "
            "draft, attach every asset without --clobber, then publish it; see "
            f"{DOC_PATH}. Command: {entry.command}"
        )

    for key, index in sorted(allowed.items(), key=lambda pair: pair[1]):
        workflow, job, step, kind, uses_clobber = key
        clobber_text = str(uses_clobber).lower()
        if key in matched:
            if matched[key] != expected_counts[key]:
                errors.append(
                    f"actions-policy.json: {POLICY_KEY}[{index}] allows "
                    f"{expected_counts[key]} command(s) but {workflow}:{job}:{step} has "
                    f"{matched[key]} matching command(s) ({kind}, clobber={clobber_text}). "
                    "A new post-publication mutation in an allowlisted step needs review; "
                    f"migrate it to draft -> attach -> publish ({ISSUE}) or, if tolerated, "
                    "set count to match. Lower count when a command is removed."
                )
            continue
        errors.append(
            f"actions-policy.json: {POLICY_KEY}[{index}] is stale: no published-release "
            f"mutation matches {workflow}:{job}:{step} ({kind}, clobber={clobber_text}). "
            f"Remove the entry once the step is migrated ({ISSUE} ratchet)."
        )
    return errors


def _load_allowlist(policy_path: Path, root: Path) -> object:
    resolved_root = root.resolve(strict=True)
    candidate = policy_path if policy_path.is_absolute() else resolved_root / policy_path
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise SystemExit("ERROR: policy must be a file inside --root") from exc
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("ERROR: policy root must be an object")
    return data.get(POLICY_KEY, [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(".github") / "actions-policy.json",
        help="Policy JSON inside --root (default: .github/actions-policy.json).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the full inventory as JSON and exit 0."
    )
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve(strict=True)
    entries = inventory(root)
    if args.json:
        print(
            json.dumps(
                [entry.__dict__ for entry in entries],
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    errors = validate(entries, _load_allowlist(args.policy, root))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    published = sum(1 for entry in entries if entry.target_state == "published")
    workflows = len({entry.workflow for entry in entries})
    print(
        f"Release asset mutation ratchet passed: {published} allowlisted post-publication "
        f"mutation(s) across {workflows} workflow(s) ({ISSUE})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
