"""Real Ed25519 signing in a manually confirmed pairing client; no remote calls."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_once, cloud_pair
from kicad_mcp.cloud_once import LocalApprovalDeniedError, _load_owner_key

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owner-key persistence needs POSIX")
CHALLENGE = "11111111-1111-4111-8111-111111111111"
DEVICE = "22222222-2222-4222-8222-222222222222"
SECRET = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


@pytest.mark.parametrize("pipe", ["stdin", "stdout"])
def test_pairing_cli_rejects_redirected_terminal_before_enrollment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipe: str
) -> None:
    keyfile = tmp_path / "new-owner.pem"
    monkeypatch.setattr(cloud_pair.sys.stdin, "isatty", lambda: pipe != "stdin")
    monkeypatch.setattr(cloud_pair.sys.stdout, "isatty", lambda: pipe != "stdout")

    def unexpected_enrollment(*_args: object) -> tuple[str, str]:
        pytest.fail("redirected terminal must fail before any enrollment operation")

    monkeypatch.setattr(cloud_pair, "enroll", unexpected_enrollment)
    outcome = cloud_pair.main(
        [
            "--cloud-origin",
            "https://localhost",
            "--alias",
            "Approved Fixture",
            "--begin-pairing",
        ]
    )
    assert outcome == 1
    assert not keyfile.exists()


@pytest.mark.parametrize("pipe", ["stdin", "stdout"])
def test_pairing_browser_confirmation_rejects_redirected_terminal(
    monkeypatch: pytest.MonkeyPatch, pipe: str
) -> None:
    monkeypatch.setattr(cloud_pair.sys.stdin, "isatty", lambda: pipe != "stdin")
    monkeypatch.setattr(cloud_pair.sys.stdout, "isatty", lambda: pipe != "stdout")
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._approval("https://localhost/devices/pairing", CHALLENGE, "ABCDEF-123456")


def test_pairing_browser_confirmation_permits_foreground_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_pair.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_pair.sys.stdout, "isatty", lambda: True)
    observed: list[str] = []

    def acknowledge(prompt: str) -> str:
        observed.append(prompt)
        return ""

    opened: list[str] = []
    monkeypatch.setattr(
        cloud_pair.webbrowser, "open", lambda url, **_options: opened.append(url) or True
    )
    monkeypatch.setattr("builtins.input", acknowledge)
    cloud_pair._approval("https://localhost/devices/pairing", CHALLENGE, "ABCDEF-123456")
    assert opened == [
        f"https://localhost/devices/pairing#challenge={CHALLENGE}&code=ABCDEF-123456"
    ]
    assert len(observed) == 1
    assert "browser" in observed[0]


def test_pairing_browser_unavailable_shows_safe_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cloud_pair.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_pair.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(cloud_pair.webbrowser, "open", lambda *_args, **_kw: False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    cloud_pair._approval("https://localhost/devices/pairing", CHALLENGE, "ABCDEF-123456")
    output = capsys.readouterr().out
    assert f"#challenge={CHALLENGE}&code=ABCDEF-123456" in output
    assert SECRET not in output


def test_pairing_refuses_untrusted_browser_link_before_owner_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "owner.pem"
    seen: list[str] = []

    def fake_post(_origin: tuple[str, int, str], path: str, data: dict, _status: int) -> dict:
        seen.append(path)
        if not path.endswith("/challenge"):
            pytest.fail("invalid pairing link must not reach redeem")
        der = base64.b64decode(data["publicKeyDer"], validate=True)
        return {
            "challengeId": CHALLENGE,
            "userCode": "ABCDEF-123456",
            "deviceCode": SECRET,
            "deviceFingerprint": hashlib.sha256(der).hexdigest(),
            "expiresAtMs": time.time_ns() // 1_000_000 + 60_000,
            "verificationUriComplete": "https://attacker.example/devices/pairing",
        }

    monkeypatch.setattr(cloud_pair, "_post", fake_post)

    def forbidden_review(*_args: object) -> None:
        pytest.fail("untrusted URL must never reach browser review")

    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Approved Fixture", keyfile, forbidden_review)
    assert seen == ["/api/v1/pairing/device/challenge"]


def test_pairing_exact_payload_and_owner_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "owner.pem"
    seen: list[str] = []

    def simulate_post(origin: tuple[str, int, str], path: str, data: dict, status: int) -> dict:
        assert origin == ("localhost", 443, "https://localhost")
        if path.endswith("/challenge"):
            assert status == 201
            assert data["alias"] == "Approved Fixture"
            der = base64.b64decode(data["publicKeyDer"], validate=True)
            public = Ed25519PublicKey.from_public_bytes(der[-32:])
            assert public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo) == der
            seen.append("challenge")
            return {
                "challengeId": CHALLENGE,
                "userCode": "ABCDEF-123456",
                "deviceCode": SECRET,
                "deviceFingerprint": hashlib.sha256(der).hexdigest(),
                "expiresAtMs": time.time_ns() // 1_000_000 + 60_000,
                "verificationUriComplete": (
                    f"https://localhost/devices/pairing#challenge={CHALLENGE}&code=ABCDEF-123456"
                ),
            }
        assert path.endswith("/redeem")
        assert status == 200

        assert seen == ["challenge", "browser_approved"]
        assert data["challengeId"] == CHALLENGE
        assert data["deviceCode"] == SECRET
        key = _load_owner_key(keyfile)
        expected = b"kicad-cloud-pairing-proof-v1\0" + CHALLENGE.encode() + b"\0" + SECRET.encode()
        key.public_key().verify(base64.urlsafe_b64decode(data["signature"] + "=="), expected)
        seen.append("redeem")
        der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        return {
            "deviceId": DEVICE,
            "deviceFingerprint": hashlib.sha256(der).hexdigest(),
            "enabled": False,
        }

    monkeypatch.setattr(cloud_pair, "_post", simulate_post)

    def approve(page: str, challenge: str, code: str) -> None:
        assert page == "https://localhost/devices/pairing"
        assert challenge == CHALLENGE
        assert code == "ABCDEF-123456"

        seen.append("browser_approved")

    device, fingerprint = cloud_pair.enroll(
        "https://localhost", "Approved Fixture", keyfile, approve
    )
    assert device == DEVICE
    assert seen == ["challenge", "browser_approved", "redeem"]
    assert len(fingerprint) == 64
    assert keyfile.stat().st_mode & 0o777 == 0o600
    # A successfully redeemed, browser-approved device must pin its origin
    # and device identity in an owner-only sidecar before any later CLI use.
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    assert binding.is_file()
    assert binding.stat().st_mode & 0o777 == 0o600
    assert '"origin":"https://localhost"' in binding.read_text()
    assert f'"deviceId":"{DEVICE}"' in binding.read_text()
    # A second enrollment with the same signing key would create another
    # remote device; reject it before sending a new Cloud challenge.
    before = keyfile.read_bytes()
    seen.clear()
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Approved Fixture", keyfile, approve)
    assert seen == []
    assert before == keyfile.read_bytes()


def test_existing_device_pin_cannot_be_overwritten_or_repaired_by_reenrollment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "owner.pem"
    cloud_pair._create_private_key(keyfile)
    der = (
        _load_owner_key(keyfile)
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    fingerprint = hashlib.sha256(der).hexdigest()
    cloud_pair._save_owner_binding(
        keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
    )
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    before = binding.read_bytes()
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://attacker.example", "Fixture", keyfile, lambda *_: None)
    assert binding.read_bytes() == before

    def impossible(*_: object, **__: object) -> dict:
        pytest.fail("existing enrollment pin must be checked before Cloud HTTP")

    monkeypatch.setattr(cloud_pair, "_post", impossible)
    binding.unlink()
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Fixture", keyfile, lambda *_: None)


def test_failed_fsync_never_leaves_a_usable_enrollment_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "fresh-owner.pem"
    cloud_pair._create_private_key(keyfile)
    fingerprint = hashlib.sha256(
        _load_owner_key(keyfile)
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()

    def fail_sync(_fd: int) -> None:
        raise OSError("synthetic disk sync failure")

    monkeypatch.setattr(cloud_once.os, "fsync", fail_sync)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_pair._save_owner_binding(
            keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
        )
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_once._read_owner_binding(keyfile)
    assert binding.stat().st_size == 0


def test_failed_binding_write_never_unlinks_a_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-user pathname swap during fsync must not delete another leaf."""
    keyfile = tmp_path / "fresh-owner.pem"
    cloud_pair._create_private_key(keyfile)
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    original = keyfile.with_name(keyfile.name + ".original-record")
    fingerprint = hashlib.sha256(
        _load_owner_key(keyfile)
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()

    def switch_leaf_then_fail(_fd: int) -> None:
        binding.rename(original)
        binding.write_text("replacement made by concurrent owner process")
        raise OSError("synthetic disk sync failure")

    monkeypatch.setattr(cloud_once.os, "fsync", switch_leaf_then_fail)
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_pair._save_owner_binding(
            keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
        )

    assert original.exists(), "first created inode kept for diagnostics"
    assert binding.read_text() == "replacement made by concurrent owner process"


def test_enrollment_binding_is_strictly_create_only_even_if_identical(tmp_path: Path) -> None:
    """Already existing metadata must never be accepted as a new enrollment."""
    keyfile = tmp_path / "fresh.pem"
    cloud_pair._create_private_key(keyfile)
    fingerprint = hashlib.sha256(
        _load_owner_key(keyfile)
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair._save_owner_binding(
        keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
    )
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    before = binding.read_bytes()
    with pytest.raises(cloud_once.LocalApprovalDeniedError):
        cloud_pair._save_owner_binding(
            keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
        )
    assert binding.read_bytes() == before


@pytest.mark.parametrize("existing_kind", ["regular", "symlink"])
def test_pending_binding_collision_denied_before_device_creation_or_key_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_kind: str
) -> None:
    """Do not provision a Cloud device when its future sidecar path is occupied."""
    keyfile = tmp_path / "new-owner.pem"
    binding = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    if existing_kind == "regular":
        binding.write_text("incomplete enrollment")
    else:
        binding.symlink_to(tmp_path / "nowhere")

    def no_remote_request(*_args: object, **_kwargs: object) -> dict:
        pytest.fail("a collision must be rejected before Cloud challenge or redeem")

    monkeypatch.setattr(cloud_pair, "_post", no_remote_request)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Approved Fixture", keyfile, lambda *_: None)
    assert not keyfile.exists()
    assert (
        binding.is_symlink()
        if existing_kind == "symlink"
        else binding.read_text() == "incomplete enrollment"
    )


def test_invalid_origin_never_creates_a_key(tmp_path: Path) -> None:
    for origin in [
        "http://localhost",
        "https://localhost/elsewhere",
        "https://admin@cloud.example",
        "https://cloud.example?token=1",
        "https://localhost:bad",
        "https://localhost#fragment",
        "https://localhost.",
        "https://localhost?",
        "https://localhost#",
        "https://localhost/?",
        "https://localhost/#",
        "https://local\thost",
        "https://localhost\n",
        "https://localhost/\r",
        "https://localhost\x00",
        " https://localhost",
        "\x1fhttps://localhost",
        "https://localhost\x7f",
        "https://caf\u00e9.example",
    ]:
        keyfile = tmp_path / "no-key"
        with pytest.raises(cloud_pair.CloudPairingError):
            cloud_pair.enroll(origin, "Fixture", keyfile, lambda *_: None)
        assert not keyfile.exists()


def test_no_unsafe_key_file_reuse_or_world_writable_parent(tmp_path: Path) -> None:
    source = tmp_path / "initial.pem"
    _ = cloud_pair._create_private_key(source)
    assert _load_owner_key(source)
    symlink = tmp_path / "alias.pem"
    symlink.symlink_to(source)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._load_or_create(symlink)
    open_dir = tmp_path / "unsafe"
    open_dir.mkdir(mode=0o777)
    open_dir.chmod(0o777)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(open_dir / "unsafe.pem")
    assert not (open_dir / "unsafe.pem").exists()
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(source)


def test_owner_key_directory_walk_denies_traversal_and_symlink_ancestors(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "protected"
    protected.mkdir(mode=0o700)
    keyfile = protected / "owner.pem"
    cloud_pair._create_private_key(keyfile)
    assert isinstance(_load_owner_key(keyfile).public_key(), Ed25519PublicKey)

    # Lexical traversal is never normalized away before the no-follow open.
    traversal = protected / ".." / "protected" / "owner.pem"
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._load_or_create(traversal)
    with pytest.raises(LocalApprovalDeniedError):
        _load_owner_key(traversal)

    # An attacker cannot substitute an ancestor with a symlink, even if its
    # target has correct ownership, permissions and the expected key file.
    linked = tmp_path / "linked"
    linked.symlink_to(protected, target_is_directory=True)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._load_or_create(linked / "new.pem")
    with pytest.raises(LocalApprovalDeniedError):
        _load_owner_key(linked / "owner.pem")

    public_parent = tmp_path / "public"
    public_parent.mkdir(mode=0o700)
    public_parent.chmod(0o755)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(public_parent / "new.pem")
    assert not (public_parent / "new.pem").exists()
    assert _load_owner_key(keyfile)


def test_hardlinked_owner_key_and_pairing_record_are_not_trusted(tmp_path: Path) -> None:
    """A 0600 regular file can still be a hard link to another owner path.

    Reject multiply-linked trust records; same-user access to the transport
    key is a *separate* and still unresolved human-authorization problem.
    """
    safe = tmp_path / "owner"
    safe.mkdir(mode=0o700)
    keyfile = safe / "device.pem"
    cloud_pair._create_private_key(keyfile)
    fingerprint = hashlib.sha256(
        _load_owner_key(keyfile)
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair._save_owner_binding(
        keyfile, origin="https://localhost", device_id=DEVICE, fingerprint=fingerprint
    )
    record = keyfile.with_name(keyfile.name + ".cloud-binding-v1.json")
    linked_key = safe / "other-device.pem"
    os.link(keyfile, linked_key)
    with pytest.raises(LocalApprovalDeniedError):
        _load_owner_key(keyfile)
    with pytest.raises(LocalApprovalDeniedError):
        _load_owner_key(linked_key)
    linked_key.unlink()
    linked_record = safe / "another-binding.json"
    os.link(record, linked_record)
    with pytest.raises(LocalApprovalDeniedError):
        cloud_once._read_owner_binding(keyfile)
    linked_record.unlink()
    assert isinstance(_load_owner_key(keyfile).public_key(), Ed25519PublicKey)
    assert cloud_once._read_owner_binding(keyfile)["deviceId"] == DEVICE


def test_owner_private_key_read_resists_directory_swap_after_fd_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o700)
    decoy = tmp_path / "decoy"
    decoy.mkdir(mode=0o700)
    approved_key = cloud_pair._create_private_key(trusted / "owner.pem")
    decoy_key = cloud_pair._create_private_key(decoy / "owner.pem")
    original_open = cloud_once._open_owner_private_dir

    def swap_after_open(path: Path) -> int:
        descriptor = original_open(path)
        trusted.rename(tmp_path / "pinned-trusted")
        trusted.symlink_to(decoy, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(cloud_once, "_open_owner_private_dir", swap_after_open)
    loaded = cloud_once._load_owner_key(trusted / "owner.pem")
    assert loaded.public_key() == approved_key.public_key()
    assert loaded.public_key() != decoy_key.public_key()
    assert (tmp_path / "pinned-trusted" / "owner.pem").is_file()


def test_owner_private_key_create_resists_directory_swap_after_fd_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o700)
    decoy = tmp_path / "decoy"
    decoy.mkdir(mode=0o700)
    original_open = cloud_pair._open_owner_private_dir

    def swap_after_open(path: Path) -> int:
        descriptor = original_open(path)
        trusted.rename(tmp_path / "pinned-trusted")
        trusted.symlink_to(decoy, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(cloud_pair, "_open_owner_private_dir", swap_after_open)
    generated = cloud_pair._create_private_key(trusted / "owner.pem")
    assert (tmp_path / "pinned-trusted" / "owner.pem").is_file()
    assert not (decoy / "owner.pem").exists()
    assert (
        generated.public_key()
        == _load_owner_key(tmp_path / "pinned-trusted" / "owner.pem").public_key()
    )


def test_owner_key_failed_creation_cleanup_stays_with_pinned_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o700)
    decoy = tmp_path / "decoy"
    decoy.mkdir(mode=0o700)
    protected_decoy = decoy / "owner.pem"
    protected_decoy.write_bytes(b"decoy must never be unlinked")
    original_sync = cloud_pair.os.fsync

    def swap_and_fail(descriptor: int) -> None:
        # This injected fault occurs after the key leaf is created and while
        # cleanup still holds the original parent directory descriptor.
        assert descriptor >= 0
        trusted.rename(tmp_path / "pinned-trusted")
        trusted.symlink_to(decoy, target_is_directory=True)
        raise OSError("simulated disk sync failure")

    monkeypatch.setattr(cloud_pair.os, "fsync", swap_and_fail)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(trusted / "owner.pem")
    monkeypatch.setattr(cloud_pair.os, "fsync", original_sync)
    assert protected_decoy.read_bytes() == b"decoy must never be unlinked"
    assert (tmp_path / "pinned-trusted" / "owner.pem").stat().st_size == 0


def test_failed_private_key_write_does_not_delete_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after another process swaps the key basename must not unlink it."""
    keyfile = tmp_path / "owner.pem"
    moved = tmp_path / "old-key-inode.pem"

    def replace_leaf_and_fail(_fd: int) -> None:
        keyfile.rename(moved)
        keyfile.write_bytes(b"unrelated same-owner file")
        raise OSError("simulated key sync failure")

    monkeypatch.setattr(cloud_pair.os, "fsync", replace_leaf_and_fail)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(keyfile)
    assert keyfile.read_bytes() == b"unrelated same-owner file"
    assert moved.stat().st_size == 0


def test_failed_key_sync_does_not_leave_usable_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "new-owner.pem"

    def fail_sync(_fd: int) -> None:
        raise OSError("simulated key sync failure")

    monkeypatch.setattr(cloud_pair.os, "fsync", fail_sync)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._create_private_key(keyfile)
    with pytest.raises(LocalApprovalDeniedError):
        _load_owner_key(keyfile)
    assert keyfile.stat().st_size == 0


def test_declined_or_tampered_challenge_never_redeems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "unused.pem"
    visited: list[str] = []

    def fake_post(origin: tuple[str, int, str], path: str, data: dict, status: int) -> dict:
        visited.append(path)
        if path.endswith("/challenge"):
            return {
                "challengeId": CHALLENGE,
                "userCode": "ABCDEF-123456",
                "deviceCode": SECRET,
                "deviceFingerprint": "0" * 64,
                "expiresAtMs": time.time_ns() // 1_000_000 + 30_000,
            }
        raise AssertionError("Never redeem an unverified server challenge")

    monkeypatch.setattr(cloud_pair, "_post", fake_post)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Fixture", keyfile, lambda *_: None)
    assert visited == ["/api/v1/pairing/device/challenge"]
    assert keyfile.exists()  # Key persisted before enrollment, can be reused safely.


def test_redirect_does_not_approve_or_follow(monkeypatch: pytest.MonkeyPatch) -> None:
    visited: list[str] = []

    class Response:
        status = 302
        headers = {"Content-Type": "text/html"}

        def read(self, _: int) -> bytes:
            return b"redirect"

        def release_conn(self) -> None:
            visited.append("released")

    class Pool:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def request(self, *_: object, **kwargs: object) -> Response:
            assert kwargs["redirect"] is False
            assert kwargs["retries"] is False
            assert kwargs["preload_content"] is False
            return Response()

        def close(self) -> None:
            visited.append("closed")

    monkeypatch.setattr(cloud_pair.urllib3, "HTTPSConnectionPool", Pool)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._post(
            ("localhost", 443, "https://localhost"),
            "/api/v1/pairing/device/challenge",
            {"alias": "Fixture"},
            201,
        )
    assert visited == ["released", "closed"]


def test_https_pairing_post_sends_only_expected_json_and_refuses_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: list[tuple[str, str]] = []

    class Response:
        status = 201
        headers = {"Content-Type": "application/json; charset=utf-8"}

        def read(self, maximum: int) -> bytes:
            assert maximum == 2049
            return b'{"challengeId":"test"}'

        def release_conn(self) -> None:
            responses.append(("released", ""))

    class Pool:
        def __init__(self, host: str, port: int, **options: object) -> None:
            assert (host, port) == ("localhost", 443)
            assert isinstance(options["timeout"], cloud_pair.urllib3.Timeout)
            assert options["retries"] is False
            assert options["cert_reqs"] == cloud_pair.ssl.CERT_REQUIRED
            assert options["assert_hostname"] == "localhost"
            assert options["ssl_context"].verify_mode == cloud_pair.ssl.CERT_REQUIRED
            assert options["ssl_context"].check_hostname is True

        def request(self, method: str, path: str, **options: object) -> Response:
            assert method == "POST"
            assert path == "/api/v1/pairing/device/challenge"

            body = options["body"]
            assert isinstance(body, bytes)
            assert b"secret" not in body
            assert options["headers"] == {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            assert options["redirect"] is False
            assert options["preload_content"] is False
            assert options["retries"] is False
            responses.append((method, path))
            return Response()

        def close(self) -> None:
            responses.append(("closed", ""))

    monkeypatch.setattr(cloud_pair.urllib3, "HTTPSConnectionPool", Pool)
    assert cloud_pair._post(
        ("localhost", 443, "https://localhost"),
        "/api/v1/pairing/device/challenge",
        {"alias": "Demo"},
        201,
    ) == {"challengeId": "test"}
    assert responses == [
        ("POST", "/api/v1/pairing/device/challenge"),
        ("released", ""),
        ("closed", ""),
    ]
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair._post(
            ("localhost", 443, "https://localhost"),
            "/api/v1/pairing/device/challenge",
            {"alias": "A" * 1100},
            201,
        )


def test_cli_requires_explicit_consent_and_reports_disabled_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    options = [
        "--cloud-origin",
        "https://localhost",
        "--alias",
        "Fixture",
    ]
    with pytest.raises(SystemExit) as missing_consent:
        cloud_pair.main(options)
    assert missing_consent.value.code == 2

    received: list[object] = []

    def authorized(origin: str, alias: str, keyfile: Path, approve: object) -> tuple[str, str]:
        received.extend([origin, alias, keyfile])
        return DEVICE, "e" * 64

    from kicad_mcp import cloud_local_registry

    monkeypatch.setattr(cloud_local_registry, "default_registry_root", lambda: tmp_path / "profile")
    monkeypatch.setattr(cloud_pair, "enroll", authorized)
    monkeypatch.setattr(cloud_pair.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cloud_pair.sys.stdout, "isatty", lambda: True)
    assert cloud_pair.main([*options, "--begin-pairing"]) == 0
    output = capsys.readouterr().out
    assert DEVICE in output
    assert "enabled: false" in output

    assert received[:2] == ["https://localhost", "Fixture"]
    assert len(received) == 3
    assert isinstance(received[2], Path)
    assert received[2].parent == tmp_path / "profile" / "keys"
    assert received[2].suffix == ".pem"
    assert "Local key slot:" in output

    def rejected(*_: object) -> tuple[str, str]:
        raise cloud_pair.CloudPairingError("pairing denied")

    monkeypatch.setattr(cloud_pair, "enroll", rejected)
    assert cloud_pair.main([*options, "--begin-pairing"]) == 1
    assert "not completed" in capsys.readouterr().err


def test_successful_challenge_but_missing_browser_approval_never_redeems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyfile = tmp_path / "owner.pem"
    visits: list[str] = []

    def fake_post(origin: tuple[str, int, str], path: str, data: dict, status: int) -> dict:
        visits.append(path)
        if path.endswith("challenge"):
            # Fetch the existing key that the client created before issuing the challenge.
            key = _load_owner_key(keyfile)
            der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
            return {
                "challengeId": CHALLENGE,
                "userCode": "ABCDEF-123456",
                "deviceCode": SECRET,
                "deviceFingerprint": hashlib.sha256(der).hexdigest(),
                "expiresAtMs": time.time_ns() // 1_000_000 + 50_000,
            }
        raise AssertionError("Redeemed without approval")

    def cancel(*_: object) -> None:
        raise cloud_pair.CloudPairingError("user declined")

    monkeypatch.setattr(cloud_pair, "_post", fake_post)
    with pytest.raises(cloud_pair.CloudPairingError):
        cloud_pair.enroll("https://localhost", "Fixture", keyfile, cancel)
    assert visits == ["/api/v1/pairing/device/challenge"]
