from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts.dev_environment import (
    _doctor_payload,
    _install_node,
    _install_rust,
    build_bootstrap_plan,
    ci_quality_gate_commands,
    download_verified,
    evaluate_development_policy,
    main,
    prepare_environment,
    safe_extract_tar,
)

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_plan_is_repository_scoped_and_exact() -> None:
    plan = build_bootstrap_plan(ROOT, core_only=False)

    assert plan.root == ROOT
    assert plan.install_optional is True
    assert plan.versions == {
        "node": "24.11.0",
        "pnpm": "11.5.0",
        "python": "3.13.12",
        "rust": "1.97.1",
        "rustup": "1.29.0",
        "task": "3.52.0",
        "uv": "0.11.31",
    }
    for path in (plan.cache_root, plan.tool_root, plan.venv_root, plan.environment_file):
        assert path == ROOT or ROOT in path.parents


def test_bootstrap_plan_core_only_keeps_optional_tools_explicit() -> None:
    plan = build_bootstrap_plan(ROOT, core_only=True)

    assert plan.install_optional is False
    assert plan.optional_tools == ("cargo", "rustc", "task")
    assert plan.required_tools == ("node", "pnpm", "python", "uv")


def test_download_verified_rejects_checksum_mismatch(tmp_path: Path) -> None:
    payload = b"verified payload"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    destination = tmp_path / "destination.bin"

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_verified(source.as_uri(), destination, "0" * 64)

    assert not destination.exists()

    download_verified(source.as_uri(), destination, hashlib.sha256(payload).hexdigest())
    assert destination.read_bytes() == payload


def test_safe_extract_tar_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "hostile.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 6
        bundle.addfile(info, io.BytesIO(b"escape"))

    with pytest.raises(ValueError, match="outside destination"):
        safe_extract_tar(archive, tmp_path / "extract")

    assert not (tmp_path / "escape.txt").exists()


