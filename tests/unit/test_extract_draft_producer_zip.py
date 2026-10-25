"""Archive ZIP content is constrained after exact Actions SHA verification."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

from scripts.assemble_mcp_server_draft_assets import _expected
from scripts.check_draft_producer_archive import REPOSITORY
from scripts.extract_draft_producer_zip import verify_and_extract

RUN_ID = 991122
ATTEMPT = 1
ARTIFACT_ID = 778899
REPO_ID = 12345
SHA = "a" * 40
TAG = "mcp-server-v4.5.0"

EXPECTED = {
    "python-dist": "python_dist",
    "python-release-evidence": "python_evidence",
    "mcpb-release-evidence": "mcpb",
    "kicad-pcm-release-evidence": "pcm",
}


class FixtureClient:
    def __init__(self, role: str, zip_bytes: bytes) -> None:
        paths = {
            "python-dist": "publish-python.yml",
            "python-release-evidence": "publish-python.yml",
            "mcpb-release-evidence": "publish-mcpb.yml",
            "kicad-pcm-release-evidence": "publish-kicad-pcm.yml",
        }
        self.run: dict[str, Any] = {
            "id": RUN_ID,
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
            "repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "head_repository": {"id": REPO_ID, "full_name": REPOSITORY},
            "path": f".github/workflows/{paths[role]}",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": SHA,
            "run_attempt": ATTEMPT,
            "status": "completed",
            "conclusion": "success",
        }
        self.art: dict[str, Any] = {
            "id": ARTIFACT_ID,
            "name": role,
            "expired": False,
            "size_in_bytes": len(zip_bytes),
            "digest": "sha256:" + hashlib.sha256(zip_bytes).hexdigest(),
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}",
            "archive_download_url": (
                f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip"
            ),
            "workflow_run": {
                "id": RUN_ID,
                "repository_id": REPO_ID,
                "head_repository_id": REPO_ID,
                "head_branch": "main",
                "head_sha": SHA,
            },
        }

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any]:
        assert repo == REPOSITORY and run_id == RUN_ID
        return self.run

    def artifact(self, repo: str, artifact_id: int) -> dict[str, Any]:
        assert repo == REPOSITORY and artifact_id == ARTIFACT_ID
        return self.art


def _zip(files: list[tuple[str, bytes]], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as f:
        for name, data in files:
            if symlink == name:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                f.writestr(info, data)
            else:
                f.writestr(name, data)
    return buffer.getvalue()


def _test_case(tmp_path: Path, role: str, zip_bytes: bytes) -> tuple[FixtureClient, dict[str, Any]]:
    downloaded = tmp_path / "downloaded.zip"
    downloaded.write_bytes(zip_bytes)
    return FixtureClient(role, zip_bytes), {
        "repo": REPOSITORY,
        "role": role,
        "tag": TAG,
        "run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "artifact_id": ARTIFACT_ID,
        "head_sha": SHA,
        "downloaded_zip": downloaded,
        "output": tmp_path / "extracted",
    }


def _files(role: str) -> list[tuple[str, bytes]]:
    return [
        (name, f"contents-{name}".encode()) for name in sorted(_expected("4.5.0")[EXPECTED[role]])
    ]


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_valid_exact_role_extracts_into_isolated_directory(tmp_path: Path, role: str) -> None:
    files = _files(role)
    client, kwargs = _test_case(tmp_path, role, _zip(files))
    result = verify_and_extract(client, **kwargs)
    assert result["zipMemberSafetyVerified"] is True
    assert result["extractedCount"] == len(files)
    assert result["signedAttestationVerified"] is False
    assert result["publicationAuthorized"] is False
    assert sorted(p.name for p in kwargs["output"].iterdir()) == sorted(name for name, _ in files)
    assert all((kwargs["output"] / name).read_bytes() == data for name, data in files)


@pytest.mark.parametrize(
    "change",
    ["extra", "missing", "duplicate", "nested", "traversal", "symlink"],
)
def test_dangerous_or_unapproved_zip_members_rejected_before_output(
    tmp_path: Path, change: str
) -> None:
    role = "mcpb-release-evidence"
    files = _files(role)
    bad_link = None
    if change == "extra":
        files.append(("unapproved.exe", b"1"))
    elif change == "missing":
        files.pop()
    elif change == "duplicate":
        files.append(files[0])
    elif change == "nested":
        files[0] = ("subdir/" + files[0][0], files[0][1])
    elif change == "traversal":
        files[0] = ("../" + files[0][0], files[0][1])
    elif change == "symlink":
        bad_link = files[0][0]
    client, kwargs = _test_case(tmp_path, role, _zip(files, symlink=bad_link))
    with pytest.raises(ValueError, match="unexpected|unsafe"):
        verify_and_extract(client, **kwargs)
    assert not kwargs["output"].exists()


def test_untrusted_zip_digest_cannot_be_extracted(tmp_path: Path) -> None:
    client, kwargs = _test_case(tmp_path, "python-dist", _zip(_files("python-dist")))
    client.art["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="ZIP differs"):
        verify_and_extract(client, **kwargs)
    assert not kwargs["output"].exists()


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    client, kwargs = _test_case(
        tmp_path, "kicad-pcm-release-evidence", _zip(_files("kicad-pcm-release-evidence"))
    )
    kwargs["output"].mkdir()
    with pytest.raises(ValueError, match="already exist"):
        verify_and_extract(client, **kwargs)
    assert not list(kwargs["output"].iterdir())


def test_invalid_version_tag_is_rejected_without_github(tmp_path: Path) -> None:
    client, kwargs = _test_case(
        tmp_path, "mcpb-release-evidence", _zip(_files("mcpb-release-evidence"))
    )
    kwargs["tag"] = "mcp-server-v5.0.0-rc1"
    with pytest.raises(ValueError, match="unapproved"):
        verify_and_extract(client, **kwargs)
