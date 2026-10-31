"""Explicit owner invocation never turns Cloud into automatic device access."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import multiprocessing
import os
import re
import select
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from kicad_mcp import cloud_local_registry, cloud_once
from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError, HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owner-key open is POSIX only")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
READ = "44444444-4444-4444-8444-444444444444"


def _keyfile(path: Path, *, other: bool = False) -> Path:
    key = (
        generate_private_key(public_exponent=65537, key_size=2048)
        if other
        else Ed25519PrivateKey.generate()
    )
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    path.chmod(0o600)
    if not other:
        from kicad_mcp.cloud_pair import _save_owner_binding

        der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        _save_owner_binding(
            path,
            origin="https://cloud.example",
            device_id=DEVICE,
            fingerprint=hashlib.sha256(der).hexdigest(),
        )
    return path


_CURRENT_LOCAL_FIXTURE: tuple[Path, Path] | None = None


_REAL_OWNER_AUTHORITY_GATE = cloud_once._require_independent_owner_authority


@pytest.fixture(autouse=True)
def _synthetic_registered_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unit tests of legacy auth/deadline logic use a test-only resolver.
    # The real registry permissions, tamper and identity checks are exercised
    # separately by test_cloud_local_registry.py.
    def fixture_resolve(**_kwargs: object) -> cloud_local_registry.LocalRegisteredRead:
        assert _CURRENT_LOCAL_FIXTURE is not None
        folder, key = _CURRENT_LOCAL_FIXTURE
        return cloud_local_registry.LocalRegisteredRead(key, folder, "demo")

    monkeypatch.setattr(cloud_local_registry, "resolve_registered_read", fixture_resolve)
    # Legacy isolated unit cases use a synthetic authority; NEVER a real grant.
    monkeypatch.setattr(cloud_once, "_require_independent_owner_authority", lambda: None)


def _args(folder: Path, key: Path) -> list[str]:
    global _CURRENT_LOCAL_FIXTURE
    _CURRENT_LOCAL_FIXTURE = (folder, key)
    return [
        "--cloud-origin",
        "https://cloud.example",
        "--owner-sub",
        "owner-fixture",
        "--device-id",
        DEVICE,
        "--project-id",
        PROJECT,
        "--allow-once",
    ]


def test_unverified_owner_gate_denies_before_registry_key_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A local PTY flag is not a remote-read authorization assertion."""
    args = _args(tmp_path, tmp_path / "enrolled.pem")
    monkeypatch.setattr(
        cloud_once, "_require_independent_owner_authority", _REAL_OWNER_AUTHORITY_GATE
    )
    monkeypatch.setattr(
        cloud_local_registry,
        "resolve_registered_read",
        lambda **_: pytest.fail("unverified read must not resolve owner files"),
    )
    monkeypatch.setattr(cloud_once, "_confirm_local_read", lambda *_: pytest.fail("do not prompt"))
    monkeypatch.setattr(
        cloud_once, "_load_bound_owner_key", lambda *_: pytest.fail("do not load key")
    )
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("do not connect"),
    )
    assert cloud_once.main(args) == 1
    assert "denied" in capsys.readouterr().err


