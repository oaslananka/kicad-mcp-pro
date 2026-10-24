"""Ratchet tests for GitHub Release asset mutations (upstream issue #1179)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.check_github_actions_policy import load_policy
from scripts.check_release_asset_mutations import (
    _ENV_ASSIGNMENT,
    _ISSUE_REF,
    ReleaseMutation,
    inventory,
    main,
    split_shell_commands,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_workflow(root: Path, body: str, name: str = "test.yml") -> None:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body, encoding="utf-8")


def _single_step_workflow(run: str, *, step: str = "Mutate release") -> str:
    indented = "\n".join(f"          {line}" for line in run.splitlines())
    return f"""name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: {step}
        run: |
{indented}
"""


def _entry(**overrides: object) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "workflow": "test.yml",
        "job": "publish",
        "step": "Mutate release",
        "kind": "upload_asset",
        "clobber": True,
        "issue": "#1179",
        "reason": "Legacy post-publication upload pending draft-first migration.",
    }
    entry.update(overrides)
    return entry


EXPECTED_REPOSITORY_INVENTORY = {
    ("gui-release.yml", "create-release", "Prepare release inventory", "create_release", False),
    (
        "gui-release.yml",
        "create-release",
        "Upload installers and evidence to GitHub Release",
        "upload_asset",
        True,
    ),
    (
        "publish-kicad-pcm.yml",
        "publish",
        "Attach KiCad PCM package and evidence to GitHub Release",
        "upload_asset",
        True,
    ),
    (
        "publish-mcpb.yml",
        "publish",
        "Attach MCPB bundle and evidence to GitHub Release",
        "upload_asset",
        True,
    ),
    ("publish-npm.yml", "publish", "Attach npm evidence to GitHub Release", "upload_asset", True),
    (
        "publish-npm.yml",
        "publish",
        "Attach npm post-publish verification to GitHub Release",
        "upload_asset",
        True,
    ),
    (
        "publish-protocol-schemas.yml",
        "publish",
        "Attach evidence to GitHub Release",
        "upload_asset",
        True,
    ),
    (
        "publish-python.yml",
        "build",
        "Attach Python evidence to GitHub Release",
        "upload_asset",
        True,
    ),
    (
        "publish-release.yml",
        "publish",
        "Publish merged Release Please versions",
        "create_release",
        False,
    ),
}


def test_repository_release_asset_mutations_match_allowlist() -> None:
    entries = inventory(ROOT)

    assert {entry.key for entry in entries} == EXPECTED_REPOSITORY_INVENTORY
    assert all(entry.target_state == "published" for entry in entries)
    policy = load_policy()
    allowlist = policy["release_asset_mutations"]
    assert isinstance(allowlist, list)
    assert len(allowlist) == len(EXPECTED_REPOSITORY_INVENTORY)
    assert all(item["issue"] == "#1179" for item in allowlist)
    assert validate(entries, allowlist) == []


def test_new_clobber_upload_is_rejected(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow('gh release upload "$TAG" dist/x.tgz --clobber'),
    )

    entries = inventory(tmp_path)
    errors = validate(entries, [])

    assert entries == [
        ReleaseMutation(
            workflow="test.yml",
            job="publish",
            step="Mutate release",
            kind="upload_asset",
            clobber=True,
            draft=False,
            target_state="published",
            command='gh release upload "$TAG" dist/x.tgz --clobber',
        )
    ]
    assert len(errors) == 1
    message = errors[0]
    assert "test.yml" in message
    assert "publish" in message
    assert "Mutate release" in message
    assert "--clobber" in message
    assert "#1179" in message
    assert "draft" in message


def test_new_upload_without_clobber_onto_non_draft_release_is_rejected(tmp_path: Path) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" dist/x.tgz'))

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.clobber, entry.target_state) for entry in entries] == [
        ("upload_asset", False, "published")
    ]
    assert len(validate(entries, [])) == 1


def test_upload_into_draft_created_in_same_job_is_allowed(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: Create draft release
        run: gh release create v1 --draft --verify-tag --title v1
      - name: Attach assets to draft
        run: gh release upload v1 dist/*
      - name: Publish draft
        run: gh release edit v1 --draft=false
""",
    )

    entries = inventory(tmp_path)

    assert [(entry.step, entry.kind, entry.target_state) for entry in entries] == [
        ("Create draft release", "create_release", "draft"),
        ("Attach assets to draft", "upload_asset", "draft"),
        ("Publish draft", "edit_release", "draft"),
    ]
    assert validate(entries, []) == []


