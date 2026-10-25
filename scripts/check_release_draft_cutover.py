"""Fail closed when a draft-first release cutover is only partially wired.

This validates *necessary* workflow boundaries, not runtime publication readiness.
The existing published-first release flow remains permitted until the complete
draft-first migration passes the protected workflow policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

# These jobs currently publish via release:published or tag push. In draft-first
# mode they must become owner-invoked reusable workflows, not autonomous writers.
_PUBLISHERS = (
    "publish-python.yml",
    "publish-npm.yml",
    "publish-mcpb.yml",
    "publish-protocol-schemas.yml",
    "publish-kicad-pcm.yml",
    "publish-mcp-container.yml",
    "publish-mcp-registry.yml",
    "gui-release.yml",
)


def _events(workflow: Path) -> dict[str, Any]:
    # PyYAML's YAML 1.1 resolver parses GitHub's 'on' key as boolean True.
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    events = document.get(True, document.get("on")) if isinstance(document, dict) else None
    if not isinstance(events, dict):
        raise ValueError(f"{workflow.name}: missing workflow event mapping")
    return events


def validate_cutover(root: Path) -> list[str]:
    """Reject a partial draft-first switch without changing release state."""
    try:
        config = json.loads((root / "release-please-config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"release-please-config.json: cannot read draft cutover configuration: {exc}"]
    if not isinstance(config, dict) or not isinstance(config.get("packages"), dict):
        return ["release-please-config.json: packages must be an object"]
    packages = [
        (path, settings)
        for path, settings in config["packages"].items()
        if isinstance(settings, dict)
        and settings.get("skip-github-release", config.get("skip-github-release")) is not True
    ]
    if not packages:
        return ["release-please-config.json: no release-producing packages"]

    modes = [
        (
            settings.get("draft", config.get("draft", False)),
            settings.get("force-tag-creation", config.get("force-tag-creation", False)),
        )
        for _, settings in packages
    ]
    # No change in behavior for the current published-first, tagged Release path.
    if all(draft is not True for draft, _ in modes):
        return []

    errors: list[str] = []
    if any(draft is not True or force is not True for draft, force in modes):
        errors.append(
            "draft cutover requires draft=true and force-tag-creation=true "
            "for every release-producing package, with no mixed-mode releases"
        )

    for filename in _PUBLISHERS:
        path = root / ".github" / "workflows" / filename
        try:
            events = _events(path)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if "workflow_call" not in events:
            errors.append(f"{filename}: draft-first publishers require workflow_call")
        if "release" in events:
            errors.append(
                f"{filename}: remove autonomous release event publication before draft cutover"
            )
        push = events.get("push")
        if isinstance(push, dict) and "tags" in push:
            errors.append(
                f"{filename}: remove autonomous tag-push publication before draft cutover"
            )

    try:
        policy = json.loads((root / ".github" / "actions-policy.json").read_text(encoding="utf-8"))
        old_mutations = policy.get("release_asset_mutations", [])
    except (OSError, ValueError, AttributeError) as exc:
        errors.append(f"draft cutover cannot read release mutation policy: {exc}")
    else:
        if old_mutations:
            errors.append(
                "draft cutover requires retiring all 9 legacy published-release mutation allowances"
            )

    return errors
