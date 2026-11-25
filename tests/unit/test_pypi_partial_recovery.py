"""Recover interrupted Python publication without replacing existing packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from scripts import generate_release_evidence as evidence

WHEEL = "kicad_mcp_pro-4.23.0-py3-none-any.whl"
SDIST = "kicad_mcp_pro-4.23.0.tar.gz"


@pytest.fixture
def release(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    dist = tmp_path / "dist"
    dist.mkdir()
    checksums = tmp_path / "SHA256SUMS.txt"
    expected = {}
    for name in (WHEEL, SDIST):
        content = name.encode()
        (dist / name).write_bytes(content)
        expected[name] = hashlib.sha256(content).hexdigest()
    checksums.write_text("".join(f"{h}  {n}\n" for n, h in expected.items()))
    return dist, checksums, tmp_path / "pending-dist", expected


def stage(release, repository="pypi") -> int:
    dist, checksums, output, _ = release
    return evidence.stage_pypi_upload(repository, "4.23.0", checksums, dist, output)


@pytest.mark.parametrize("repository", ["pypi", "testpypi"])
@pytest.mark.parametrize("present", [(), (WHEEL,), (SDIST,), (WHEEL, SDIST)])
def test_stage_only_missing(release, monkeypatch, repository, present) -> None:
    dist, _, output, expected = release
    remote = {n: expected[n] for n in present}
    get = Mock(return_value=remote)
    if not present:
        get.side_effect = HTTPError("https://example.invalid", 404, "not found", {}, None)
    monkeypatch.setattr(evidence, "_published_pypi_digests", get)
    provenance = Mock(return_value=[])
    monkeypatch.setattr(evidence, "_pypi_provenance_attempt_errors", provenance)
    assert stage(release, repository) == 2 - len(present)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        n: (dist / n).read_bytes() for n in expected.keys() - remote.keys()
    }
    assert set(p.name for p in dist.iterdir()) == set(expected)
    get.assert_called_once_with(repository, "kicad-mcp-pro", "4.23.0")
    if present:
        provenance.assert_called_once()
        assert provenance.call_args.args == (remote,)
        assert provenance.call_args.kwargs["publisher_environment"] == repository
        assert provenance.call_args.kwargs["artifact_dir"] == dist
    else:
        provenance.assert_not_called()


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_http_error_never_means_missing(release, monkeypatch, code) -> None:
    monkeypatch.setattr(
        evidence,
        "_published_pypi_digests",
        Mock(side_effect=HTTPError("https://example.invalid", code, "failure", {}, None)),
    )
    with pytest.raises(HTTPError):
        stage(release)
    assert not release[2].exists()


@pytest.mark.parametrize("remote", [{WHEEL: "0" * 64}, {"extra.whl": "a" * 64}, {}])
def test_bad_remote_inventory_blocks_upload(release, monkeypatch, remote) -> None:
    monkeypatch.setattr(evidence, "_published_pypi_digests", Mock(return_value=remote))
    with pytest.raises(ValueError):
        stage(release)
    assert not release[2].exists()


def test_existing_bad_provenance_blocks_upload(release, monkeypatch) -> None:
    monkeypatch.setattr(
        evidence, "_published_pypi_digests", Mock(return_value={WHEEL: release[3][WHEEL]})
    )
    monkeypatch.setattr(
        evidence, "_pypi_provenance_attempt_errors", Mock(return_value=["wrong signer"])
    )
    with pytest.raises(ValueError, match="wrong signer"):
        stage(release)
    assert not release[2].exists()


@pytest.mark.parametrize(
    "change", ["tamper", "extra", "duplicate", "missing", "symlink", "existing-output"]
)
def test_invalid_local_inputs_block_before_registry_read(release, monkeypatch, change) -> None:
    dist, checksums, output, expected = release
    if change == "tamper":
        (dist / WHEEL).write_bytes(b"tampered")
    elif change == "extra":
        (dist / "unexpected.whl").write_bytes(b"extra")
    elif change == "duplicate":
        checksums.write_text(checksums.read_text() + f"{expected[WHEEL]}  {WHEEL}\n")
    elif change == "missing":
        (dist / SDIST).unlink()
    elif change == "symlink":
        (dist / SDIST).unlink()
        target = dist.parent / SDIST
        target.write_bytes(SDIST.encode())
        try:
            (dist / SDIST).symlink_to(target)
        except OSError:
            pytest.skip("symlink creation unavailable")
    else:
        output.mkdir()
    read = Mock()
    monkeypatch.setattr(evidence, "_published_pypi_digests", read)
    with pytest.raises((ValueError, SystemExit)):
        stage(release)
    read.assert_not_called()
    if change != "existing-output":
        assert not output.exists()


@pytest.mark.parametrize(
    "urls",
    [
        None,
        [{}],
        [{"filename": WHEEL, "digests": {}}],
        [
            {"filename": WHEEL, "digests": {"sha256": "a" * 64}},
            {"filename": WHEEL, "digests": {"sha256": "a" * 64}},
        ],
    ],
)
def test_invalid_registry_json_is_not_absent(monkeypatch, urls) -> None:
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({"urls": urls}).encode()
    monkeypatch.setattr(evidence.urllib.request, "urlopen", Mock(return_value=response))
    with pytest.raises(ValueError):
        evidence._published_pypi_digests("pypi", "kicad-mcp-pro", "4.23.0")