def test_direct_one_shot_helper_denies_unverified_owner_before_key_or_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling the internal coroutine directly must not bypass the CLI stop gate."""
    options = cloud_once._parser().parse_args(_args(tmp_path, tmp_path / "owner.pem"))
    options.project_directory = tmp_path
    options.private_key_file = tmp_path / "owner.pem"
    monkeypatch.setattr(
        cloud_once, "_require_independent_owner_authority", _REAL_OWNER_AUTHORITY_GATE
    )
    monkeypatch.setattr(
        cloud_once,
        "_load_bound_owner_key",
        lambda *_: pytest.fail("direct helper must not load an owner key"),
    )
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("direct helper must not open a socket"),
    )
    lease = (time.time_ns() // 1_000_000 + 20_000, time.monotonic_ns() + 20_000_000_000)
    connection = cloud_once._connect(options, lease)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        asyncio.run(connection)


def test_no_consent_flag_never_loads_a_key_or_connects(tmp_path: Path) -> None:
    _raise_argument_1 = _args(tmp_path, tmp_path / "not-a-key")[:-1]
    with pytest.raises(SystemExit) as denied:
        cloud_once.main(_raise_argument_1)
    assert denied.value.code == 2


def test_terminal_consent_rejects_noninteractive_or_declined_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = argparse.Namespace(
        cloud_origin="https://cloud.example",
        owner_sub="owner-fixture",
        device_id=DEVICE,
        project_id=PROJECT,
        project_directory=tmp_path,
        filename_stem="demo",
        private_key_file=tmp_path / "owner.pem",
    )
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("no prompt for piped commands"))
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._confirm_local_read(options)


def _same_uid_pty_child(terminal: str, arguments: list[str]) -> None:
    """Attach a fresh Python test process to an actual pseudo-terminal."""
    fd = os.open(terminal, os.O_RDWR | os.O_NOCTTY)
    try:
        for stdfd in (0, 1, 2):
            os.dup2(fd, stdfd)
    finally:
        os.close(fd)
    sys.stdin = os.fdopen(0, "r", closefd=False)
    sys.stdout = os.fdopen(1, "w", buffering=1, closefd=False)
    sys.stderr = os.fdopen(2, "w", buffering=1, closefd=False)
    options = cloud_once._parser().parse_args(arguments)
    options.project_directory = Path.cwd()
    options.private_key_file = Path.cwd() / "synthetic.pem"
    options.filename_stem = "demo"
    cloud_once._confirm_local_read(options)
    print("SYNTHETIC_PTY_CONSENT_PASSED", flush=True)


def test_same_uid_pty_is_not_independent_human_approval(tmp_path: Path) -> None:
    """Prove that a separate same-UID process can satisfy the real PTY prompt.

    This is a threat-model finding, NOT proof of human authorization.
    No monkeypatch, private key, Cloud connection, or shell execution.
    """
    master_fd, slave_fd = os.openpty()
    child = multiprocessing.get_context("spawn").Process(
        target=_same_uid_pty_child,
        args=(os.ttyname(slave_fd), _args(tmp_path, tmp_path / "no-owner-key.pem")),
    )
    # Keep the slave endpoint open until the spawned child attaches; closing
    # it immediately can make the PTY master return EIO before startup.
    child.start()
    observed = b""
    try:
        deadline = time.monotonic() + 6.0
        challenge: re.Match[bytes] | None = None
        while time.monotonic() < deadline and challenge is None:
            readable, _, _ = select.select([master_fd], [], [], 0.2)
            if readable:
                observed += os.read(master_fd, 4096)
                challenge = re.search(
                    rb"Type APPROVE ([A-F0-9]{8}) to authorize exactly one read:",
                    observed,
                )
        assert challenge is not None, observed.decode("utf-8", errors="replace")
        os.write(master_fd, b"APPROVE " + challenge.group(1) + b"\n")
        child.join(timeout=5)
        assert child.exitcode == 0
        # The CLI accepted same-user PTY input without a real human.
        assert not (tmp_path / "no-owner-key.pem").exists()
    finally:
        if child.is_alive():
            child.kill()
        child.join(timeout=3)
        os.close(slave_fd)
        os.close(master_fd)


def test_unbound_owner_key_denied_before_private_key_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    keyfile = _keyfile(tmp_path / "unbound.pem")
    keyfile.with_name(keyfile.name + ".cloud-binding-v1.json").unlink()
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("unpaired key must never connect"),
    )
    assert cloud_once.main(_args(tmp_path, keyfile)) == 1
    assert "denied" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("--cloud-origin", "https://wrong.example"),
        ("--device-id", "55555555-5555-4555-8555-555555555555"),
    ],
)
def test_enrollment_pin_denies_another_cloud_or_device_before_key_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    override: str,
    value: str,
) -> None:
    keyfile = _keyfile(tmp_path / "enrolled.pem")
    args = _args(tmp_path, keyfile)
    args[args.index(override) + 1] = value
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr(cloud_once, "_load_owner_key", lambda *_: pytest.fail("do not open key"))
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("never connect to a substituted origin/device"),
    )
    assert cloud_once.main(args) == 1
    assert "denied" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["symlink", "world-readable", "duplicate-json", "mismatch"])
def test_enrollment_pin_rejects_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    keyfile = _keyfile(tmp_path / "enrolled.pem")
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    if kind == "symlink":
        copy = tmp_path / "copy.json"
        copy.write_bytes(binding.read_bytes())
        binding.unlink()
        binding.symlink_to(copy)
    elif kind == "world-readable":
        binding.chmod(0o644)
    elif kind == "duplicate-json":
        binding.write_text('{"origin":"https://cloud.example","origin":"https://other.example"}')
    else:
        value = json.loads(binding.read_text())
        value["fingerprint"] = "0" * 64
        binding.write_text(json.dumps(value))
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("invalid enrollment pin must not connect"),
    )
    assert cloud_once.main(_args(tmp_path, keyfile)) == 1
    assert "denied" in capsys.readouterr().err


def test_piped_cli_denied_before_private_key_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("must not prompt"))
    monkeypatch.setattr(
        cloud_once, "_load_owner_key", lambda *_: pytest.fail("denied before private key read")
    )
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("denied before any outbound connection"),
    )
    assert cloud_once.main(_args(tmp_path, tmp_path / "unavailable.pem")) == 1
    assert "denied" in capsys.readouterr().err


@pytest.mark.parametrize("reason", [EOFError, KeyboardInterrupt])
def test_aborted_terminal_confirmation_never_reads_owner_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: type[BaseException],
) -> None:
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(reason()))
    monkeypatch.setattr(
        cloud_once, "_load_owner_key", lambda *_: pytest.fail("key must stay unopened")
    )
    assert cloud_once.main(_args(tmp_path, tmp_path / "missing.pem")) == 1


def test_terminal_consent_requires_fresh_explicit_challenge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    options = argparse.Namespace(
        cloud_origin="https://cloud.example",
        owner_sub="owner-fixture",
        device_id=DEVICE,
        project_id=PROJECT,
        project_directory=tmp_path,
        filename_stem="demo",
        private_key_file=tmp_path / "owner.pem",
    )
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    responses = iter(["APPROVE expired", "APPROVE CAFEBABE"])
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._confirm_local_read(options)
    cloud_once._confirm_local_read(options)
    terminal = capsys.readouterr().out
    assert repr(str(options.project_directory)) in terminal
    displayed_lines = terminal.splitlines()
    assert f"Cloud origin: {options.cloud_origin!r}" in displayed_lines
    assert f"Project UUID: {options.project_id!r}" in displayed_lines
    assert f"Owner account: {options.owner_sub!r}" in displayed_lines
    assert f"Device UUID: {options.device_id!r}" in displayed_lines
    assert f"Owner key file: {str(options.private_key_file)!r}" in displayed_lines


def test_terminal_consent_declined_cannot_access_private_key_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "1234abcd")
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE wrong")
    monkeypatch.setattr(
        cloud_once, "_load_owner_key", lambda *_: pytest.fail("denied before key read")
    )
    monkeypatch.setattr(
        cloud_once,
        "execute_single_approved_read",
        lambda **_: pytest.fail("denied before network"),
    )
    assert cloud_once.main(_args(tmp_path, tmp_path / "unavailable.pem")) == 1
    assert "denied" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["owner-key", "pairing-binding"])
def test_owner_fifo_substitution_cannot_block_before_inode_validation(
    tmp_path: Path, target: str
) -> None:
    """The inode type check cannot protect an open() blocked on a FIFO."""
    keyfile = tmp_path / "owner.pem"
    if target == "owner-key":
        candidate = keyfile
        function = "_load_owner_key"
    else:
        _keyfile(keyfile)
        candidate = tmp_path / "owner.pem.cloud-binding-v1.json"
        candidate.unlink()
        function = "_read_owner_binding"
    os.mkfifo(candidate, mode=0o600)
    started = threading.Event()
    observed: list[str] = []

    def load() -> None:
        started.set()
        try:
            getattr(cloud_once, function)(keyfile)
        except cloud_once.LocalApprovalDeniedError:
            observed.append("denied")
        else:
            observed.append("unsafe accept")

    # A test-only daemon thread detects the potential blocked open. If
    # it blocks, the test opens the FIFO's other end to release it before
    # reporting failure; no child process or hung test runner is left.
    worker = threading.Thread(target=load, daemon=True)
    worker.start()
    assert started.wait(timeout=1.0)
    worker.join(timeout=0.75)
    blocked = worker.is_alive()
    if blocked:
        release_fd = os.open(candidate, os.O_RDWR | os.O_NONBLOCK)
        try:
            worker.join(timeout=1.0)
        finally:
            os.close(release_fd)
    assert not worker.is_alive(), "FIFO reader must be safely released"
    assert not blocked, "owner-only read must not block on a substituted FIFO"
    assert observed == ["denied"]


def test_owner_only_key_is_loaded_but_weak_or_unsafe_key_is_denied(tmp_path: Path) -> None:
    filename = _keyfile(tmp_path / "private.pem")
    assert isinstance(cloud_once._load_owner_key(filename), Ed25519PrivateKey)
    filename.chmod(0o644)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(filename)
    filename.chmod(0o600)
    link = tmp_path / "link.pem"
    link.symlink_to(filename)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(link)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(tmp_path / "missing.pem")
    filename.write_bytes(b"not a PEM")
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(filename)
    filename.write_bytes(b"a" * 9000)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(filename)
    _keyfile(filename, other=True)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._load_owner_key(filename)


def test_explicit_approval_uses_only_selected_project_and_file_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "owner-selected"
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text("never send this content")
    keyfile = _keyfile(tmp_path / "enrolled.pem")
    observations: list[str] = []

    async def fake_cloud(**kwargs: object) -> HandshakeReceipt:
        assert kwargs["origin"] == kwargs["trusted_origin"] == "https://cloud.example"
        assert kwargs["owner_sub"] == "owner-fixture"
        assert isinstance(kwargs["signing_key"], Ed25519PrivateKey)
        factory = kwargs["dispatcher_factory"]
        assert callable(factory)
        receipt = HandshakeReceipt(DEVICE, SESSION)
        dispatcher = factory(receipt)
        assert dispatcher._current_authorization() is True
        request = {
            "kind": "connector.read_request",
            "version": 1,
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "requestId": READ,
            "operation": "project_summary",
            "deadlineUnixMs": int(time.time() * 1000) + 1_000,
        }
        result = dispatcher.read(json.dumps(request).encode(), sequence=1)
        observations.append(json.dumps(result))
        dispatcher.close()
        _raise_argument_2 = json.dumps(request).encode()
        with pytest.raises(LocalReadDeniedError):
            dispatcher.read(_raise_argument_2, sequence=2)
        return receipt

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", fake_cloud)
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    assert cloud_once.main(_args(folder, keyfile)) == 0
    assert observations
    assert '"projectPresent": true' in observations[0]
    assert "never send this content" not in observations[0]
    assert str(folder) not in observations[0]
    assert "completed" in capsys.readouterr().out


def test_local_lease_expires_on_monotonic_clock_even_if_wall_clock_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "selected"
    folder.mkdir()
    (folder / "demo.kicad_pro").touch()
    keyfile = _keyfile(tmp_path / "enrolled.pem")
    clock = {"wall_ms": 1_800_000_000_000, "monotonic_ns": 100_000_000_000}
    monkeypatch.setattr(cloud_once.time, "time_ns", lambda: clock["wall_ms"] * 1_000_000)
    monkeypatch.setattr(cloud_once.time, "monotonic_ns", lambda: clock["monotonic_ns"])

    async def fake_cloud(**kwargs: object) -> HandshakeReceipt:
        factory = kwargs["dispatcher_factory"]
        assert callable(factory)
        receipt = HandshakeReceipt(DEVICE, SESSION)
        dispatcher = factory(receipt)

        def frame(request_id: str) -> bytes:
            return json.dumps(
                {
                    "kind": "connector.read_request",
                    "version": 1,
                    "deviceId": DEVICE,
                    "projectId": PROJECT,
                    "requestId": request_id,
                    "operation": "project_summary",
                    "deadlineUnixMs": clock["wall_ms"] + 1000,
                }
            ).encode()

        clock["wall_ms"] -= 5_000
        clock["monotonic_ns"] += 29_000_000_000
        assert dispatcher._current_authorization() is True
        assert dispatcher.read(frame(READ), sequence=1)["files"]["projectPresent"] is True
        clock["monotonic_ns"] += 1_000_000_000
        assert dispatcher._current_authorization() is False
        expired_frame = frame("66666666-6666-4666-8666-666666666666")
        with pytest.raises(LocalReadDeniedError):
            dispatcher.read(expired_frame, sequence=2)
        dispatcher.close()
        return receipt

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", fake_cloud)
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    assert cloud_once.main(_args(folder, keyfile)) == 0


def test_grant_clock_starts_when_local_foreground_consent_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = cloud_once._parser().parse_args(_args(tmp_path, tmp_path / "not-opened.pem"))
    options.project_directory = tmp_path
    options.private_key_file = tmp_path / "not-opened.pem"
    options.filename_stem = "demo"
    clocks = {"wall_ns": 1_800_000_000_000_000_000, "monotonic_ns": 100_000_000_000}
    monkeypatch.setattr(cloud_once.time, "time_ns", lambda: clocks["wall_ns"])
    monkeypatch.setattr(cloud_once.time, "monotonic_ns", lambda: clocks["monotonic_ns"])
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")

    def finish_user_consent(_prompt: str) -> str:
        clocks["wall_ns"] += 7_000_000_000
        clocks["monotonic_ns"] += 7_000_000_000
        return "APPROVE CAFEBABE"

    monkeypatch.setattr("builtins.input", finish_user_consent)
    wall_cutoff, monotonic_cutoff = cloud_once._confirm_local_read(options)
    assert wall_cutoff == clocks["wall_ns"] // 1_000_000 + 30_000
    assert monotonic_cutoff == clocks["monotonic_ns"] + 30_000_000_000


def test_slow_handshake_cannot_renew_the_original_local_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "approved"
    folder.mkdir()
    keyfile = _keyfile(tmp_path / "owner.pem")
    options = cloud_once._parser().parse_args(_args(folder, keyfile))
    options.project_directory = folder
    options.private_key_file = keyfile
    options.filename_stem = "demo"
    clocks = {"monotonic": 100_000_000_000}
    monkeypatch.setattr(cloud_once.time, "monotonic_ns", lambda: clocks["monotonic"])
    original_window = (1_800_000_030_000, clocks["monotonic"] + 30_000_000_000)

    async def slow_cloud(**kwargs: object) -> HandshakeReceipt:
        factory = kwargs["dispatcher_factory"]
        assert callable(factory)
        clocks["monotonic"] += 30_000_000_000
        receipt = HandshakeReceipt(DEVICE, SESSION)
        factory(receipt)
        return receipt

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", slow_cloud)
    connection = cloud_once._connect(options, original_window)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        asyncio.run(connection)


def test_one_shot_cli_grant_rejects_second_read_even_when_lease_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "selected"
    folder.mkdir()
    (folder / "demo.kicad_pro").touch()
    keyfile = _keyfile(tmp_path / "enrolled.pem")

    async def fake_cloud(**kwargs: object) -> HandshakeReceipt:
        factory = kwargs["dispatcher_factory"]
        assert callable(factory)
        receipt = HandshakeReceipt(DEVICE, SESSION)
        dispatcher = factory(receipt)
        deadline = int(time.time() * 1000) + 1000

        def frame(request_id: str) -> bytes:
            return json.dumps(
                {
                    "kind": "connector.read_request",
                    "version": 1,
                    "deviceId": DEVICE,
                    "projectId": PROJECT,
                    "requestId": request_id,
                    "operation": "project_summary",
                    "deadlineUnixMs": deadline,
                }
            ).encode()

        assert dispatcher.read(frame(READ), sequence=1)["files"]["projectPresent"] is True
        assert dispatcher._current_authorization() is True
        second_frame = frame("55555555-5555-4555-8555-555555555555")
        with pytest.raises(LocalReadDeniedError):
            dispatcher.read(second_frame, sequence=2)
        dispatcher.close()
        return receipt

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", fake_cloud)
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    assert cloud_once.main(_args(folder, keyfile)) == 0


def test_invalid_local_grant_or_denied_server_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    keyfile = _keyfile(tmp_path / "enrolled.pem")

    async def no_network(**kwargs: object) -> None:
        raise AssertionError("never start TLS without a selected absolute folder")

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", no_network)
    monkeypatch.setattr(cloud_once.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_once.secrets, "token_hex", lambda _: "cafebabe")
    monkeypatch.setattr("builtins.input", lambda *_: "APPROVE CAFEBABE")
    assert cloud_once.main(_args(Path("relative"), keyfile)) == 1
    assert "denied" in capsys.readouterr().err

    async def rejected(**kwargs: object) -> None:
        raise CloudHandshakeDeniedError("handshake denied")

    monkeypatch.setattr(cloud_once, "execute_single_approved_read", rejected)
    assert cloud_once.main(_args(tmp_path, keyfile)) == 1
    assert "denied" in capsys.readouterr().err

    assert cloud_once.main(_args(tmp_path, tmp_path / "missing.pem")) == 1
    assert "denied" in capsys.readouterr().err
