from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import install_git_hooks


@dataclass(frozen=True)
class _Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _Harness:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        git_dir: str = ".git",
        common_dir: str = ".git",
        effective_hooks: str = "",
        local_hooks: str = "",
        worktree_hooks: str = "",
        worktree_config: str = "",
    ) -> None:
        (tmp_path / ".git").mkdir(exist_ok=True)
        monkeypatch.setattr(install_git_hooks, "ROOT", tmp_path)
        self.calls: list[list[str]] = []
        self.values = {
            ("rev-parse", "--git-dir"): git_dir,
            ("rev-parse", "--git-common-dir"): common_dir,
            ("config", "--get", "core.hooksPath"): effective_hooks,
            ("config", "--local", "--get", "core.hooksPath"): local_hooks,
            ("config", "--get", "extensions.worktreeConfig"): worktree_config,
            ("config", "--global", "--get", "core.hooksPath"): "",
            ("config", "--worktree", "--get", "core.hooksPath"): worktree_hooks,
        }

        def fake_git_output(arguments: list[str], *, scope_optional: bool = False) -> str:
            del scope_optional
            return self.values[tuple(arguments)]

        def fake_run(command: list[str], *, check: bool = True) -> _Result:
            del check
            self.calls.append(command)
            return _Result()

        monkeypatch.setattr(install_git_hooks, "_git_output", fake_git_output)
        monkeypatch.setattr(install_git_hooks, "_run", fake_run)
        monkeypatch.setattr(
            install_git_hooks,
            "_lefthook_command",
            lambda *args: ["lefthook", *args],
        )


@pytest.fixture
def harness_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Harness]:
    def build(**kwargs: str) -> _Harness:
        return _Harness(tmp_path, monkeypatch, **kwargs)

    return build


def test_normal_clone_without_custom_hooks_path_uses_plain_install(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory()

    install_git_hooks.install()

    assert ["lefthook", "install"] in harness.calls
    assert ["lefthook", "check-install"] in harness.calls
    assert not any(call[:3] == ["git", "config", "--local"] for call in harness.calls)


def test_normal_clone_overrides_global_hooks_path_locally(
    harness_factory: Callable[..., _Harness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = harness_factory(effective_hooks="/home/example/.git-hooks")

    install_git_hooks.install()

    assert [
        "git",
        "config",
        "--local",
        "core.hooksPath",
        str((install_git_hooks.ROOT / ".git" / "hooks").resolve()),
    ] in harness.calls
    assert ["lefthook", "install", "--force"] in harness.calls
    assert ["lefthook", "check-install"] in harness.calls
    assert not any(call[:3] == ["git", "config", "--global"] for call in harness.calls)
    assert "preserving global core.hooksPath" in capsys.readouterr().out


def test_custom_repository_hooks_path_is_not_overwritten(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness_factory(
        effective_hooks="custom-hooks",
        local_hooks="custom-hooks",
    )

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        install_git_hooks.install()


def test_primary_worktree_scopes_override_without_touching_shared_git(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(effective_hooks="/home/example/.git-hooks", worktree_config="true")
    install_git_hooks.install()
    expected = str((install_git_hooks.ROOT / ".git" / "hooks").resolve())
    assert ["git", "config", "--worktree", "core.hooksPath", expected] in harness.calls
    assert not any(call[:3] == ["git", "config", "--local"] for call in harness.calls)
    assert ["lefthook", "install", "--force"] in harness.calls


def test_linked_worktree_can_install_without_mutating_other_worktrees(
    tmp_path: Path, harness_factory: Callable[..., _Harness]
) -> None:
    git_dir = tmp_path / "common" / "worktrees" / "topic"
    git_dir.mkdir(parents=True)
    harness = harness_factory(
        git_dir=str(git_dir),
        common_dir=str(tmp_path / "common"),
        effective_hooks="/home/example/.git-hooks",
        worktree_config="true",
    )
    install_git_hooks.install()
    assert [
        "git",
        "config",
        "--worktree",
        "core.hooksPath",
        str(git_dir / "hooks"),
    ] in harness.calls
    assert ["lefthook", "install", "--force"] in harness.calls
    assert not any(call[:3] == ["git", "config", "--local"] for call in harness.calls)


def test_linked_worktree_with_custom_hooks_path_fails_closed(
    tmp_path: Path,
    harness_factory: Callable[..., _Harness],
) -> None:
    git_dir = tmp_path / "common" / "worktrees" / "topic"
    common_dir = tmp_path / "common"
    git_dir.mkdir(parents=True)
    harness_factory(
        git_dir=str(git_dir),
        common_dir=str(common_dir),
        effective_hooks="/home/example/.git-hooks",
        worktree_config="true",
        worktree_hooks="/another/custom/path",
    )

    with pytest.raises(RuntimeError, match="worktree has a custom core.hooksPath"):
        install_git_hooks.install()


def test_global_commit_msg_is_preserved_without_modifying_the_original(
    tmp_path: Path,
) -> None:
    source = tmp_path / "global-hooks"
    source.mkdir()
    original = source / "commit-msg"
    original.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    original.chmod(0o700)
    new_dir = tmp_path / "worktree-hooks"
    install_git_hooks._preserve_global_commit_msg(str(source), new_dir)
    assert (new_dir / "commit-msg").is_symlink()
    assert (new_dir / "commit-msg").resolve() == original
    assert original.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    install_git_hooks._preserve_global_commit_msg(str(source), new_dir)
    assert (new_dir / "commit-msg").resolve() == original