def test_upload_after_draft_is_published_is_rejected(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: gh release create v1 --draft
      - run: gh release edit v1 --draft=false
      - name: Late evidence
        run: gh release upload v1 late.json
""",
    )

    entries = inventory(tmp_path)

    late = [entry for entry in entries if entry.step == "Late evidence"]
    assert [(entry.kind, entry.target_state) for entry in late] == [("upload_asset", "published")]
    assert len(validate(entries, [])) == 1


def test_draft_state_does_not_leak_across_jobs(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
permissions:
  contents: read
jobs:
  draft:
    runs-on: ubuntu-latest
    steps:
      - run: gh release create "$TAG" --draft
  attach:
    needs: draft
    runs-on: ubuntu-latest
    steps:
      - name: Attach
        run: gh release upload "$TAG" dist/*
""",
    )

    attach = [entry for entry in inventory(tmp_path) if entry.job == "attach"]

    assert [entry.target_state for entry in attach] == ["published"]


@pytest.mark.parametrize(
    ("run", "kind"),
    [
        ('gh release create "$TAG" --generate-notes', "create_release"),
        ('gh release edit "$TAG" --notes-file notes.md', "edit_release"),
        ('gh release delete-asset "$TAG" old.zip --yes', "delete_asset"),
        ('gh release delete "$TAG" --yes', "delete_release"),
        ('gh api -X POST "repos/$REPO/releases" -f tag_name="$TAG"', "api_write"),
        ('gh api --method PATCH "repos/$REPO/releases/$ID" -F draft=false', "api_write"),
        ('gh api -X DELETE "repos/$REPO/releases/assets/$ASSET"', "api_write"),
        ('gh api "repos/$REPO/releases" -f tag_name="$TAG"', "api_write"),
        (
            'curl -sS -X POST --data-binary @x.zip "https://uploads.github.com/repos/o/r/releases/1/assets?name=x.zip"',
            "upload_asset",
        ),
    ],
)
def test_release_mutation_shell_paths_detected(tmp_path: Path, run: str, kind: str) -> None:
    _write_workflow(tmp_path, _single_step_workflow(run))

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.target_state) for entry in entries] == [(kind, "published")]
    assert len(validate(entries, [])) == 1


@pytest.mark.parametrize(
    ("uses", "with_block", "expected"),
    [
        (
            "googleapis/release-please-action@" + "a" * 40,
            "skip-github-release: false",
            [("create_release", "published")],
        ),
        ("googleapis/release-please-action@" + "a" * 40, "", [("create_release", "published")]),
        ("googleapis/release-please-action@" + "a" * 40, "skip-github-release: true", []),
        (
            "softprops/action-gh-release@" + "b" * 40,
            "files: dist/*",
            [("create_release", "published")],
        ),
        ("softprops/action-gh-release@" + "b" * 40, "draft: true", [("create_release", "draft")]),
        (
            "ncipollo/release-action@" + "c" * 40,
            "allowUpdates: true",
            [("create_release", "published")],
        ),
    ],
)
def test_release_mutation_actions_detected(
    tmp_path: Path, uses: str, with_block: str, expected: list[tuple[str, str]]
) -> None:
    with_yaml = f"\n        with:\n          {with_block}" if with_block else ""
    _write_workflow(
        tmp_path,
        f"""name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: Release action
        uses: {uses}{with_yaml}
""",
    )

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.target_state) for entry in entries] == expected
    published = [entry for entry in entries if entry.target_state == "published"]
    assert len(validate(entries, [])) == len(published)


@pytest.mark.parametrize(
    "run",
    [
        'gh release view "$TAG" --json isDraft',
        "gh release list --limit 5",
        'gh release download "$TAG" --dir out --clobber',
        'gh release verify-asset "$TAG" dist/x.zip',
        'gh api "repos/$REPO/releases/tags/$TAG"',
        '# gh release upload "$TAG" commented.zip --clobber',
        "echo 'Run gh release upload manually only during recovery'",
    ],
)
def test_read_only_release_commands_ignored(tmp_path: Path, run: str) -> None:
    _write_workflow(tmp_path, _single_step_workflow(run))

    assert inventory(tmp_path) == []


