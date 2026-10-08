"""Experimental provider manifest and explicit capability/permission negotiation."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from kicad_mcp.project.hardware_intent_contract import StrictContractModel

from .contracts import IDENTIFIER, ProviderFamily, ProviderOperation, ProviderPermission


class ProviderManifest(StrictContractModel):
    sdk_version: Literal["0-experimental"]
    provider_id: str = Field(min_length=2, max_length=100, pattern=IDENTIFIER)
    provider_version: str = Field(min_length=1, max_length=64)
    family: ProviderFamily
    capabilities: tuple[str, ...] = Field(min_length=1)
    operations: tuple[ProviderOperation, ...] = Field(min_length=1)
    permissions: tuple[ProviderPermission, ...] = ()
    network_access: bool = False
    data_egress: bool = False
    network_hosts: tuple[str, ...] = ()
    deterministic: bool
    provenance_source: str = Field(min_length=1, max_length=200)
    healthcheck: str = Field(min_length=2, max_length=80, pattern=IDENTIFIER)
    license_id: str = Field(min_length=1, max_length=100)
    distribution_notes: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def check_declarations(self) -> ProviderManifest:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("duplicate capabilities")
        if any(re.fullmatch(IDENTIFIER, x) is None or len(x) > 80 for x in self.capabilities):
            raise ValueError("invalid capability name")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("duplicate declared permissions")
        if len({op.name for op in self.operations}) != len(self.operations):
            raise ValueError("duplicate operation name")
        for op in self.operations:
            if op.capability not in self.capabilities:
                raise ValueError("operation uses undeclared capability")
            if not set(op.permissions) <= set(self.permissions):
                raise ValueError("operation uses undeclared permission")
        return self

    @model_validator(mode="after")
    def check_network_declarations(self) -> ProviderManifest:
        if self.network_access != (ProviderPermission.NETWORK in self.permissions):
            raise ValueError("network declaration and permission disagree")
        if self.data_egress != (ProviderPermission.DATA_EGRESS in self.permissions):
            raise ValueError("egress declaration and permission disagree")
        if self.data_egress and not self.network_access:
            raise ValueError("egress requires network access")
        if self.network_access != bool(self.network_hosts):
            raise ValueError("network access requires explicit host declarations")
        if len(set(self.network_hosts)) != len(self.network_hosts):
            raise ValueError("duplicate network host")
        if any(
            not host or "*" in host or "/" in host or "://" in host for host in self.network_hosts
        ):
            raise ValueError("network hosts must be exact names")
        return self

    def find_operation(self, name: str, capability: str) -> ProviderOperation | None:
        return next(
            (op for op in self.operations if op.name == name and op.capability == capability),
            None,
        )
