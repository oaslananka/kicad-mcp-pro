"""Deterministic KiCad adapter selection and generated compatibility evidence.

The router remains the source of truth for public tool categories and the
capability registry remains the source of truth for each tool's runtime and
access tier.  This module combines those contracts with an explicit category
policy so KiCad GUI IPC, explicitly asserted KiCad 11 headless IPC, CLI, guarded file, and
external-engine fallbacks are observable rather than implicit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .capabilities import AccessTier, RuntimeRequirement
from .capabilities import get as get_capability

ADAPTER_MATRIX_SCHEMA_VERSION = "1.0.0"


class AdapterBackend(StrEnum):
    """Concrete execution backend selected for a routed tool."""

    KICAD_11_HEADLESS_IPC = "kicad-11-headless-ipc"
    KICAD_GUI_IPC = "kicad-gui-ipc"
    KICAD_CLI = "kicad-cli"
    GUARDED_SCHEMATIC_FILE = "guarded-schematic-file"
    TRANSACTIONAL_PCB_FILE = "transactional-pcb-file"
    LOCAL_FILESYSTEM = "local-filesystem"
    LOCAL_ENGINE = "local-engine"
    NETWORK = "network"
    NGSPICE = "ngspice"
    FREEROUTING = "freerouting"
    DOCKER = "docker"
    GIT = "git"
    UNAVAILABLE = "unavailable"


class KiCad11Support(StrEnum):
    """Readiness level for one routed category on the KiCad 11 line."""

    PREVIEW = "preview"
    PARTIAL = "partial"
    INDEPENDENT = "independent"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True, slots=True)
class CategoryAdapterPolicy:
    """Static policy and evidence expectations for a routed category."""

    preferred_backends: tuple[AdapterBackend, ...]
    kicad11_support: KiCad11Support
    canary_surfaces: tuple[str, ...]
    fallback_policy: str
    mutation_guard: str | None = None

    def to_contract(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible policy payload."""
        return {
            "preferredBackends": [backend.value for backend in self.preferred_backends],
            "kicad11Support": self.kicad11_support.value,
            "canarySurfaces": list(self.canary_surfaces),
            "fallbackPolicy": self.fallback_policy,
            "mutationGuard": self.mutation_guard,
        }


