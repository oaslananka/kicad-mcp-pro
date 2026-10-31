"""Interactive, explicitly approved Cloud device enrollment (not access enablement).

Initiate the Cloud v1 device challenge with a fresh owner-only
Ed25519 key, wait for owner approval in a browser, and redeem once. No OAuth
session cookies, bearer tokens, private keys, or local KiCad files are sent.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import urllib3
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from kicad_mcp.cloud_pair_keys import (
    _load_owner_key,
    _open_owner_private_dir,
    _read_owner_binding,
    _save_owner_binding,
)

_PAIRING_DENIED = "pairing denied"
_JSON_MEDIA_TYPE = "application/json"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_USER_CODE = re.compile(r"[A-Z0-9]{6}-[A-Z0-9]{6}")
_BASE64URL_32 = re.compile(r"[A-Za-z0-9_-]{43}")
_FINGERPRINT = re.compile(r"[a-f0-9]{64}")


class CloudPairingError(ValueError):
    """Do not leak credentials, internal errors, or private filesystem details."""


def default_registry_root() -> Path:
    """Same owner-private key root used by the non-released read prototype."""
    return Path.home() / ".local" / "share" / "kicad-mcp-cloud"


def _origin(value: str) -> tuple[str, int, str]:
    try:
        # urlsplit() loses empty query/fragment delimiters, so reject them
        # on the original input before storing an origin for future WSS use.
        if (
            not isinstance(value, str)
            or not value.isascii()
            or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
            or "?" in value
            or "#" in value
        ):
            raise CloudPairingError(_PAIRING_DENIED)
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            # Enrollment and the subsequent WSS session must accept the
            # same origin set; a trailing DNS root dot is rejected by the
            # signed-session endpoint and must not strand an enrolled key.
            or parsed.hostname.endswith(".")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not parsed.netloc.isascii()
            or parsed.port == 0
        ):
            raise CloudPairingError(_PAIRING_DENIED)
        port = parsed.port or 443
        host = parsed.hostname
        return host, port, f"https://{parsed.netloc}"
    except ValueError as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc


def _post(
    origin: tuple[str, int, str], path: str, body: dict[str, object], status: int
) -> dict[str, object]:
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if len(data) > 1024:
        raise CloudPairingError(_PAIRING_DENIED)
    # urllib3 is a direct runtime dependency. A dedicated pool is never shared
    # with untrusted origins; TLS hostname/CA verification is mandatory.
    tls = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    tls.verify_mode = ssl.CERT_REQUIRED
    tls.check_hostname = True
    pool = urllib3.HTTPSConnectionPool(
        origin[0],
        origin[1],
        timeout=urllib3.Timeout(connect=10, read=10),
        retries=False,
        cert_reqs=ssl.CERT_REQUIRED,
        assert_hostname=origin[0],
        ssl_context=tls,
    )
    try:
        # Do not follow redirects or retry a pairing request: either could
        # move a one-use proof to a different endpoint or duplicate an attempt.
        response = pool.request(
            "POST",
            path,
            body=data,
            headers={"Content-Type": _JSON_MEDIA_TYPE, "Accept": _JSON_MEDIA_TYPE},
            retries=False,
            redirect=False,
            preload_content=False,
        )
        try:
            payload = response.read(2049)
            if (
                response.status != status
                or len(payload) > 2048
                or response.headers.get("Content-Type", "").split(";")[0] != _JSON_MEDIA_TYPE
            ):
                raise CloudPairingError(_PAIRING_DENIED)
            decoded = json.loads(payload)
            if not isinstance(decoded, dict):
                raise CloudPairingError(_PAIRING_DENIED)
            return decoded
        finally:
            response.release_conn()
    except (urllib3.exceptions.HTTPError, OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc
    finally:
        pool.close()


def _create_private_key(path: Path) -> Ed25519PrivateKey:
    """Exclusive 0600 owner key inside a pinned 0700 directory, never a symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(nofollow, int):
        raise CloudPairingError(_PAIRING_DENIED)
    try:
        directory_fd = _open_owner_private_dir(path)
    except (OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc
    try:
        key = Ed25519PrivateKey.generate()
        data = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(fd, "wb", buffering=0) as handle:
            try:
                if handle.write(data) != len(data):
                    raise OSError(_PAIRING_DENIED)
                os.fsync(handle.fileno())
            except BaseException:
                # A concurrent same-owner process may replace the filename.
                # Invalidate only our still-open inode, never unlink by path.
                os.ftruncate(handle.fileno(), 0)
                raise
        return key
    except (OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc
    finally:
        os.close(directory_fd)


def _load_or_create(path: Path) -> Ed25519PrivateKey:
    try:
        parent_fd = _open_owner_private_dir(path)
    except (OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc
    os.close(parent_fd)
    if path.is_symlink():
        raise CloudPairingError(_PAIRING_DENIED)
    if path.exists():
        try:
            return _load_owner_key(path)
        except (OSError, ValueError) as exc:
            raise CloudPairingError(_PAIRING_DENIED) from exc
    return _create_private_key(path)


def _challenge(result: dict[str, object], key: Ed25519PrivateKey) -> tuple[str, str, str, str, int]:
    required_fields = {"challengeId", "userCode", "deviceCode", "deviceFingerprint", "expiresAtMs"}
    if set(result) not in (required_fields, required_fields | {"verificationUriComplete"}):
        raise CloudPairingError(_PAIRING_DENIED)
    challenge, code, secret, fingerprint, expiry = (
        result["challengeId"],
        result["userCode"],
        result["deviceCode"],
        result["deviceFingerprint"],
        result["expiresAtMs"],
    )
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    expected = hashlib.sha256(der).hexdigest()
    if (
        not isinstance(challenge, str)
        or not _UUID.fullmatch(challenge)
        or not isinstance(code, str)
        or not _USER_CODE.fullmatch(code)
        or not isinstance(secret, str)
        or not _BASE64URL_32.fullmatch(secret)
        or not isinstance(fingerprint, str)
        or not _FINGERPRINT.fullmatch(fingerprint)
        or fingerprint != expected
        or type(expiry) is not int
        or not (time.time_ns() // 1_000_000 < expiry <= time.time_ns() // 1_000_000 + 300_000)
    ):
        raise CloudPairingError(_PAIRING_DENIED)
    return challenge, code, secret, fingerprint, expiry


def _require_unused_binding_path(keyfile: Path) -> None:
    """Fail before any Cloud request if a pairing record already occupies the path.

    Exclusive creation during redeem is still authoritative if the filesystem
    changes after this preflight check.
    """
    try:
        directory_fd = _open_owner_private_dir(keyfile)
        try:
            try:
                os.stat(
                    keyfile.name + ".cloud-binding-v1.json",
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            raise CloudPairingError(_PAIRING_DENIED)
        finally:
            os.close(directory_fd)
    except (OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc


def _wait_for_owner_approval(
    origin: tuple[str, int, str],
    challenge: str,
    device_code: str,
    signing_key: Ed25519PrivateKey,
    expiry_ms: int,
    start_owner_review: Callable[[], None] | None = None,
) -> None:
    """Require a working signed status endpoint before opening owner approval."""
    proof = (
        b"kicad-cloud-pairing-status-v1\x00"
        + challenge.encode("ascii")
        + b"\x00"
        + device_code.encode("ascii")
    )
    signature = base64.urlsafe_b64encode(signing_key.sign(proof)).decode("ascii").rstrip("=")
    body: dict[str, object] = {
        "challengeId": challenge,
        "deviceCode": device_code,
        "signature": signature,
    }
    while True:
        remaining = expiry_ms - time.time_ns() // 1_000_000
        if remaining <= 0:
            raise CloudPairingError(_PAIRING_DENIED)
        response = _post(origin, "/api/v1/pairing/device/status", body, 200)
        if set(response) != {"approved"} or type(response["approved"]) is not bool:
            raise CloudPairingError(_PAIRING_DENIED)
        if start_owner_review is not None:
            # A new challenge must be pending before inviting a human to click.
            # This also rejects older Cloud versions with no signed status API.
            if response["approved"]:
                raise CloudPairingError(_PAIRING_DENIED)
            start_owner_review()
            start_owner_review = None
        elif response["approved"]:
            return
        time.sleep(min(8.0, remaining / 1000))


def enroll(
    origin: str, alias: str, keyfile: Path, approval: Callable[[str, str, str], None]
) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", alias):
        raise CloudPairingError(_PAIRING_DENIED)
    target = _origin(origin)
    # A previously enrolled key is bound to its original Cloud; switching
    # origin requires separate owner enrollment with a new device key.
    if keyfile.is_file():
        # Reusing an already enrolled private key would create another remote
        # device record with the same signing identity. Require a fresh key
        # and a separate owner browser approval for each new enrollment.
        try:
            _read_owner_binding(keyfile)
        except (OSError, ValueError) as exc:
            raise CloudPairingError(_PAIRING_DENIED) from exc
        raise CloudPairingError(_PAIRING_DENIED)
    _require_unused_binding_path(keyfile)
    key = _load_or_create(keyfile)
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    result = _post(
        target,
        "/api/v1/pairing/device/challenge",
        {
            "alias": alias,
            "publicKeyDer": base64.b64encode(der).decode("ascii"),
        },
        201,
    )
    challenge, code, device_secret, fingerprint, expiry = _challenge(result, key)
    review_url = f"{target[2]}/devices/pairing#challenge={challenge}&code={code}"
    # Never open an untrusted Cloud-supplied link or a link carrying deviceCode.
    supplied_url = result.get("verificationUriComplete")
    if supplied_url is not None and supplied_url != review_url:
        raise CloudPairingError(_PAIRING_DENIED)
    _wait_for_owner_approval(
        target,
        challenge,
        device_secret,
        key,
        expiry,
        lambda: approval(target[2] + "/devices/pairing", challenge, code),
    )
    if time.time_ns() // 1_000_000 >= expiry:
        raise CloudPairingError(_PAIRING_DENIED)
    proof = (
        b"kicad-cloud-pairing-proof-v1\x00" + challenge.encode() + b"\x00" + device_secret.encode()
    )
    signature = base64.urlsafe_b64encode(key.sign(proof)).decode("ascii").rstrip("=")
    answer = _post(
        target,
        "/api/v1/pairing/device/redeem",
        {
            "challengeId": challenge,
            "deviceCode": device_secret,
            "signature": signature,
        },
        200,
    )
    if (
        set(answer) != {"deviceId", "deviceFingerprint", "enabled"}
        or not isinstance(answer["deviceId"], str)
        or not _UUID.fullmatch(answer["deviceId"])
        or answer["deviceFingerprint"] != fingerprint
        or answer["enabled"] is not False
    ):
        raise CloudPairingError(_PAIRING_DENIED)
    try:
        _save_owner_binding(
            keyfile, origin=target[2], device_id=answer["deviceId"], fingerprint=fingerprint
        )
    except (OSError, ValueError) as exc:
        raise CloudPairingError(_PAIRING_DENIED) from exc
    return answer["deviceId"], fingerprint


def _approval(page: str, challenge: str, code: str) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CloudPairingError(_PAIRING_DENIED)
    review_url = f"{page}#challenge={challenge}&code={code}"
    try:
        opened = webbrowser.open(review_url, new=2, autoraise=True)
    except (OSError, webbrowser.Error):
        opened = False
    if opened:
        print(f"Check that the code in the browser matches: {code}")
    else:
        # GUI-less devices retain an explicit fallback, never automatic approval.
        print(f"Open this device approval link in your signed-in browser: {review_url}")
    print("Approve in your browser. This terminal completes pairing automatically after approval.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manually enroll a KiCad Cloud device (disabled by default)"
    )
    parser.add_argument("--cloud-origin", required=True)
    parser.add_argument("--alias", required=True)
    # A fresh random local key slot replaces arbitrary CLI-selected paths.
    # The Cloud device UUID is bound to this slot's owner-only sidecar on
    # successful enrollment; a separate offline project record references it.
    parser.add_argument("--begin-pairing", action="store_true", required=True)
    options = parser.parse_args(argv)
    try:
        # Refuse unattended shell pipes before creating the signing key
        # or initiating a one-use pairing challenge on the Cloud.
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise CloudPairingError(_PAIRING_DENIED)
        from uuid import uuid4

        root = default_registry_root()
        keys = root / "keys"
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        keys.mkdir(mode=0o700, exist_ok=True)
        slot = str(uuid4())
        keyfile = keys / (slot + ".pem")
        # Before an HTTP request or key creation, prove the preselected local
        # storage is owned by this POSIX user and has private permissions.
        owned_fd = _open_owner_private_dir(keyfile)
        os.close(owned_fd)
        device_id, fingerprint = enroll(options.cloud_origin, options.alias, keyfile, _approval)
    except (CloudPairingError, KeyboardInterrupt, EOFError):
        print(
            "Cloud pairing not completed; no access enabled. An owner-only key file may exist.",
            file=sys.stderr,
        )
        return 1
    print(f"Device registered: {device_id}; fingerprint: {fingerprint}; Cloud enabled: false")
    print(f"Local key slot: {slot} (store offline in owner-private project registry)")
    print("No remote access granted. Keep the private key for a future authorized connection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
