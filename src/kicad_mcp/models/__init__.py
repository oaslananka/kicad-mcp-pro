"""Typed models used by tool modules."""

from .export import ExportBOMInput, ExportGerberInput
from .live_preview import (
    LivePreviewArtifact,
    LivePreviewDebounce,
    LivePreviewManifest,
    LivePreviewPayload,
    LivePreviewRender,
    LivePreviewSafety,
    LivePreviewWatch,
)
from .pcb import (
    AddCircleInput,
    AddRectangleInput,
    AddTrackInput,
    AddViaInput,
    CreepageCheckInput,
    ImpedanceForTraceInput,
    LayerViaInput,
    SetStackupInput,
    StackupLayerSpec,
)
from .power_integrity import (
    CopperWeightCheckInput,
    DecouplingRecommendationInput,
    VoltageDropInput,
)
from .schematic import AddLabelInput, AddSymbolInput, AddWireInput
from .signal_integrity import (
    DifferentialPairSkewInput,
    LengthMatchingInput,
    StackupInput,
    TraceImpedanceInput,
    TraceWidthForImpedanceInput,
)
from .simulation import ACAnalysisInput, DCSweepInput, OperatingPointInput, TransientAnalysisInput
from .state import (
    AgentRunState,
    BoardState,
    CapabilityState,
    ManufacturingState,
    ProjectState,
    SchematicState,
    VerificationState,
    WorkspaceState,
)
from .tool_result import ArtifactRef, StateDelta, ToolResult
from .verdict import FailureMode, Finding, SuggestedFix, Verdict, VerdictReport, stable_finding_id

__all__ = [
    "ACAnalysisInput",
    "AddCircleInput",
    "AddLabelInput",
    "AddRectangleInput",
    "AddSymbolInput",
    "AddTrackInput",
    "AddViaInput",
    "AddWireInput",
    "AgentRunState",
    "ArtifactRef",
    "BoardState",
    "CapabilityState",
    "CopperWeightCheckInput",
    "CreepageCheckInput",
    "DecouplingRecommendationInput",
    "DCSweepInput",
    "DifferentialPairSkewInput",
    "ExportBOMInput",
    "ExportGerberInput",
    "FailureMode",
    "Finding",
    "ImpedanceForTraceInput",
    "LayerViaInput",
    "LengthMatchingInput",
    "LivePreviewArtifact",
    "LivePreviewDebounce",
    "LivePreviewManifest",
    "LivePreviewPayload",
    "LivePreviewRender",
    "LivePreviewSafety",
    "LivePreviewWatch",
    "ManufacturingState",
    "OperatingPointInput",
    "ProjectState",
    "SchematicState",
    "SetStackupInput",
    "SuggestedFix",
    "StackupInput",
    "StackupLayerSpec",
    "StateDelta",
    "ToolResult",
    "TraceImpedanceInput",
    "TraceWidthForImpedanceInput",
    "TransientAnalysisInput",
    "Verdict",
    "VerdictReport",
    "VerificationState",
    "VoltageDropInput",
    "WorkspaceState",
    "stable_finding_id",
]