CATEGORY_ADAPTER_POLICIES: dict[str, CategoryAdapterPolicy] = {
    "project": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE, AdapterBackend.KICAD_CLI),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read",),
        fallback_policy=(
            "Use repository and filesystem discovery; use KiCad CLI only for native probes."
        ),
    ),
    "pcb_read": CategoryAdapterPolicy(
        preferred_backends=(
            AdapterBackend.KICAD_11_HEADLESS_IPC,
            AdapterBackend.KICAD_GUI_IPC,
            AdapterBackend.LOCAL_FILESYSTEM,
        ),
        kicad11_support=KiCad11Support.PREVIEW,
        canary_surfaces=("read",),
        fallback_policy=(
            "Prefer official IPC. File-backed parsers are permitted only for tools whose "
            "capability record does not require IPC."
        ),
    ),
    "pcb_write": CategoryAdapterPolicy(
        preferred_backends=(
            AdapterBackend.KICAD_11_HEADLESS_IPC,
            AdapterBackend.KICAD_GUI_IPC,
            AdapterBackend.TRANSACTIONAL_PCB_FILE,
        ),
        kicad11_support=KiCad11Support.PREVIEW,
        canary_surfaces=("write",),
        fallback_policy=(
            "Fail closed when an IPC-required mutation has no live backend. Explicit file-backed "
            "mutations use atomic replacement and post-write parsing."
        ),
        mutation_guard="ipc-transaction-or-atomic-parse-validation",
    ),
    "schematic": CategoryAdapterPolicy(
        preferred_backends=(
            AdapterBackend.KICAD_11_HEADLESS_IPC,
            AdapterBackend.KICAD_GUI_IPC,
            AdapterBackend.GUARDED_SCHEMATIC_FILE,
            AdapterBackend.KICAD_CLI,
        ),
        kicad11_support=KiCad11Support.PARTIAL,
        canary_surfaces=("read", "write", "export"),
        fallback_policy=(
            "Use IPC when required; otherwise use the transactional schematic writer with "
            "structural fingerprint loss detection and opportunistic IPC reload."
        ),
        mutation_guard="atomic-roundtrip-loss-detection",
    ),
    "library": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE, AdapterBackend.NETWORK),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read", "write"),
        fallback_policy=(
            "Use local KiCad libraries first; network enrichment is explicit and optional."
        ),
        mutation_guard="isolated-library-output-validation",
    ),
    "export": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.KICAD_CLI,),
        kicad11_support=KiCad11Support.PREVIEW,
        canary_surfaces=("export",),
        fallback_policy=(
            "Require a verified kicad-cli capability; never silently emulate native exports."
        ),
        mutation_guard="isolated-output-validation",
    ),
    "release_export": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.KICAD_CLI,),
        kicad11_support=KiCad11Support.PREVIEW,
        canary_surfaces=("export",),
        fallback_policy=(
            "Require KiCad CLI, release evidence, and the existing human approval gate."
        ),
        mutation_guard="human-gated-isolated-output-validation",
    ),
    "manufacturing": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.KICAD_CLI, AdapterBackend.LOCAL_FILESYSTEM),
        kicad11_support=KiCad11Support.PARTIAL,
        canary_surfaces=("read", "write", "export"),
        fallback_policy=(
            "Use CLI for native import/export and validated local transforms for metadata."
        ),
        mutation_guard="isolated-output-and-source-preservation",
    ),
    "validation": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.KICAD_CLI, AdapterBackend.LOCAL_ENGINE),
        kicad11_support=KiCad11Support.PARTIAL,
        canary_surfaces=("read", "export"),
        fallback_policy="Prefer native DRC/ERC; local checks must identify themselves as advisory.",
    ),
    "dfm": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE,),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read",),
        fallback_policy="Run deterministic local manufacturer-rule checks on parsed design data.",
    ),
    "routing": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.FREEROUTING, AdapterBackend.TRANSACTIONAL_PCB_FILE),
        kicad11_support=KiCad11Support.PARTIAL,
        canary_surfaces=("write", "export"),
        fallback_policy=(
            "External routing is explicit; session application uses validated transactional writes."
        ),
        mutation_guard="transactional-board-write-and-route-validation",
    ),
    "signal_integrity": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE,),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read", "write"),
        fallback_policy="Use deterministic analytical models and label results as advisory.",
        mutation_guard="validated-design-rule-write",
    ),
    "power_integrity": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE,),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read", "write"),
        fallback_policy="Use deterministic analytical models and explicit design-file writes.",
        mutation_guard="validated-design-rule-write",
    ),
    "emc": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.LOCAL_ENGINE,),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("write",),
        fallback_policy=(
            "Apply explicit, reviewable design changes without hidden native API fallback."
        ),
        mutation_guard="validated-design-file-write",
    ),
    "simulation": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.NGSPICE,),
        kicad11_support=KiCad11Support.NOT_APPLICABLE,
        canary_surfaces=("read", "write"),
        fallback_policy=(
            "Require ngspice for simulation; analytical substitutes must be separate tools."
        ),
        mutation_guard="isolated-simulation-artifacts",
    ),
    "version_control": CategoryAdapterPolicy(
        preferred_backends=(AdapterBackend.GIT,),
        kicad11_support=KiCad11Support.INDEPENDENT,
        canary_surfaces=("read", "write"),
        fallback_policy=(
            "Use isolated Git commands with hooks disabled and explicit confirmation for release "
            "tags."
        ),
        mutation_guard="git-checkpoint-and-confirmation",
    ),
}


@dataclass(frozen=True, slots=True)
class AdapterRuntimeContext:
    """Runtime facts used to select one adapter without hidden fallback."""

    kicad_major: int | None = None
    ipc_reachable: bool = False
    live_pcb_context: bool = False
    live_schematic_context: bool = False
    headless_ipc_available: bool = False
    cli_available: bool = False
    ngspice_available: bool = False
    freerouting_available: bool = False
    docker_available: bool = False
    network_available: bool = False

    def to_contract(self) -> dict[str, object]:
        """Return JSON-compatible diagnostics without secrets or paths."""
        return {
            "kicadMajor": self.kicad_major,
            "ipcReachable": self.ipc_reachable,
            "livePcbContext": self.live_pcb_context,
            "liveSchematicContext": self.live_schematic_context,
            "headlessIpcAvailable": self.headless_ipc_available,
            "cliAvailable": self.cli_available,
            "ngspiceAvailable": self.ngspice_available,
            "freeroutingAvailable": self.freerouting_available,
            "dockerAvailable": self.docker_available,
            "networkAvailable": self.network_available,
        }


