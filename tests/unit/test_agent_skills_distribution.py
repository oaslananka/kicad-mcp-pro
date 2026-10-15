"""Validate portable skills and client examples without launching external agents."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts import sync_agent_skills as skill_sync

ROOT = Path(__file__).resolve().parents[2]


def test_all_generated_skill_trees_match_authoritative_sources() -> None:
    module = skill_sync
    assert module.run(write=False) == 0
    generated = module.expected_skill_files()
    assert len(generated) >= 24
    for path, content in generated.items():
        assert path.read_bytes() == content
    canonical = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    assert canonical == set(module.SKILLS)


def test_mirrored_wired_subcircuit_reference_has_portable_gallery_link() -> None:
    reference = (
        "https://github.com/oaslananka/kicad-mcp-pro/blob/main/"
        "examples/gallery/esp32-c3-wroom-02-breakout/README.md"
    )
    assert (ROOT / "examples/gallery/esp32-c3-wroom-02-breakout/README.md").is_file()
    hosts = (ROOT / "skills", *skill_sync.HOST_ROOTS)
    for root in hosts:
        content = (root / "wired-subcircuit-design/SKILL.md").read_text(encoding="utf-8")
        assert f"]({reference})" in content
        assert "../../examples/gallery/" not in content


def test_skills_preserve_fail_closed_mcp_mutation_guards() -> None:
    for host in (ROOT / "skills", ROOT / ".opencode/skills", ROOT / ".agents/skills"):
        text = (host / "pcb-design/SKILL.md").read_text(encoding="utf-8")
        assert "pcb_delete_items" in text
        assert "pcb_delete_object" in text
        assert "Do **not** rewrite `.kicad_pcb` or `.kicad_sch`" in text
        assert "required MCP mutation tool is unavailable" in text


def test_invalid_frontmatter_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = skill_sync
    canonical = tmp_path / "skills"
    canonical.mkdir()
    (canonical / "bad").mkdir()
    (canonical / "bad/SKILL.md").write_text("# No frontmatter", encoding="utf-8")
    monkeypatch.setattr(module, "CANONICAL", canonical)
    monkeypatch.setattr(module, "SKILLS", ("bad",))
    with pytest.raises(ValueError, match="frontmatter"):
        module.expected_skill_files()


def test_codex_examples_have_valid_map_named_mcp_servers() -> None:
    examples = [
        ROOT / ".codex/config.example.toml",
        ROOT / "integrations/codex/config.toml.example",
        ROOT / "docs/examples/clients/codex-config.toml",
        ROOT / "docs/examples/clients/codex-http-config.toml",
    ]
    for path in examples:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        servers = data["mcp_servers"]
        assert isinstance(servers, dict), path
        assert set(servers) == {"kicad"}, path
        server = servers["kicad"]
        assert "default_tools_approval_mode" not in server
        assert "cwd" not in server
        assert server.get("command") == "uvx" or server.get("url", "").startswith(
            "http://127.0.0.1:"
        )
        if "env" in server:
            assert server["env"]["KICAD_MCP_OPERATING_MODE"] == "readonly"


def test_claude_manifest_and_copilot_instructions_match_installed_features() -> None:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert "mcpServers" not in plugin  # A skill-only manifest does NOT install an MCP server.
    for name in plugin["skills"]:
        assert (ROOT / name / "SKILL.md").is_file()
    assert (ROOT / ".mcp.json").is_file()
    entry = (ROOT / ".github/copilot-instructions.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in entry
    assert ".agents/skills/" in entry
    assert "Do not" in entry


def test_portable_skill_manifest_is_valid_yaml_and_distinct() -> None:
    names: set[str] = set()
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        _, frontmatter, _ = path.read_text(encoding="utf-8").split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert metadata["name"] == path.parent.name
        assert metadata["description"]
        assert metadata["name"] not in names
        names.add(metadata["name"])
    assert len(names) == 7


def _temporary_skill_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    canonical = tmp_path / "skills"
    source = canonical / "pcb-design"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: pcb-design\ndescription: PCB review and guarded design.\n---\n"
        "# PCB review\nNever mutate without approval.\n",
        encoding="utf-8",
    )
    (source / "references").mkdir()
    (source / "references" / "notes.md").write_text("# Reference\n", encoding="utf-8")
    first = tmp_path / ".opencode" / "skills"
    second = tmp_path / ".agents" / "skills"
    monkeypatch.setattr(skill_sync, "ROOT", tmp_path)
    monkeypatch.setattr(skill_sync, "CANONICAL", canonical)
    monkeypatch.setattr(skill_sync, "HOST_ROOTS", (first, second))
    monkeypatch.setattr(skill_sync, "SKILLS", ("pcb-design",))
    return canonical, first, second


def test_check_write_refresh_and_remove_stale_skill_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, first, second = _temporary_skill_mirror(tmp_path, monkeypatch)
    assert skill_sync.run(write=False) == 1
    assert skill_sync.run(write=True) == 0
    assert skill_sync.run(write=False) == 0
    for root in (first, second):
        assert (root / "pcb-design/references/notes.md").read_text() == "# Reference\n"
    (first / "pcb-design/SKILL.md").write_text("tampered", encoding="utf-8")
    old = first / "pcb-design/obsolete" / "old.txt"
    old.parent.mkdir()
    old.write_text("stale", encoding="utf-8")
    (canonical / "pcb-design/SKILL.md").write_text(
        "---\nname: pcb-design\ndescription: New description.\n---\n# Updated\n",
        encoding="utf-8",
    )
    assert skill_sync.run(write=False) == 1
    assert old.is_file()
    assert skill_sync.run(write=True) == 0
    assert not old.exists()
    assert not old.parent.exists()
    assert skill_sync.run(write=False) == 0
    assert "# Updated" in (second / "pcb-design/SKILL.md").read_text()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("---\nname: wrong\ndescription: valid\n---\n", "identity"),
        ("---\nname: pcb-design\ndescription: ''\n---\n", "identity"),
        ("---\nname: pcb-design\ndescription: valid", "not enough values"),
    ],
)
def test_skill_metadata_rejects_incorrect_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str, reason: str
) -> None:
    canonical, _, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    (canonical / "pcb-design/SKILL.md").write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError), match=reason):
        skill_sync.expected_skill_files()


def test_skips_private_payloads_in_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical, first, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    (canonical / "pcb-design/.secret").write_text("should not ship", encoding="utf-8")
    skill_sync.run(write=True)
    assert not (first / "pcb-design/.secret").exists()


def test_target_symlink_fails_closed_if_platform_supports_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, first, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    target = first / "pcb-design/SKILL.md"
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(canonical / "pcb-design/SKILL.md")
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.run(write=True)


def test_source_symlink_fails_closed_if_platform_supports_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, _, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    target = canonical / "pcb-design/ref.md"
    try:
        target.symlink_to(canonical / "pcb-design/SKILL.md")
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.expected_skill_files()


def test_cli_requires_explicit_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    _temporary_skill_mirror(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["sync_agent_skills.py"])
    with pytest.raises(SystemExit):
        skill_sync.main()
    monkeypatch.setattr(sys, "argv", ["sync_agent_skills.py", "--write"])
    assert skill_sync.main() == 0
    monkeypatch.setattr(sys, "argv", ["sync_agent_skills.py", "--check"])
    assert skill_sync.main() == 0


def test_availability_helper_does_not_execute_discovered_binary(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Skill discovery preflight must not execute a PATH-resolved program."""
    import importlib.util
    import shutil

    path = ROOT / "skills/kicad-design-review/scripts/check_mcp_available.py"
    spec = importlib.util.spec_from_file_location("kicad_skill_availability", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/untrusted/bin" if name == "kicad-mcp-pro" else None
    )
    assert module.main() == 0
    assert "runtime not yet verified" in capsys.readouterr().out
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert module.main() == 1
    assert "not found" in capsys.readouterr().out
    assert "subprocess" not in path.read_text(encoding="utf-8")


