"""Provider v0 dummy conformance: capability, offline, permission, timeout, corruption."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest

from kicad_mcp.providers import (
    ProviderErrorCode,
    ProviderFamily,
    ProviderManifest,
    ProviderOperation,
    ProviderPermission,
    ProviderProvenance,
    ProviderRegistry,
    ProviderRequest,
    ProviderResult,
    execute_provider,
)
from kicad_mcp.providers.contracts import Provider


@dataclass
class Dummy:
    family: ProviderFamily = ProviderFamily.PART
    mode: str = "ok"

    async def ready(self) -> bool:
        return self.mode != "unavailable"

    async def invoke(self, request: ProviderRequest) -> object:
        if self.mode == "timeout":
            await asyncio.sleep(1)
        if self.mode == "exception":
            raise RuntimeError("secret error")
        if self.mode == "malformed":
            return {"ok": True, "request_id": request.request_id}
        return ProviderResult(
            request_id="req-wrong" if self.mode == "wrong_request" else request.request_id,
            ok=True,
            payload={"part": "R0603"},
            provenance=ProviderProvenance(
                provider_id="other-part" if self.mode == "wrong_provider" else "fixture-part",
                provider_version="0.2" if self.mode == "wrong_version" else "0.1",
                source="unexpected:source" if self.mode == "wrong_source" else "fixture:unit",
                execution_id="exec-001",
                deterministic=self.mode != "wrong_determinism",
                input_sha256="a" * 64,
                output_sha256="b" * 64,
            ),
        )


def fixture_manifest(*, network: bool = False, mutation: bool = False) -> ProviderManifest:
    perm = (ProviderPermission.PROJECT_WRITE,) if mutation else ()
    if network:
        perm += (ProviderPermission.NETWORK,)
    return ProviderManifest(
        sdk_version="0-experimental",
        provider_id="fixture-part",
        provider_version="0.1",
        family=ProviderFamily.PART,
        capabilities=("parts.lookup",),
        operations=(
            ProviderOperation(
                name="lookup",
                capability="parts.lookup",
                permissions=perm[:1] if mutation else (),
                idempotent=not mutation,
            ),
        ),
        permissions=perm,
        network_access=network,
        network_hosts=("api.example.org",) if network else (),
        deterministic=True,
        provenance_source="fixture:unit",
        healthcheck="ready",
        license_id="MIT",
        distribution_notes="Dummy only",
    )


def request(**kwargs: object) -> ProviderRequest:
    fields: dict[str, object] = {
        "request_id": "req-001",
        "capability": "parts.lookup",
        "operation": "lookup",
    }
    fields.update(kwargs)
    return ProviderRequest.model_validate(fields)


@pytest.mark.anyio
@pytest.mark.parametrize("family", tuple(ProviderFamily))
async def test_all_four_provider_families_share_the_typed_capability_contract(
    family: ProviderFamily,
) -> None:
    """The experimental SDK must not special-case real vendor adapters."""

    class FamilyDummy:
        def __init__(self, requested: ProviderFamily) -> None:
            self.family = requested

        async def ready(self) -> bool:
            return True

        async def invoke(self, provider_request: ProviderRequest) -> object:
            return ProviderResult(
                request_id=provider_request.request_id,
                ok=True,
                payload={"family": self.family.value},
                provenance=ProviderProvenance(
                    provider_id=f"fixture-{self.family.value}",
                    provider_version="0.1",
                    source="fixture:family",
                    execution_id="exec-001",
                    deterministic=True,
                    input_sha256="a" * 64,
                    output_sha256="b" * 64,
                ),
            )

    capability = f"{family.value}.probe"
    registration = ProviderManifest(
        sdk_version="0-experimental",
        provider_id=f"fixture-{family.value}",
        provider_version="0.1",
        family=family,
        capabilities=(capability,),
        operations=(ProviderOperation(name="probe", capability=capability),),
        deterministic=True,
        provenance_source="fixture:family",
        healthcheck="ready",
        license_id="MIT",
        distribution_notes="Dummy conformance only",
    )
    registry = ProviderRegistry()
    registry.register(registration, FamilyDummy(family))
    outcome = await execute_provider(
        registry,
        ProviderRequest(request_id="req-probe", operation="probe", capability=capability),
    )
    assert outcome.ok
    assert outcome.payload == {"family": family.value}
    assert registry.advertised_families() == {family}
    missing = await execute_provider(registry, request(capability="missing.capability"))
    assert missing.error is not None
    assert missing.error.code is ProviderErrorCode.NO_CAPABILITY


@pytest.mark.anyio
async def test_success_and_capability_selection_without_provider_name() -> None:
    registry = ProviderRegistry()
    registry.register(fixture_manifest(), Dummy())
    reply = await execute_provider(registry, request())
    assert reply.ok
    assert reply.payload["part"] == "R0603"
    assert registry.advertised_families() == {ProviderFamily.PART}
    unknown = await execute_provider(registry, request(capability="route.fast"))
    assert unknown.error is not None
    assert unknown.error.code is ProviderErrorCode.NO_CAPABILITY


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("unavailable", ProviderErrorCode.NOT_READY),
        ("timeout", ProviderErrorCode.TIMEOUT),
        ("malformed", ProviderErrorCode.MALFORMED_RESULT),
        ("wrong_request", ProviderErrorCode.MALFORMED_RESULT),
        ("wrong_provider", ProviderErrorCode.MALFORMED_RESULT),
        ("wrong_version", ProviderErrorCode.MALFORMED_RESULT),
        ("wrong_source", ProviderErrorCode.MALFORMED_RESULT),
        ("wrong_determinism", ProviderErrorCode.MALFORMED_RESULT),
        ("exception", ProviderErrorCode.PROVIDER_FAILURE),
    ],
)
async def test_fail_closed(mode: str, code: ProviderErrorCode) -> None:
    registry = ProviderRegistry()
    registry.register(fixture_manifest(), Dummy(mode=mode))
    reply = await execute_provider(registry, request(timeout_seconds=0.005))
    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code is code
    assert reply.provenance is None


@pytest.mark.anyio
async def test_offline_network_permission_and_mutation_guards() -> None:
    registry = ProviderRegistry()
    registry.register(fixture_manifest(network=True), Dummy())
    offline = await execute_provider(registry, request())
    assert offline.error is not None
    assert offline.error.code is ProviderErrorCode.NETWORK_DISABLED
    permitted = await execute_provider(
        registry, request(), offline=False, granted_permissions=(ProviderPermission.NETWORK,)
    )
    assert permitted.ok is True

    mutations = ProviderRegistry()
    mutations.register(fixture_manifest(mutation=True), Dummy())
    denied = await execute_provider(mutations, request())
    assert denied.error is not None
    assert denied.error.code is ProviderErrorCode.PERMISSION_DENIED
    missing_key = await execute_provider(
        mutations,
        request(),
        granted_permissions=(ProviderPermission.PROJECT_WRITE,),
    )
    assert missing_key.error is not None
    assert missing_key.error.code is ProviderErrorCode.PERMISSION_DENIED
    accepted = await execute_provider(
        mutations,
        request(idempotency_key="edit-001"),
        granted_permissions=(ProviderPermission.PROJECT_WRITE,),
    )
    assert accepted.ok is True


def test_family_mismatch_and_duplicate_registration() -> None:
    registry = ProviderRegistry()
    expected = fixture_manifest()
    wrong_family = Dummy(family=ProviderFamily.SOLVER)
    with pytest.raises(ValueError, match="family mismatch"):
        registry.register(expected, wrong_family)
    registry.register(fixture_manifest(), Dummy())
    duplicate = fixture_manifest()
    new_adapter = Dummy()
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(duplicate, new_adapter)


@pytest.mark.anyio
async def test_cancellation_is_propagated() -> None:
    registry = ProviderRegistry()
    registry.register(fixture_manifest(), Dummy(mode="timeout"))
    task = asyncio.create_task(execute_provider(registry, request()))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    ("ready_mode", "invoke_mode"),
    [
        ("missing", "valid"),
        ("sync", "valid"),
        ("value", "valid"),
        ("valid", "missing"),
        ("valid", "sync"),
        ("valid", "value"),
    ],
)
def test_register_rejects_invalid_async_provider_before_advertising(
    ready_mode: str, invoke_mode: str
) -> None:
    async def async_ready() -> bool:
        return True

    async def async_invoke(_request: ProviderRequest) -> object:
        return None

    def sync_ready() -> bool:
        return True

    def sync_invoke(_request: ProviderRequest) -> object:
        return None

    ready_values = {"valid": async_ready, "sync": sync_ready, "value": True}
    invoke_values = {"valid": async_invoke, "sync": sync_invoke, "value": True}
    methods: dict[str, object] = {"family": ProviderFamily.PART}
    if ready_mode != "missing":
        methods["ready"] = ready_values[ready_mode]
    if invoke_mode != "missing":
        methods["invoke"] = invoke_values[invoke_mode]
    adapter = cast(Provider, SimpleNamespace(**methods))
    registry = ProviderRegistry()

    with pytest.raises(ValueError, match="asynchronous"):
        registry.register(fixture_manifest(), adapter)

    assert registry.candidates(request()) == ()
    assert registry.advertised_families() == frozenset()
