"""In-memory Provider SDK registry independent of MCP transport and sessions."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import Provider, ProviderFamily, ProviderOperation, ProviderRequest
from .manifest import ProviderManifest


@dataclass(frozen=True)
class ProviderSelection:
    manifest: ProviderManifest
    adapter: Provider
    operation: ProviderOperation


class ProviderRegistry:
    """Only trusted, explicitly supplied adapters may be registered.

    No import-by-name, arbitrary plugin loading, filesystem scanning or remote
    discovery is performed. Registry lifetime belongs to the host process.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[ProviderManifest, Provider]] = {}

    def register(self, manifest: ProviderManifest, adapter: Provider) -> None:
        if manifest.provider_id in self._entries:
            raise ValueError("duplicate provider registration")
        if getattr(adapter, "family", None) != manifest.family:
            raise ValueError("provider family mismatch")
        self._entries[manifest.provider_id] = (manifest, adapter)

    def candidates(self, request: ProviderRequest) -> tuple[ProviderSelection, ...]:
        choices: list[ProviderSelection] = []
        for manifest, adapter in self._entries.values():
            operation = manifest.find_operation(request.operation, request.capability)
            if operation is not None:
                choices.append(ProviderSelection(manifest, adapter, operation))
        return tuple(sorted(choices, key=lambda x: x.manifest.provider_id))

    def advertised_families(self) -> frozenset[ProviderFamily]:
        return frozenset(manifest.family for manifest, _ in self._entries.values())