def test_symlinked_mirror_root_rejected_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, first, second = _temporary_skill_mirror(tmp_path, monkeypatch)
    external = tmp_path / "external"
    external.mkdir()
    first.parent.mkdir(parents=True, exist_ok=True)
    try:
        first.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows directory symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.run(write=True)
    assert not list(external.iterdir())
    assert not (second / "pcb-design/SKILL.md").exists()


def test_symlinked_nested_target_parent_rejected_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, first, second = _temporary_skill_mirror(tmp_path, monkeypatch)
    external = tmp_path / "external"
    external.mkdir()
    nested = first / "pcb-design/references"
    nested.parent.mkdir(parents=True)
    try:
        nested.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows directory symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.run(write=True)
    assert not list(external.iterdir())
    assert not (second / "pcb-design/SKILL.md").exists()


def test_symlinked_canonical_directory_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, _, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    original = canonical / "pcb-design"
    destination = tmp_path / "external-source"
    original.rename(destination)
    try:
        original.symlink_to(destination, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows directory symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.expected_skill_files()


def test_symlinked_canonical_nested_directory_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical, _, _ = _temporary_skill_mirror(tmp_path, monkeypatch)
    external = tmp_path / "external-source"
    external.mkdir()
    linked = canonical / "pcb-design/external-reference"
    try:
        linked.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem disallows directory symlink creation")
    with pytest.raises(ValueError, match="symlink"):
        skill_sync.expected_skill_files()
