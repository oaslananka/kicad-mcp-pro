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


class _UniqueMappingLoader(yaml.SafeLoader):
    """Preserve safe YAML construction while rejecting duplicate mappings."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        keys: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in keys:
                raise ValueError(f"duplicate YAML mapping key: {key!r}")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _events(workflow: Path) -> dict[str, Any]:
    # PyYAML's YAML 1.1 resolver parses GitHub's 'on' key as boolean True.
    loader = _UniqueMappingLoader(workflow.read_text(encoding="utf-8"))
    try:
        document = loader.get_single_data()
    finally:
        loader.dispose()
    if isinstance(document, dict) and True in document and "on" in document:
        raise ValueError("duplicate GitHub workflow on event mapping")
    events = document.get(True, document.get("on")) if isinstance(document, dict) else None
    if not isinstance(events, dict):
        raise ValueError(f"{workflow.name}: missing workflow event mapping")
    return events


def _publisher_trigger_errors(root: Path) -> list[str]:
    """Require one explicit draft owner instead of automatic publisher events."""
    errors: list[str] = []
    allowed_events = {"workflow_call", "workflow_dispatch", "pull_request"}
    for filename in _PUBLISHERS:
        path = root / ".github" / "workflows" / filename
        try:
            events = _events(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"{filename}: {exc}")
            continue
        if "workflow_call" not in events:
            errors.append(f"{filename}: draft-first publishers require workflow_call")
        for event in sorted(set(events) - allowed_events):
            errors.append(f"{filename}: remove autonomous {event} trigger before draft cutover")
    return errors


def _legacy_mutation_errors(root: Path, policy: dict[str, Any] | None) -> list[str]:
    """Use the same effective release mutation allowlist as the policy validator."""
    if policy is None:
        try:
            policy = json.loads(
                (root / ".github" / "actions-policy.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            return [f"draft cutover cannot read release mutation policy: {exc}"]
    if not isinstance(policy, dict):
        return ["draft cutover: release mutation policy must be an object"]
    mutations = policy.get("release_asset_mutations", [])
    if not isinstance(mutations, list):
        return ["draft cutover: release_asset_mutations must be a list"]
    if mutations:
        return ["draft cutover requires retiring all legacy published-release mutation allowances"]
    return []


def validate_cutover(root: Path, policy: dict[str, Any] | None = None) -> list[str]:
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

    errors.extend(_publisher_trigger_errors(root))
    errors.extend(_legacy_mutation_errors(root, policy))

    return errors
