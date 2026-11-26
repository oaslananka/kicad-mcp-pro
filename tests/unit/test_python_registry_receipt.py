"""Read-only PyPI receipt adapter and required cryptographic checks."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from scripts import check_python_registry_receipt as receipt


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int) -> None:
        super().__init__(data)
        self.status = status


@pytest.mark.parametrize(
    "payload,status",
    [(b'{"x":1,"x":2}', 200), (b"[]", 200), (b"x" * 1025, 200), (b"{}", 302)],
)
def test_registry_json_rejects_invalid_response(monkeypatch, payload, status) -> None:
    monkeypatch.setattr(receipt, "_MAX_JSON", 1024)
    closed = []

    class Pool:
        def __init__(self, *, cert_reqs, timeout) -> None:
            assert cert_reqs == "CERT_REQUIRED"
            assert timeout == 30.0

        def request(
            self, method, url, *, headers, preload_content, redirect, retries, decode_content
        ):
            assert method == "GET"
            assert url == "https://pypi.org/pypi/kicad-mcp-pro/1.2.3/json"
            assert headers == {"Accept": "application/json", "Accept-Encoding": "identity"}
            assert preload_content is False
            assert redirect is False
            assert retries is False
            assert decode_content is False
            return Response(payload, status)

        def clear(self):
            closed.append(True)

    monkeypatch.setattr(receipt.urllib3, "PoolManager", Pool)
    with pytest.raises(ValueError):
        receipt.PyPIReadClient().inventory("1.2.3")
    assert closed == [True]


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/a",
        "https://pypi.org.evil.example/a",
        "https://pypi.org/a?b",
        "https://pypi.org/a#b",
    ],
)
def test_registry_rejects_unapproved_url(url) -> None:
    with pytest.raises(ValueError):
        receipt._read_registry_json(url, "application/json")


def test_registry_client_fixed_endpoints(monkeypatch) -> None:
    calls = []

    def read(url, accept):
        calls.append((url, accept))
        return {}

    monkeypatch.setattr(receipt, "_read_registry_json", read)
    client = receipt.PyPIReadClient()
    client.inventory("1.2.3")
    client.provenance("1.2.3", "name.whl")
    assert calls == [
        ("https://pypi.org/pypi/kicad-mcp-pro/1.2.3/json", "application/json"),
        (
            "https://pypi.org/integrity/kicad-mcp-pro/1.2.3/name.whl/provenance",
            "application/vnd.pypi.integrity.v1+json",
        ),
    ]


@pytest.mark.parametrize(
    "metadata,crypto", [(None, None), ("bad publisher", None), (None, "bad signature")]
)
def test_provenance_requires_cryptographic_gate(tmp_path, monkeypatch, metadata, crypto) -> None:
    path = tmp_path / "name.whl"
    path.write_bytes(b"package")
    calls = []

    def metadata_check(
        payload,
        *,
        filename,
        digest,
        publisher_repository,
        publisher_workflow,
        publisher_environment,
    ):
        assert filename == path.name
        assert len(digest) == 64
        assert publisher_repository == "oaslananka/kicad-mcp-pro"
        assert publisher_workflow == "publish-python.yml"
        assert publisher_environment == "pypi"
        calls.append("metadata")
        return metadata

    def crypto_check(
        payload,
        *,
        artifact_path: Path,
        publisher_repository,
        publisher_workflow,
        publisher_environment,
    ):
        assert artifact_path == path
        assert publisher_repository == "oaslananka/kicad-mcp-pro"
        assert publisher_workflow == "publish-python.yml"
        assert publisher_environment == "pypi"
        calls.append("crypto")
        return crypto

    monkeypatch.setattr(receipt, "_provenance_failure", metadata_check)
    monkeypatch.setattr(receipt, "_cryptographic_provenance_failure", crypto_check)
    assert receipt.verify_registry_provenance({}, path) == (metadata or crypto)
    assert calls == (["metadata"] if metadata else ["metadata", "crypto"])
