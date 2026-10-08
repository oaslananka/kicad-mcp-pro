"""Experimental, versioned Provider SDK v0 types. No MCP/KiCad runtime dependency."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, JsonValue, model_validator

from kicad_mcp.project.hardware_intent_contract import StrictContractModel

SDK_VERSION = "0-experimental"
IDENTIFIER = r"^[a-z][a-z0-9_.-]*$"
SHA256 = r"^[0-9a-f]{64}$"


class ProviderFamily(StrEnum):
    PART = "part"
    SOLVER = "solver"
    ROUTER = "router"
    LAB_INSTRUMENT = "lab_instrument"


class ProviderPermission(StrEnum):
    PROJECT_READ = "project_read"
    PROJECT_WRITE = "project_write"
    NETWORK = "network"
    DATA_EGRESS = "data_egress"
    INSTRUMENT_CONTROL = "instrument_control"


class ProviderErrorCode(StrEnum):
    NO_CAPABILITY = "no_capability"
    NOT_READY = "not_ready"
    PERMISSION_DENIED = "permission_denied"
    NETWORK_DISABLED = "network_disabled"
    TIMEOUT = "timeout"
    MALFORMED_RESULT = "malformed_result"
    PROVIDER_FAILURE = "provider_failure"


class ProviderOperation(StrictContractModel):
    name: str = Field(min_length=2, max_length=80, pattern=IDENTIFIER)
    capability: str = Field(min_length=2, max_length=80, pattern=IDENTIFIER)
    permissions: tuple[ProviderPermission, ...] = ()
    idempotent: bool = True

    @model_validator(mode="after")
    def check_permissions(self) -> ProviderOperation:
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("duplicate operation permissions")
        if not self.idempotent and not {
            ProviderPermission.PROJECT_WRITE,
            ProviderPermission.INSTRUMENT_CONTROL,
        }.intersection(self.permissions):
            raise ValueError("non-idempotent operation requires mutation permission")
        return self


class ProviderRequest(StrictContractModel):
    schema_version: Literal[0] = 0
    request_id: str = Field(min_length=3, max_length=120, pattern=IDENTIFIER)
    capability: str = Field(min_length=2, max_length=80, pattern=IDENTIFIER)
    operation: str = Field(min_length=2, max_length=80, pattern=IDENTIFIER)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    idempotency_key: str | None = Field(
        default=None, min_length=3, max_length=120, pattern=IDENTIFIER
    )


class Provider(Protocol):
    async def ready(self) -> bool: ...
    async def invoke(self, request: ProviderRequest) -> object: ...