def test_bootstrap_cli_plan_and_missing_check_are_machine_readable(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "bootstrap-dev.sh"
    bash = shutil.which("bash")
    assert bash is not None
    plan = subprocess.run(
        [bash, str(script), "--plan", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(plan.stdout)
    assert payload["versions"]["python"] == "3.13.12"
    assert payload["installOptional"] is True

    check = subprocess.run(
        [bash, str(script), "--check", "--json", "--root", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 2
    check_payload = json.loads(check.stdout)
    assert check_payload["ok"] is False
    assert check_payload["status"] == "not-prepared"


def test_bootstrap_wrapper_never_elevates_or_pipes_remote_shell() -> None:
    script = (ROOT / "scripts" / "bootstrap-dev.sh").read_text(encoding="utf-8")
    assert "sudo" not in script
    assert "curl |" not in script
    assert "curl -" not in script


def test_package_and_taskfile_expose_bootstrap_commands() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")

    assert package["scripts"]["dev:bootstrap"] == "./scripts/bootstrap-dev.sh"
    assert package["scripts"]["dev:doctor"] == (
        "uv run --all-extras python scripts/dev_environment.py --doctor"
    )
    assert "dev:bootstrap:" in taskfile
    assert "dev:doctor:" in taskfile


def test_safe_extract_tar_allows_internal_symlink_but_rejects_escape(tmp_path: Path) -> None:
    safe_archive = tmp_path / "safe-links.tar.gz"
    with tarfile.open(safe_archive, "w:gz") as bundle:
        target = tarfile.TarInfo("package/lib/cli.js")
        target.size = 3
        bundle.addfile(target, io.BytesIO(b"cli"))
        link = tarfile.TarInfo("package/bin/tool")
        link.type = tarfile.SYMTYPE
        link.linkname = "../lib/cli.js"
        bundle.addfile(link)

    safe_root = tmp_path / "safe"
    safe_extract_tar(safe_archive, safe_root)
    assert (safe_root / "package/bin/tool").resolve() == (safe_root / "package/lib/cli.js")

    hostile_archive = tmp_path / "hostile-links.tar.gz"
    with tarfile.open(hostile_archive, "w:gz") as bundle:
        link = tarfile.TarInfo("package/bin/tool")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../escape"
        bundle.addfile(link)

    with pytest.raises(ValueError, match="outside destination"):
        safe_extract_tar(hostile_archive, tmp_path / "hostile")


def test_safe_extract_tar_uses_callable_cross_version_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "node-links.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        target = tarfile.TarInfo("node/lib/node_modules/npm/bin/npm-cli.js")
        target.size = 3
        bundle.addfile(target, io.BytesIO(b"cli"))
        link = tarfile.TarInfo("node/bin/npm")
        link.type = tarfile.SYMTYPE
        link.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        bundle.addfile(link)

    filters: list[object] = []
    original_extractall = tarfile.TarFile.extractall

    def recording_extractall(
        bundle: tarfile.TarFile,
        path: str | Path = ".",
        members: object = None,
        *,
        numeric_owner: bool = False,
        filter: object = None,
    ) -> None:
        filters.append(filter)
        original_extractall(
            bundle,
            path,
            members,
            numeric_owner=numeric_owner,
            filter=filter,
        )

    monkeypatch.setattr(tarfile.TarFile, "extractall", recording_extractall)

    safe_extract_tar(archive, tmp_path / "extract")

    assert len(filters) == 1
    assert callable(filters[0])


def test_safe_extract_tar_rejects_special_files(tmp_path: Path) -> None:
    archive = tmp_path / "special.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        fifo = tarfile.TarInfo("package/unsafe-fifo")
        fifo.type = tarfile.FIFOTYPE
        bundle.addfile(fifo)

    with pytest.raises(ValueError, match="Unsupported archive member"):
        safe_extract_tar(archive, tmp_path / "extract")


def test_node_install_preserves_archive_symlinks(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "archive-root"
    node_root = source_root / "node-v24.11.0-linux-x64"
    (node_root / "bin").mkdir(parents=True)
    cli = node_root / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    (node_root / "bin" / "node").write_text("node", encoding="utf-8")
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (node_root / "bin" / "npm").symlink_to("../lib/node_modules/npm/bin/npm-cli.js")
    archive = tmp_path / "node.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        bundle.add(node_root, arcname=node_root.name, recursive=True)

    target_root = tmp_path / "checkout"
    plan = build_bootstrap_plan(target_root, core_only=True, contract_root=ROOT)

    def copy_archive(_url: str, destination: Path, _sha256: str) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read_bytes())
        return destination

    monkeypatch.setattr("scripts.dev_environment.download_verified", copy_archive)
    installed = _install_node(plan, "x86_64")

    assert (installed / "bin" / "npm").is_symlink()
    assert (installed / "bin" / "npm").resolve() == (
        installed / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    )


def test_development_ci_policy_blocks_required_but_not_optional_or_live() -> None:
    development = {
        "available": True,
        "prepared": True,
        "frozen_python_ready": True,
        "frozen_node_ready": True,
        "roots": [
            {"name": "tools", "writable": True},
            {"name": "cache", "writable": True},
            {"name": "venv", "writable": True},
        ],
        "tools": [
            {"name": "python", "classification": "required", "status": "ok"},
            {"name": "task", "classification": "optional", "status": "missing"},
            {"name": "kicad-cli", "classification": "live-kicad", "status": "missing"},
        ],
    }
    policy = evaluate_development_policy(development)
    assert policy["ready"] is True
    assert policy["blocking"] == []
    assert {item["name"] for item in policy["limitations"]} == {"kicad-cli", "task"}

    development["tools"][0]["status"] = "version-mismatch"
    blocked = evaluate_development_policy(development)
    assert blocked["ready"] is False
    assert blocked["blocking"] == [
        {"name": "python", "reason": "required tool status is version-mismatch"}
    ]


def test_ci_quality_gate_commands_use_prepared_pnpm_and_cover_acceptance() -> None:
    plan = build_bootstrap_plan(ROOT, core_only=True)
    commands = ci_quality_gate_commands(plan)
    scripts = [command[-1] for command in commands]

    assert scripts == [
        "metadata:check",
        "format:check",
        "lint",
        "typecheck",
        "test:unit",
        "package:check",
    ]
    expected_pnpm = ROOT / ".dev-tools" / "pnpm" / "11.5.0" / "bin" / "pnpm"
    assert all(Path(command[0]) == expected_pnpm for command in commands)


def test_dev_doctor_cli_accepts_pnpm_argument_separator(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.dev_environment._doctor_payload",
        lambda _plan: {
            "status": "degraded",
            "development": {"capability_mode": "core-only"},
            "developmentPolicy": {"ready": True, "blocking": [], "limitations": []},
        },
    )

    result = main(["--doctor", "--", "--json", "--ci"])

    assert result == 0
    assert json.loads(capsys.readouterr().out)["developmentPolicy"]["ready"] is True


def test_doctor_payload_keeps_probe_logs_out_of_machine_output(
    monkeypatch,
    capsys,
) -> None:
    plan = build_bootstrap_plan(ROOT, core_only=True)

    class FakeReport:
        def model_dump(self, **_kwargs: object) -> dict[str, object]:
            return {
                "status": "degraded",
                "development": {
                    "available": True,
                    "prepared": True,
                    "frozen_python_ready": True,
                    "frozen_node_ready": True,
                    "roots": [],
                    "tools": [],
                },
            }

    def noisy_report():
        print("probe log must not corrupt JSON")
        return FakeReport()

    monkeypatch.setattr("kicad_mcp.diagnostics.build_doctor_report", noisy_report)

    payload = _doctor_payload(plan)

    assert payload["status"] == "degraded"
    assert capsys.readouterr().out == ""


def test_prepare_environment_installs_uv_and_uvx_from_pinned_archive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan = build_bootstrap_plan(tmp_path / "checkout", core_only=True, contract_root=ROOT)
    installed: list[str] = []

    def fake_archive_install(_plan: object, **kwargs: str) -> Path:
        installed.append(kwargs["binary_name"])
        return tmp_path / kwargs["binary_name"]

    monkeypatch.setattr("scripts.dev_environment._host_architecture", lambda: "x86_64")
    monkeypatch.setattr("scripts.dev_environment._install_archive_binary", fake_archive_install)
    monkeypatch.setattr("scripts.dev_environment._install_node", lambda *_args: tmp_path / "node")
    monkeypatch.setattr(
        "scripts.dev_environment._install_pnpm",
        lambda *_args, **_kwargs: tmp_path / "pnpm",
    )
    monkeypatch.setattr("scripts.dev_environment._run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts.dev_environment._write_environment_file", lambda _plan: None)
    monkeypatch.setattr(
        "scripts.dev_environment.check_prepared_environment",
        lambda _plan: {"ok": True, "status": "ready", "tools": {}},
    )

    result = prepare_environment(plan)

    assert result["ok"] is True
    assert installed == ["uv", "uvx"]


def test_ci_bootstrap_runs_doctor_with_prepared_python(monkeypatch, capsys) -> None:
    doctor_payload = {
        "status": "degraded",
        "development": {"capabilityMode": "core-only"},
        "developmentPolicy": {"ready": True, "blocking": [], "limitations": []},
    }
    commands: list[list[str]] = []

    monkeypatch.setattr(
        "scripts.dev_environment.prepare_environment",
        lambda _plan, *, capture: {"ok": True, "status": "ready", "tools": {}},
    )
    monkeypatch.setattr(
        "scripts.dev_environment._doctor_payload",
        lambda _plan: pytest.fail("bootstrap must not import doctor with the system Python"),
    )
    monkeypatch.setattr("scripts.dev_environment.run_ci_quality_gates", lambda _plan: [])

    def fake_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(doctor_payload),
            stderr="",
        )

    monkeypatch.setattr("scripts.dev_environment._run", fake_run)

    result = main(["--ci", "--json", "--core-only"])

    assert result == 0
    assert commands
    assert Path(commands[0][0]) == ROOT / ".venv" / "bin" / "python"
    assert commands[0][1:] == [
        str(ROOT / "scripts" / "dev_environment.py"),
        "--doctor",
        "--json",
        "--ci",
        "--root",
        str(ROOT),
    ]
    assert json.loads(capsys.readouterr().out)["doctor"] == doctor_payload


def test_main_requests_captured_subprocess_output_for_json(monkeypatch, capsys) -> None:
    captured: list[bool] = []

    def fake_prepare(_plan, *, capture: bool):
        captured.append(capture)
        return {"ok": True, "status": "ready", "tools": {}}

    monkeypatch.setattr("scripts.dev_environment.prepare_environment", fake_prepare)

    result = main(["--json", "--core-only"])

    assert result == 0
    assert captured == [True]
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_existing_rust_toolchain_still_repairs_required_rustfmt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan = build_bootstrap_plan(tmp_path / "checkout", core_only=False, contract_root=ROOT)
    rustc = plan.tool_root / "cargo" / "bin" / "rustc"
    rustup = plan.tool_root / "cargo" / "bin" / "rustup"
    rustc.parent.mkdir(parents=True)
    rustc.write_text("rustc", encoding="utf-8")
    rustup.write_text("rustup", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="rustc 1.97.1", stderr="")

    monkeypatch.setattr("scripts.dev_environment._run", fake_run)

    _install_rust(plan, "x86_64", {}, capture=True)

    assert [str(rustup), "component", "add", "rustfmt", "--toolchain", "1.97.1"] in commands
