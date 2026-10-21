from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APT_GUARD = "sudo rm -f /etc/apt/sources.list.d/google-chrome.{list,sources}"

CASES = [
    ("gui-ci.yml", "Install Playwright browsers", "playwright install --with-deps chromium"),
    ("gui-ci.yml", "Install Linux Tauri dependencies", "sudo apt-get update"),
    ("gui-release.yml", "Install Linux Tauri dependencies", "sudo apt-get update"),
    ("kicad-live-e2e.yml", "Install KiCad nightly preview CLI", "sudo add-apt-repository"),
]


def _named_step(workflow: str, step_name: str) -> str:
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    marker = f"- name: {step_name}"
    start = text.index(marker)
    next_step = text.find("\n      - name:", start + len(marker))
    return text[start : next_step if next_step != -1 else len(text)]


def test_ubuntu_package_steps_ignore_unrelated_google_chrome_repository() -> None:
    for workflow, step_name, package_command in CASES:
        block = _named_step(workflow, step_name)
        assert APT_GUARD in block, f"{workflow}: {step_name} lacks apt source guard"
        assert block.index(APT_GUARD) < block.index(package_command)


def test_pinned_kicad_appimage_steps_do_not_invoke_apt() -> None:
    for workflow, step_name in (
        ("dev-bootstrap.yml", "Install KiCad 10.0.6 CLI"),
        ("kicad-live-e2e.yml", "Install KiCad 10.0.x CLI"),
    ):
        block = _named_step(workflow, step_name)
        assert "bash scripts/ci/install_kicad_10_0_6_appimage.sh" in block
        assert "sudo" not in block
        assert "apt-get" not in block