@dataclass(frozen=True, slots=True)
class AdapterDecision:
    """Resolved adapter and reason for one public tool."""

    tool_name: str
    category: str
    backend: AdapterBackend
    available: bool
    reason: str
    fallback_chain: tuple[AdapterBackend, ...]
    mutation_guard: str | None

    def to_contract(self) -> dict[str, object]:
        """Return deterministic JSON-compatible decision metadata."""
        return {
            "tool": self.tool_name,
            "category": self.category,
            "backend": self.backend.value,
            "available": self.available,
            "reason": self.reason,
            "fallbackChain": [backend.value for backend in self.fallback_chain],
            "mutationGuard": self.mutation_guard,
        }

    def to_matrix_contract(self) -> dict[str, object]:
        """Return the compact per-scenario fields not already stored on the tool row."""
        return {
            "backend": self.backend.value,
            "available": self.available,
            "mutationGuard": self.mutation_guard,
        }


def _category_for_tool(tool_name: str) -> str:
    from .tools.router import TOOL_CATEGORIES

    categories = [
        category for category, detail in TOOL_CATEGORIES.items() if tool_name in detail["tools"]
    ]
    if len(categories) != 1:
        raise KeyError(
            f"Expected exactly one routed category for {tool_name!r}, found {categories!r}"
        )
    return categories[0]


def _file_backend(category: str) -> AdapterBackend:
    if category == "schematic":
        return AdapterBackend.GUARDED_SCHEMATIC_FILE
    if category in {"pcb_write", "routing"}:
        return AdapterBackend.TRANSACTIONAL_PCB_FILE
    if category == "version_control":
        return AdapterBackend.GIT
    return AdapterBackend.LOCAL_FILESYSTEM


def _mutation_guard(category: str, tier: AccessTier, backend: AdapterBackend) -> str | None:
    policy = CATEGORY_ADAPTER_POLICIES[category]
    if backend is AdapterBackend.KICAD_CLI and tier in {
        AccessTier.EXPORT,
        AccessTier.HUMAN_ONLY,
    }:
        return policy.mutation_guard or "isolated-output-validation"
    if backend in {
        AdapterBackend.GUARDED_SCHEMATIC_FILE,
        AdapterBackend.TRANSACTIONAL_PCB_FILE,
        AdapterBackend.LOCAL_FILESYSTEM,
        AdapterBackend.GIT,
    }:
        return policy.mutation_guard or "atomic-write-validation"
    if backend in {
        AdapterBackend.KICAD_11_HEADLESS_IPC,
        AdapterBackend.KICAD_GUI_IPC,
    } and tier in {AccessTier.WRITE, AccessTier.PUBLISH}:
        return "ipc-transaction-and-postcondition-check"
    return policy.mutation_guard if tier is not AccessTier.READ else None


def _ipc_context_available(category: str, context: AdapterRuntimeContext) -> bool:
    if category in {"pcb_read", "pcb_write"}:
        return context.live_pcb_context
    if category == "schematic":
        return context.live_schematic_context
    return True


def decision_for_tool(tool_name: str, context: AdapterRuntimeContext) -> AdapterDecision:
    """Resolve one tool adapter from declared capability and current runtime state."""
    record = get_capability(tool_name)
    if record is None:
        raise KeyError(f"No capability record for routed tool {tool_name!r}")
    category = _category_for_tool(tool_name)
    policy = CATEGORY_ADAPTER_POLICIES[category]
    runtime = record.runtime
    backend = AdapterBackend.UNAVAILABLE
    available = False
    reason: str

    if runtime is RuntimeRequirement.KICAD_IPC:
        if (
            context.headless_ipc_available
            and context.kicad_major is not None
            and context.kicad_major >= 11
        ):
            backend = AdapterBackend.KICAD_11_HEADLESS_IPC
            available = True
            reason = "KiCad 11+ headless IPC is reachable."
        elif context.ipc_reachable and _ipc_context_available(category, context):
            backend = AdapterBackend.KICAD_GUI_IPC
            available = True
            reason = "KiCad GUI IPC is reachable with the required live document context."
        else:
            reason = (
                "The tool requires KiCad IPC and no compatible live or headless context "
                "is available."
            )
    elif runtime is RuntimeRequirement.KICAD_CLI:
        if context.cli_available:
            backend = AdapterBackend.KICAD_CLI
            available = True
            reason = "A verified kicad-cli executable is available."
        else:
            reason = "The tool requires kicad-cli, which is unavailable."
    elif runtime is RuntimeRequirement.NGSPICE:
        if context.ngspice_available:
            backend = AdapterBackend.NGSPICE
            available = True
            reason = "ngspice is available."
        else:
            reason = "The tool requires ngspice, which is unavailable."
    elif runtime is RuntimeRequirement.FREEROUTING:
        if context.freerouting_available:
            backend = AdapterBackend.FREEROUTING
            available = True
            reason = "FreeRouting is available."
        else:
            reason = "The tool requires FreeRouting, which is unavailable."
    elif runtime is RuntimeRequirement.DOCKER:
        if context.docker_available:
            backend = AdapterBackend.DOCKER
            available = True
            reason = "Docker is available."
        else:
            reason = "The tool requires Docker, which is unavailable."
    elif runtime is RuntimeRequirement.NETWORK:
        if context.network_available:
            backend = AdapterBackend.NETWORK
            available = True
            reason = "Network access is explicitly available."
        else:
            reason = "The tool requires explicit network access, which is unavailable."
    else:
        if category == "version_control":
            backend = AdapterBackend.GIT
        elif record.writes_files:
            backend = _file_backend(category)
        else:
            backend = AdapterBackend.LOCAL_ENGINE
        available = True
        reason = "The tool uses a deterministic repository-local adapter."

    fallback_chain = (*policy.preferred_backends, AdapterBackend.UNAVAILABLE)
    return AdapterDecision(
        tool_name=tool_name,
        category=category,
        backend=backend,
        available=available,
        reason=reason,
        fallback_chain=fallback_chain,
        mutation_guard=_mutation_guard(category, record.tier, backend),
    )