def test_allowlisted_mutation_passes(tmp_path: Path) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))

    assert validate(inventory(tmp_path), [_entry()]) == []


def test_clobber_flag_change_requires_allowlist_review(tmp_path: Path) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))

    errors = validate(inventory(tmp_path), [_entry(clobber=False)])

    assert any("not allowlisted" in error for error in errors)
    assert any("stale" in error for error in errors)


def test_stale_allowlist_entry_is_rejected(tmp_path: Path) -> None:
    _write_workflow(tmp_path, _single_step_workflow("echo nothing to release"))

    errors = validate(inventory(tmp_path), [_entry()])

    assert len(errors) == 1
    assert "stale" in errors[0]
    assert "Mutate release" in errors[0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"issue": ""},
        {"issue": "1179"},
        {"issue": "#abc"},
        {"reason": ""},
        {"reason": "   "},
        {"kind": "rename_release"},
        {"clobber": "yes"},
        {"step": ""},
    ],
)
def test_allowlist_entries_require_issue_reference_and_reason(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))

    errors = validate(inventory(tmp_path), [_entry(**overrides)])

    assert any("release_asset_mutations[0]" in error for error in errors)


def test_allowlist_must_be_a_list() -> None:
    errors = validate([], {"workflow": "x"})

    assert errors == ["actions-policy.json: release_asset_mutations must be a list"]


def test_multiline_run_and_continuations_parsed(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            """for attempt in $(seq 1 18); do
  if gh release view "$RELEASE_TAG" >/dev/null 2>&1; then
    gh release upload "$RELEASE_TAG" \\
      "$upload_dir"/* \\
      --clobber
    exit 0
  fi
done"""
        ),
    )

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.clobber) for entry in entries] == [("upload_asset", True)]


def test_split_shell_commands_handles_separators_and_comments() -> None:
    script = (
        "set -e\na && gh release upload t x; echo done # trailing\n  # only a comment\nb || c | d"
    )

    assert split_shell_commands(script) == [
        "set -e",
        "a",
        "gh release upload t x",
        "echo done # trailing",
        "b",
        "c",
        "d",
    ]


def test_unnamed_step_uses_id_then_index(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - id: upload-one
        run: gh release upload "$TAG" a --clobber
      - run: gh release upload "$TAG" b --clobber
""",
    )

    assert [entry.step for entry in inventory(tmp_path)] == ["upload-one", "#2"]


def test_cli_reports_inventory_and_fails_on_unlisted_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))
    policy = tmp_path / ".github" / "actions-policy.json"
    policy.write_text(json.dumps({"release_asset_mutations": []}), encoding="utf-8")
    argv = ["--root", str(tmp_path), "--policy", str(policy)]

    assert main(argv) == 1
    assert "not allowlisted" in capsys.readouterr().out

    policy.write_text(json.dumps({"release_asset_mutations": [_entry()]}), encoding="utf-8")

    assert main(argv) == 0
    assert "1 allowlisted post-publication mutation" in capsys.readouterr().out


def test_cli_passes_on_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ROOT)]) == 0, capsys.readouterr().out


def test_same_step_upload_after_publish_is_not_deduplicated(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            """gh release create v1 --draft
gh release upload v1 a
gh release edit v1 --draft=false
gh release upload v1 b"""
        ),
    )

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.target_state) for entry in entries] == [
        ("create_release", "draft"),
        ("upload_asset", "draft"),
        ("edit_release", "draft"),
        ("upload_asset", "published"),
    ]
    errors = validate(entries, [])
    assert len(errors) == 1
    assert "gh release upload v1 b" in errors[0]


def test_same_named_steps_upload_before_and_after_publish(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: gh release create v1 --draft
      - name: s
        run: gh release upload v1 a
      - name: p
        run: gh release edit v1 --draft=false
      - name: s
        run: gh release upload v1 b
""",
    )

    entries = inventory(tmp_path)

    assert [entry.target_state for entry in entries if entry.step == "s"] == [
        "draft",
        "published",
    ]
    assert len(validate(entries, [])) == 1


