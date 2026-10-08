"""Contract and security declaration tests for experimental Provider SDK v0."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_mcp.providers import (
    ProviderFamily,
    ProviderManifest,
    ProviderOperation,
    ProviderPermission,
    ProviderRequest,
    SDK_VERSION,
)


def manifest(**overrides: object) -> ProviderManifest:
    fields: dict[str, object] = {
        "sdk_version": SDK_VERSION,
        "provider_id": "dummy-part",
        "provider_version": "0.1.0",
        "family": ProviderFamily.PART,
        "capabilities": ("parts.lookup",),
        "operations": (ProviderOperation(name="lookup", capability="parts.lookup"),),
        "permissions": (),
        "deterministic": True,
        "provenance_source": "dummy:contract-test",
        "healthcheck": "ready",
        "license_id": "MIT",
        "distribution_notes": "Internal test provider only",
    }
    fields.update(overrides)
    return ProviderManifest.model_validate(fields)


def test_manifest_is_versioned_and_declares_capabilities() -> None:
    obj = manifest()
    assert obj.sdk_version == "0-experimental"
    assert obj.find_operation("lookup", "parts.lookup") is not None
    assert obj.find_operation("route", "parts.lookup") is None
    assert obj.model_dump(mode="json")["network_access"] is False
    with pytest.raises(ValidationError):
        manifest(sdk_version="1")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"capabilities": ("parts.lookup", "parts.lookup")}, "duplicate capabilities"),
        ({"capabilities": ("invalid capability",)}, "invalid capability"),
        ({"operations": (ProviderOperation(name="lookup", capability="other"),)},
         "undeclared capability"),
        ({"permissions": (ProviderPermission.NETWORK,)}, "network declaration"),
        ({"network_access": True}, "network declaration"),
        ({"network_hosts": ("api.example.org",)}, "explicit host"),
        ({"network_access": True, "permissions": (ProviderPermission.NETWORK,)},
         "explicit host"),
        ({"network_access": True, "permissions": (ProviderPermission.NETWORK,),
          "network_hosts": ("*.example.org",)}, "exact names"),
        ({"data_egress": True}, "egress declaration"),
        ({"data_egress": True, "permissions": (ProviderPermission.DATA_EGRESS,)},
         "egress requires"),
        ({"operations": (ProviderOperation(
            name="lookup", capability="parts.lookup",
            permissions=(ProviderPermission.PROJECT_WRITE,),
        ),)}, "undeclared permission"),
    ],
)
def test_manifest_rejects_unsafe_declarations(
    change: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        manifest(**change)


def test_mutations_require_explicit_permission_and_idempotency() -> None:
    with pytest.raises(ValidationError, match="mutation permission"):
        ProviderOperation(name="write", capability="parts.lookup", idempotent=False)
    op = ProviderOperation(
        name="write", capability="parts.lookup", idempotent=False,
        permissions=(ProviderPermission.PROJECT_WRITE,),
    )
    assert op.idempotent is False
    with pytest.raises(ValidationError):
        ProviderRequest(
            request_id="req-001", capability="parts.lookup",
            operation="lookup", timeout_seconds=0,
        )


def test_provider_request_strict_unknown_fields_and_json_payload() -> None:
    request = ProviderRequest(
        request_id="req-001", capability="parts.lookup",
        operation="lookup", payload={"part": "C0603", "count": 3},
    )
    assert request.payload["count"] == 3
    with pytest.raises(ValidationError):
        ProviderRequest.model_validate({**request.model_dump(), "unsafe_path": "/tmp/x"})