def _all_routed_tools() -> list[str]:
    from .tools.router import TOOL_CATEGORIES

    return sorted(tool for detail in TOOL_CATEGORIES.values() for tool in detail["tools"])


def adapter_routing_contract(context: AdapterRuntimeContext) -> dict[str, object]:
    """Return compact runtime routing diagnostics grouped by public category."""
    from .tools.router import TOOL_CATEGORIES

    decisions = {tool: decision_for_tool(tool, context) for tool in _all_routed_tools()}
    categories: dict[str, object] = {}
    for category, detail in TOOL_CATEGORIES.items():
        rows = [decisions[tool] for tool in detail["tools"]]
        backends = Counter(row.backend.value for row in rows)
        categories[category] = {
            **CATEGORY_ADAPTER_POLICIES[category].to_contract(),
            "toolCount": len(rows),
            "availableCount": sum(row.available for row in rows),
            "blockedCount": sum(not row.available for row in rows),
            "selectedBackends": dict(sorted(backends.items())),
        }
    return {
        "schemaVersion": ADAPTER_MATRIX_SCHEMA_VERSION,
        "context": context.to_contract(),
        "categories": categories,
    }


def build_adapter_matrix_payload() -> dict[str, Any]:
    """Build the committed adapter matrix and three reference runtime scenarios."""
    from .tools.router import TOOL_CATEGORIES

    scenarios = {
        "kicad10Gui": AdapterRuntimeContext(
            kicad_major=10,
            ipc_reachable=True,
            live_pcb_context=True,
            live_schematic_context=True,
            cli_available=True,
            ngspice_available=True,
            freerouting_available=True,
            docker_available=True,
            network_available=True,
        ),
        "kicad11Headless": AdapterRuntimeContext(
            kicad_major=11,
            ipc_reachable=True,
            live_pcb_context=False,
            live_schematic_context=False,
            headless_ipc_available=True,
            cli_available=True,
            ngspice_available=True,
            freerouting_available=True,
            docker_available=True,
            network_available=True,
        ),
        "degradedNoKiCad": AdapterRuntimeContext(),
    }
    tools: list[dict[str, object]] = []
    for tool_name in _all_routed_tools():
        category = _category_for_tool(tool_name)
        record = get_capability(tool_name)
        if record is None:  # pragma: no cover - enforced by capability coverage tests
            raise KeyError(tool_name)
        tools.append(
            {
                "tool": tool_name,
                "category": category,
                "tier": record.tier.value,
                "runtime": record.runtime.value,
                "writesFiles": record.writes_files,
                "routes": {
                    name: decision_for_tool(tool_name, context).to_matrix_contract()
                    for name, context in scenarios.items()
                },
            }
        )
    return {
        "schemaVersion": ADAPTER_MATRIX_SCHEMA_VERSION,
        "summary": {
            "categoryCount": len(TOOL_CATEGORIES),
            "toolCount": len(tools),
            "stableBaseline": "10.0.x",
            "previewBaseline": "11.x",
            "publicSupportClaim": "KiCad 11 remains preview until native canaries pass.",
        },
        "categories": {
            category: {
                "description": TOOL_CATEGORIES[category]["description"],
                **policy.to_contract(),
            }
            for category, policy in CATEGORY_ADAPTER_POLICIES.items()
        },
        "scenarios": {
            name: adapter_routing_contract(context) for name, context in scenarios.items()
        },
        "tools": tools,
    }