@pytest.mark.parametrize(
    "publish",
    [
        "gh api -X PATCH repos/o/r/releases/1 -f draft=false",
        'gh api --method PATCH "repos/$REPO/releases/$ID" --input publish.json',
        'curl -X PATCH -d \'{"draft":false}\' "https://api.github.com/repos/o/r/releases/1"',
    ],
)
def test_api_write_closes_the_draft_window(tmp_path: Path, publish: str) -> None:
    _write_workflow(
        tmp_path,
        f"""name: fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: gh release create v1 --draft
      - name: Publish via API
        run: {json.dumps(publish)}
      - name: Late evidence
        run: gh release upload v1 x --clobber
""",
    )

    entries = inventory(tmp_path)

    assert [(entry.step, entry.kind, entry.target_state) for entry in entries][1:] == [
        ("Publish via API", "api_write", "published"),
        ("Late evidence", "upload_asset", "published"),
    ]
    errors = validate(entries, [])
    assert len(errors) == 2
    assert "Publish via API" in errors[0]
    assert "Late evidence" in errors[1]


@pytest.mark.parametrize(
    "run",
    [
        'gh release upload "${{ inputs.tag || github.ref_name }}" f --clobber',
        'gh release upload "$(cat tag.txt)" f --clobber',
        'gh release upload "`cat tag.txt`" f --clobber',
        "env GH_TOKEN=x gh release upload v1 f --clobber",
        "sudo -E gh release upload v1 f --clobber",
        "ls f | xargs gh release upload v1 --clobber",
        "timeout 60 gh release upload v1 f --clobber",
        "timeout -k 5 -s TERM 60 gh release upload v1 f --clobber",
        "nice -n 10 gh release upload v1 f --clobber",
        "sudo -u bot gh release upload v1 f --clobber",
        "env -u GH_DEBUG gh release upload v1 f --clobber",
        "ls f | xargs -I {} gh release upload v1 {} --clobber",
    ],
)
def test_expressions_substitutions_and_wrappers_keep_the_whole_command(
    tmp_path: Path, run: str
) -> None:
    _write_workflow(tmp_path, _single_step_workflow(run))

    entries = inventory(tmp_path)

    assert [(entry.kind, entry.clobber, entry.target_state) for entry in entries] == [
        ("upload_asset", True, "published")
    ]
    assert validate(entries, [_entry()]) == []


def test_command_substitution_contents_are_still_inspected(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow('id="$(gh api -X POST "repos/$REPO/releases" -f tag_name=v1)"'),
    )

    assert [entry.kind for entry in inventory(tmp_path)] == ["api_write"]


def test_new_command_in_allowlisted_step_is_rejected(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            """gh release upload "$TAG" x --clobber
gh release upload "$TAG" y --clobber"""
        ),
    )

    entries = inventory(tmp_path)
    errors = validate(entries, [_entry()])

    assert len(entries) == 2
    assert len(errors) == 1
    assert "2 matching command(s)" in errors[0]
    assert validate(entries, [_entry(count=2)]) == []


@pytest.mark.parametrize("count", [0, -1, "2", True, 1.5])
def test_allowlist_count_must_be_positive_integer(tmp_path: Path, count: object) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))

    errors = validate(inventory(tmp_path), [_entry(count=count)])

    assert any("count must be a positive integer" in error for error in errors)


def test_allowlist_count_above_matches_is_rejected(tmp_path: Path) -> None:
    _write_workflow(tmp_path, _single_step_workflow('gh release upload "$TAG" x --clobber'))

    errors = validate(inventory(tmp_path), [_entry(count=2)])

    assert len(errors) == 1
    assert "1 matching command(s)" in errors[0]


def test_curl_upload_requires_uploads_host_not_substring(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            'curl -sS -o x.zip "https://example.com/mirror/uploads.github.com/x.zip"'
        ),
    )

    assert inventory(tmp_path) == []


