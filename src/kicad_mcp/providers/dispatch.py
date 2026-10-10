"""Fail-closed Provider SDK v0 dispatcher; no implicit retries or external loading."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from pydantic import ValidationError

from .contracts import ProviderErrorCode, ProviderPermission, ProviderRequest
from .registry import ProviderRegistry, ProviderSelection
from .results import ProviderError, ProviderResult


def _failure(request: ProviderRequest, code: ProviderErrorCode, message: str) -> ProviderResult:
    return ProviderResult(
        request_id=request.request_id,
        ok=False,
        error=ProviderError(code=code, message=message),
    )


def _select(
    registry: ProviderRegistry,
    request: ProviderRequest,
    *,
    permissions: frozenset[ProviderPermission],
    offline: bool,
) -> ProviderSelection | ProviderResult:
    candidates = registry.candidates(request)
    if not candidates:
        return _failure(request, ProviderErrorCode.NO_CAPABILITY, "capability unavailable")
    if offline:
        candidates = tuple(item for item in candidates if not item.manifest.network_access)
        if not candidates:
            return _failure(request, ProviderErrorCode.NETWORK_DISABLED, "offline policy")
    eligible = tuple(
        item
        for item in candidates
        if (
            set(item.operation.permissions)
            | (
                {ProviderPermission.NETWORK, ProviderPermission.DATA_EGRESS}
                & set(item.manifest.permissions)
            )
        )
        <= permissions
    )
    if not eligible:
        return _failure(request, ProviderErrorCode.PERMISSION_DENIED, "permission not granted")
    return eligible[0]


async def execute_provider(
    registry: ProviderRegistry,
    request: ProviderRequest,
    *,
    granted_permissions: Iterable[ProviderPermission] = (),
    offline: bool = True,
) -> ProviderResult:
    """Run one negotiated adapter with bounded wait, no automatic retry.

    Cancellation propagates. In particular a timed-out mutation may have
    succeeded remotely: the host must read back real state before retry.
    Invalid host request contracts raise a validation error before adapter access.
    """
    request = ProviderRequest.model_validate(request)
    selected = _select(
        registry, request, permissions=frozenset(granted_permissions), offline=offline
    )
    if isinstance(selected, ProviderResult):
        return selected
    op, manifest, adapter = selected.operation, selected.manifest, selected.adapter
    if not op.idempotent and request.idempotency_key is None:
        return _failure(
            request, ProviderErrorCode.PERMISSION_DENIED, "mutation requires idempotency key"
        )
    try:
        async with asyncio.timeout(request.timeout_seconds):
            readiness = await adapter.ready()
            if not isinstance(readiness, bool):
                return _failure(
                    request, ProviderErrorCode.MALFORMED_RESULT, "invalid readiness response"
                )
            if not readiness:
                return _failure(request, ProviderErrorCode.NOT_READY, "provider unavailable")
            raw = await adapter.invoke(request)
    except TimeoutError:
        return _failure(
            request, ProviderErrorCode.TIMEOUT, "provider timed out; mutation state unknown"
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return _failure(request, ProviderErrorCode.PROVIDER_FAILURE, "provider failed")
    try:
        result = ProviderResult.model_validate(raw)
    except (ValidationError, ValueError, TypeError):
        return _failure(request, ProviderErrorCode.MALFORMED_RESULT, "invalid provider envelope")
    if result.request_id != request.request_id:
        return _failure(request, ProviderErrorCode.MALFORMED_RESULT, "request ID mismatch")
    if result.ok:
        proof = result.provenance
        if proof is None or (
            proof.provider_id != manifest.provider_id
            or proof.provider_version != manifest.provider_version
            or proof.source != manifest.provenance_source
            or proof.deterministic != manifest.deterministic
        ):
            return _failure(request, ProviderErrorCode.MALFORMED_RESULT, "provenance mismatch")
    return result