@pytest.mark.parametrize(
    "publish",
    [
        "gh release edit v1 --draft=0",
        "gh release edit v1 --draft=False",
        'gh release edit v1 --draft="$PUBLISH"',
        "gh release edit v1 --draft=${{ inputs.draft }}",
    ],
)
def test_unrecognised_draft_value_closes_the_draft_window(tmp_path: Path, publish: str) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(f"gh release create v1 --draft\n{publish}\ngh release upload v1 x"),
    )

    entries = inventory(tmp_path)

    assert entries[-1].kind == "upload_asset"
    assert entries[-1].target_state == "published"
    assert len(validate(entries, [])) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("FOO=", True),
        ("_X9=value", True),
        ("X9=1", True),
        ("9X=value", False),
        ("É=value", False),
        ("X٧=value", False),
        ("X６=value", False),
    ],
)
def test_wrapper_environment_assignment_remains_ascii_only(value: str, expected: bool) -> None:
    assert (_ENV_ASSIGNMENT.match(value) is not None) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#1179", True),
        ("#1", True),
        ("#0", False),
        ("#01", False),
        ("#١", False),
        ("#1٧", False),
        ("#1６", False),
    ],
)
def test_policy_issue_reference_remains_ascii_only(value: str, expected: bool) -> None:
    assert (_ISSUE_REF.fullmatch(value) is not None) is expected


def _release_please_fixture(
    root: Path,
    config: object,
    *,
    config_file: str = "release-please-config.json",
    skip_release: str = "false",
) -> None:
    (root / "release-please-config.json").write_text(json.dumps(config), encoding="utf-8")
    _write_workflow(
        root,
        f"""name: Draft release fixture
on: push
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: Release Please
        uses: googleapis/release-please-action@{"a" * 40}
        with:
          config-file: {config_file}
          skip-github-release: {skip_release}
""",
    )


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"draft": True, "force-tag-creation": True, "packages": {".": {}}}, "draft"),
        (
            {
                "draft": True,
                "force-tag-creation": True,
                "packages": {".": {}, "packages/npm": {"draft": True}},
            },
            "draft",
        ),
        (
            {
                "packages": {
                    ".": {"draft": True, "force-tag-creation": True},
                    "packages/npm": {"draft": True, "force-tag-creation": True},
                }
            },
            "draft",
        ),
        ({"draft": True, "packages": {".": {}}}, "published"),
        ({"draft": True, "force-tag-creation": False, "packages": {".": {}}}, "published"),
        (
            {
                "draft": True,
                "force-tag-creation": True,
                "packages": {".": {}, "packages/npm": {"draft": False}},
            },
            "published",
        ),
        (
            {
                "draft": True,
                "force-tag-creation": True,
                "packages": {".": {}, "packages/npm": {"force-tag-creation": False}},
            },
            "published",
        ),
        ({"draft": True, "force-tag-creation": True, "packages": {}}, "published"),
        (
            {"draft": True, "force-tag-creation": True, "packages": {".": "invalid"}},
            "published",
        ),
        (
            {
                "draft": True,
                "force-tag-creation": True,
                "packages": {".": {"skip-github-release": True}},
            },
            "published",
        ),
    ],
)
def test_release_please_manifest_draft_requires_all_package_tags(
    tmp_path: Path, config: object, expected: str
) -> None:
    _release_please_fixture(tmp_path, config)
    entries = inventory(tmp_path)
    assert len(entries) == 1
    assert entries[0].kind == "create_release"
    assert entries[0].target_state == expected
    assert (validate(entries, []) == []) is (expected == "draft")


@pytest.mark.parametrize(
    "config_path",
    ["../foreign.json", "/not-authorized/foreign.json", "$GHA_CONFIG"],
)
def test_release_please_manifest_path_untrusted_is_not_a_draft(
    tmp_path: Path, config_path: str
) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid, config_file=config_path)
    entries = inventory(tmp_path)
    assert entries[0].target_state == "published"
    assert len(validate(entries, [])) == 1


def test_release_please_manifest_invalid_json_is_not_draft(tmp_path: Path) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid)
    (tmp_path / "release-please-config.json").write_text("{", encoding="utf-8")
    entries = inventory(tmp_path)
    assert entries[0].target_state == "published"


def test_release_please_manifest_path_symlink_cannot_escape(tmp_path: Path) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    external = tmp_path.parent / f"{tmp_path.name}-outside.json"
    external.write_text(json.dumps(valid), encoding="utf-8")
    (tmp_path / "release-please-config.json").symlink_to(external)
    _write_workflow(
        tmp_path,
        f"""name: fixture
on: push
jobs:
  publish:
    steps:
      - uses: googleapis/release-please-action@{"a" * 40}
        with:
          skip-github-release: false
""",
    )
    entries = inventory(tmp_path)
    assert entries[0].target_state == "published"


def test_skipped_release_please_step_creates_no_release_even_if_draft(tmp_path: Path) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid, skip_release="true")
    assert inventory(tmp_path) == []


def test_draft_upload_with_clobber_is_rejected(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        """name: fixture
on: push
jobs:
  publish:
    steps:
      - run: gh release create v1 --draft
      - name: Dangerous draft replacement
        run: gh release upload v1 x.tgz --clobber
""",
    )
    entries = inventory(tmp_path)
    assert entries[-1].target_state == "draft"
    errors = validate(entries, [])
    assert len(errors) == 1
    assert "never use --clobber" in errors[0]


def test_draft_create_and_safe_upload_across_config_and_job_is_not_inferred(
    tmp_path: Path,
) -> None:
    """Release Please draft action does not confer cross-job draft upload safety."""
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid)
    path = tmp_path / ".github" / "workflows" / "test.yml"
    source = path.read_text()
    source += """
  attach:
    needs: publish
    steps:
      - run: gh release upload "$TAG" x.tgz
"""
    path.write_text(source, encoding="utf-8")
    entries = inventory(tmp_path)
    assert [(x.kind, x.target_state) for x in entries] == [
        ("create_release", "draft"),
        ("upload_asset", "published"),
    ]
    assert len(validate(entries, [])) == 1


@pytest.mark.parametrize(
    "alternative",
    [
        "repo-url: other-owner/other-repo",
        "repo-url: $GITHUB_REPOSITORY",
        "target-branch: another-branch",
        "target-branch: $GITHUB_REF",
        "release-type: node",
    ],
)
def test_release_please_unknown_effective_configuration_fails_closed(
    tmp_path: Path, alternative: str
) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid)
    path = tmp_path / ".github" / "workflows" / "test.yml"
    path.write_text(path.read_text() + f"          {alternative}\n", encoding="utf-8")
    entries = inventory(tmp_path)
    assert len(entries) == 1
    assert entries[0].target_state == "published"
    assert len(validate(entries, [])) == 1


def test_release_please_multifamily_draft_does_not_open_unknown_tag_window(
    tmp_path: Path,
) -> None:
    valid = {"draft": True, "force-tag-creation": True, "packages": {".": {}}}
    _release_please_fixture(tmp_path, valid)
    path = tmp_path / ".github" / "workflows" / "test.yml"
    path.write_text(
        path.read_text() + "      - run: gh release upload v1.0.0 x.tgz\n",
        encoding="utf-8",
    )
    entries = inventory(tmp_path)
    assert [(x.kind, x.target_state) for x in entries] == [
        ("create_release", "draft"),
        ("upload_asset", "published"),
    ]
    assert len(validate(entries, [])) == 1


@pytest.mark.parametrize(
    ("create_tag", "upload_tag"),
    [
        ('"$TAG"', '"$TAG"'),
        ('"$TAG"', "v1"),
        ("v1", "v2"),
        ("v1", '"$TAG"'),
    ],
)
def test_unknown_or_mismatched_draft_tag_cannot_authorize_upload(
    tmp_path: Path, create_tag: str, upload_tag: str
) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            f"gh release create {create_tag} --draft\ngh release upload {upload_tag} x.tgz"
        ),
    )
    entries = inventory(tmp_path)
    assert [(x.kind, x.target_state) for x in entries] == [
        ("create_release", "draft"),
        ("upload_asset", "published"),
    ]
    assert len(validate(entries, [])) == 1


def test_matching_literal_tag_upload_allowed_but_wrong_tag_closes_window(
    tmp_path: Path,
) -> None:
    _write_workflow(
        tmp_path,
        _single_step_workflow(
            "gh release create v1 --draft\n"
            "gh release upload v1 a.tgz\n"
            "gh release upload v2 wrong.tgz\n"
            "gh release upload v1 later.tgz"
        ),
    )
    entries = inventory(tmp_path)
    assert [entry.target_state for entry in entries] == [
        "draft",
        "draft",
        "published",
        "published",
    ]
    assert len(validate(entries, [])) == 2
