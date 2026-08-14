"""Check incremental domain-boundary guards for the tool refactor.

This is intentionally narrow: it protects the first extracted helper modules from
sliding back into the schematic/PCB/server monoliths while the larger split
continues incrementally.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

_EXPORT_PCB_3D_RENDER_ADAPTER = "kicad_mcp.tools.export_pcb_3d_render"
_EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER = "kicad_mcp.tools.export_pcb_manufacturing_outputs"
_EXPORT_MANUFACTURING_PACKAGE_ADAPTER = "kicad_mcp.tools.export_manufacturing_package"
_LIBRARY_CATALOG_ADAPTER = "kicad_mcp.tools.library_catalog"
_LIBRARY_DATASHEET_ADAPTER = "kicad_mcp.tools.library_datasheet"
_LIBRARY_LOCAL_AUTHORING_ADAPTER = "kicad_mcp.tools.library_local_authoring"
_LIBRARY_COMPONENT_CONTRACT_ADAPTER = "kicad_mcp.tools.library_component_contract"

_TOOLS_PCB = "kicad_mcp.tools.pcb"
_TOOLS_SCHEMATIC = "kicad_mcp.tools.schematic"
_TOOLS_VALIDATION = "kicad_mcp.tools.validation"
_TOOLS_EXPORT_BOM = "kicad_mcp.tools.export_bom"
_TOOLS_EXPORT_BOARD_STATS = "kicad_mcp.tools.export_board_stats"
_TOOLS_EXPORT_DRILL = "kicad_mcp.tools.export_drill"
_TOOLS_EXPORT_GERBER = "kicad_mcp.tools.export_gerber"
_TOOLS_EXPORT_NETLIST = "kicad_mcp.tools.export_netlist"
_TOOLS_EXPORT_PCB_3D_PDF = "kicad_mcp.tools.export_pcb_3d_pdf"
_TOOLS_EXPORT_PCB_FILE_FORMATS = "kicad_mcp.tools.export_pcb_file_formats"
_TOOLS_EXPORT_PCB_PDF = "kicad_mcp.tools.export_pcb_pdf"
_TOOLS_EXPORT_PCB_VECTOR = "kicad_mcp.tools.export_pcb_vector"
_TOOLS_EXPORT_SCH_PDF = "kicad_mcp.tools.export_sch_pdf"
_TOOLS_EXPORT_SCH_PYTHON_BOM = "kicad_mcp.tools.export_sch_python_bom"
_TOOLS_EXPORT_SCH_VECTOR = "kicad_mcp.tools.export_sch_vector"
_TOOLS_VALIDATION_POLICY_STATE = "kicad_mcp.tools.validation_policy_state"
_PCB_BOARD_ACCESS = "kicad_mcp.pcb.board_access"
_PCB_GEOMETRY = "kicad_mcp.pcb.geometry"
_TOOLS_PCB_GROUPS_INSPECTION = "kicad_mcp.tools.pcb_groups_inspection"
_TOOLS_PCB_BOARD_INSPECTION = "kicad_mcp.tools.pcb_board_inspection"
_TOOLS_PCB_BASIC_INSPECTION = "kicad_mcp.tools.pcb_basic_inspection"
_TOOLS_PCB_FILE_INSPECTION = "kicad_mcp.tools.pcb_file_inspection"
_TOOLS_PCB_ORIGIN_MANAGEMENT = "kicad_mcp.tools.pcb_origin_management"
_TOOLS_PCB_SESSION_INSPECTION = "kicad_mcp.tools.pcb_session_inspection"
_TOOLS_PCB_STACKUP_MANAGEMENT = "kicad_mcp.tools.pcb_stackup_management"
_TOOLS_PCB_TITLE_BLOCK_MANAGEMENT = "kicad_mcp.tools.pcb_title_block_management"
_TOOLS_PCB_TRANSACTION_LIFECYCLE = "kicad_mcp.tools.pcb_transaction_lifecycle"
_TOOLS_SCHEMATIC_BACK_ANNOTATION = "kicad_mcp.tools.schematic_back_annotation"
_TOOLS_SCHEMATIC_BASIC_AUTHORING = "kicad_mcp.tools.schematic_basic_authoring"
_TOOLS_SCHEMATIC_CIRCUIT_COMPILATION = "kicad_mcp.tools.schematic_circuit_compilation"
_TOOLS_SCHEMATIC_CONNECTIVITY_AUTHORING = "kicad_mcp.tools.schematic_connectivity_authoring"
_TOOLS_SCHEMATIC_DESTRUCTIVE_EDIT = "kicad_mcp.tools.schematic_destructive_edit"
_TOOLS_SCHEMATIC_DOCUMENT_SETTINGS = "kicad_mcp.tools.schematic_document_settings"
_TOOLS_SCHEMATIC_SYMBOL_MUTATION = "kicad_mcp.tools.schematic_symbol_mutation"
_TOOLS_SCHEMATIC_TEMPLATE_CATALOG = "kicad_mcp.tools.schematic_template_catalog"
_TOOLS_SCHEMATIC_TEMPLATE_INSTANTIATION = "kicad_mcp.tools.schematic_template_instantiation"
_TOOLS_SCHEMATIC_TOPOLOGY = "kicad_mcp.tools.schematic_topology"
_TOOLS_SCHEMATIC_HIERARCHY_AUTHORING = "kicad_mcp.tools.schematic_hierarchy_authoring"
_TOOLS_SCHEMATIC_INSPECTION = "kicad_mcp.tools.schematic_inspection"
_TOOLS_SCHEMATIC_LIFECYCLE_AUTHORING = "kicad_mcp.tools.schematic_lifecycle_authoring"
_TOOLS_SCHEMATIC_LAYOUT_AUTOMATION = "kicad_mcp.tools.schematic_layout_automation"
_TOOLS_SCHEMATIC_LAYOUT_INSPECTION = "kicad_mcp.tools.schematic_layout_inspection"
_TOOLS_SCHEMATIC_RENDERING = "kicad_mcp.tools.schematic_rendering"
_TOOLS_SCHEMATIC_SEMANTIC_IR = "kicad_mcp.tools.schematic_semantic_ir"

DOMAIN_MODULES = {
    _TOOLS_PCB: SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py",
    "kicad_mcp.export.board_stats": SRC_ROOT / "kicad_mcp" / "export" / "board_stats.py",
    "kicad_mcp.export.bom": SRC_ROOT / "kicad_mcp" / "export" / "bom.py",
    "kicad_mcp.export.drill": SRC_ROOT / "kicad_mcp" / "export" / "drill.py",
    "kicad_mcp.export.gerber": SRC_ROOT / "kicad_mcp" / "export" / "gerber.py",
    "kicad_mcp.export.manufacturing_package": SRC_ROOT
    / "kicad_mcp"
    / "export"
    / "manufacturing_package.py",
    "kicad_mcp.export.netlist": SRC_ROOT / "kicad_mcp" / "export" / "netlist.py",
    "kicad_mcp.export.pcb_3d_pdf": SRC_ROOT / "kicad_mcp" / "export" / "pcb_3d_pdf.py",
    "kicad_mcp.export.pcb_3d_render": SRC_ROOT / "kicad_mcp" / "export" / "pcb_3d_render.py",
    "kicad_mcp.export.pcb_file_formats": SRC_ROOT / "kicad_mcp" / "export" / "pcb_file_formats.py",
    "kicad_mcp.export.pcb_manufacturing_outputs": SRC_ROOT
    / "kicad_mcp"
    / "export"
    / "pcb_manufacturing_outputs.py",
    "kicad_mcp.export.pcb_pdf": SRC_ROOT / "kicad_mcp" / "export" / "pcb_pdf.py",
    "kicad_mcp.export.pcb_vector": SRC_ROOT / "kicad_mcp" / "export" / "pcb_vector.py",
    "kicad_mcp.export.sch_pdf": SRC_ROOT / "kicad_mcp" / "export" / "sch_pdf.py",
    "kicad_mcp.export.sch_python_bom": SRC_ROOT / "kicad_mcp" / "export" / "sch_python_bom.py",
    "kicad_mcp.export.sch_vector": SRC_ROOT / "kicad_mcp" / "export" / "sch_vector.py",
    "kicad_mcp.library.catalog": SRC_ROOT / "kicad_mcp" / "library" / "catalog.py",
    "kicad_mcp.library.local_authoring": SRC_ROOT / "kicad_mcp" / "library" / "local_authoring.py",
    "kicad_mcp.library.component_contract": SRC_ROOT
    / "kicad_mcp"
    / "library"
    / "component_contract.py",
    _TOOLS_EXPORT_BOM: SRC_ROOT / "kicad_mcp" / "tools" / "export_bom.py",
    _TOOLS_EXPORT_BOARD_STATS: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_board_stats.py",
    _TOOLS_EXPORT_DRILL: SRC_ROOT / "kicad_mcp" / "tools" / "export_drill.py",
    _TOOLS_EXPORT_GERBER: SRC_ROOT / "kicad_mcp" / "tools" / "export_gerber.py",
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_manufacturing_package.py",
    _TOOLS_EXPORT_NETLIST: SRC_ROOT / "kicad_mcp" / "tools" / "export_netlist.py",
    _TOOLS_EXPORT_PCB_3D_PDF: SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_3d_pdf.py",
    _EXPORT_PCB_3D_RENDER_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_3d_render.py",
    _TOOLS_EXPORT_PCB_FILE_FORMATS: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_pcb_file_formats.py",
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_pcb_manufacturing_outputs.py",
    _TOOLS_EXPORT_PCB_PDF: SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_pdf.py",
    _TOOLS_EXPORT_PCB_VECTOR: SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_vector.py",
    _TOOLS_EXPORT_SCH_PDF: SRC_ROOT / "kicad_mcp" / "tools" / "export_sch_pdf.py",
    _TOOLS_EXPORT_SCH_PYTHON_BOM: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_sch_python_bom.py",
    _TOOLS_EXPORT_SCH_VECTOR: SRC_ROOT / "kicad_mcp" / "tools" / "export_sch_vector.py",
    _LIBRARY_CATALOG_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "library_catalog.py",
    _LIBRARY_DATASHEET_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "library_datasheet.py",
    _LIBRARY_LOCAL_AUTHORING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "library_local_authoring.py",
    _LIBRARY_COMPONENT_CONTRACT_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "library_component_contract.py",
    _TOOLS_VALIDATION: SRC_ROOT / "kicad_mcp" / "tools" / "validation.py",
    "kicad_mcp.validation.drc_runner": SRC_ROOT / "kicad_mcp" / "validation" / "drc_runner.py",
    "kicad_mcp.validation.policy_state": SRC_ROOT / "kicad_mcp" / "validation" / "policy_state.py",
    _TOOLS_VALIDATION_POLICY_STATE: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "validation_policy_state.py",
    _TOOLS_SCHEMATIC: SRC_ROOT / "kicad_mcp" / "tools" / "schematic.py",
    "kicad_mcp.companion.context": SRC_ROOT / "kicad_mcp" / "companion" / "context.py",
    "kicad_mcp.ipc.command_queue": SRC_ROOT / "kicad_mcp" / "ipc" / "command_queue.py",
    "kicad_mcp.models.contract_verifier": SRC_ROOT
    / "kicad_mcp"
    / "models"
    / "contract_verifier.py",
    "kicad_mcp.models.sch_transaction": SRC_ROOT / "kicad_mcp" / "models" / "sch_transaction.py",
    "kicad_mcp.models.visual_qa": SRC_ROOT / "kicad_mcp" / "models" / "visual_qa.py",
    "kicad_mcp.pcb.basic_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "basic_inspection.py",
    _PCB_BOARD_ACCESS: SRC_ROOT / "kicad_mcp" / "pcb" / "board_access.py",
    _PCB_GEOMETRY: SRC_ROOT / "kicad_mcp" / "pcb" / "geometry.py",
    "kicad_mcp.pcb.file_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "file_inspection.py",
    "kicad_mcp.pcb.groups_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "groups_inspection.py",
    "kicad_mcp.pcb.origin_management": SRC_ROOT / "kicad_mcp" / "pcb" / "origin_management.py",
    "kicad_mcp.pcb.session_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "session_inspection.py",
    "kicad_mcp.pcb.title_block_management": SRC_ROOT
    / "kicad_mcp"
    / "pcb"
    / "title_block_management.py",
    "kicad_mcp.pcb.transaction_lifecycle": SRC_ROOT
    / "kicad_mcp"
    / "pcb"
    / "transaction_lifecycle.py",
    "kicad_mcp.schematic.back_annotation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "back_annotation.py",
    "kicad_mcp.schematic.basic_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "basic_authoring.py",
    "kicad_mcp.schematic.circuit_compilation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "circuit_compilation.py",
    "kicad_mcp.schematic.connectivity_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "connectivity_authoring.py",
    "kicad_mcp.schematic.destructive_edit": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "destructive_edit.py",
    "kicad_mcp.schematic.document_settings": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "document_settings.py",
    "kicad_mcp.schematic.hierarchy_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "hierarchy_authoring.py",
    "kicad_mcp.schematic.inspection": SRC_ROOT / "kicad_mcp" / "schematic" / "inspection.py",
    "kicad_mcp.schematic.lifecycle_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "lifecycle_authoring.py",
    "kicad_mcp.schematic.layout_automation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "layout_automation.py",
    "kicad_mcp.schematic.layout_inspection": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "layout_inspection.py",
    "kicad_mcp.schematic.rendering": SRC_ROOT / "kicad_mcp" / "schematic" / "rendering.py",
    "kicad_mcp.schematic.semantic_ir": SRC_ROOT / "kicad_mcp" / "schematic" / "semantic_ir.py",
    "kicad_mcp.schematic.sheet_pins": SRC_ROOT / "kicad_mcp" / "schematic" / "sheet_pins.py",
    "kicad_mcp.schematic.sheet_wiring": SRC_ROOT / "kicad_mcp" / "schematic" / "sheet_wiring.py",
    "kicad_mcp.schematic.symbol_mutation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "symbol_mutation.py",
    "kicad_mcp.schematic.template_catalog": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "template_catalog.py",
    "kicad_mcp.schematic.template_instantiation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "template_instantiation.py",
    "kicad_mcp.schematic.topology": SRC_ROOT / "kicad_mcp" / "schematic" / "topology.py",
    _TOOLS_PCB_GROUPS_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_groups_inspection.py",
    "kicad_mcp.pcb.board_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "board_inspection.py",
    _TOOLS_PCB_BOARD_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_board_inspection.py",
    _TOOLS_PCB_BASIC_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_basic_inspection.py",
    _TOOLS_PCB_FILE_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_file_inspection.py",
    _TOOLS_PCB_ORIGIN_MANAGEMENT: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_origin_management.py",
    _TOOLS_PCB_SESSION_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_session_inspection.py",
    "kicad_mcp.pcb.stackup_management": SRC_ROOT / "kicad_mcp" / "pcb" / "stackup_management.py",
    _TOOLS_PCB_STACKUP_MANAGEMENT: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_stackup_management.py",
    _TOOLS_PCB_TITLE_BLOCK_MANAGEMENT: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_title_block_management.py",
    _TOOLS_PCB_TRANSACTION_LIFECYCLE: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_transaction_lifecycle.py",
    _TOOLS_SCHEMATIC_BACK_ANNOTATION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_back_annotation.py",
    _TOOLS_SCHEMATIC_BASIC_AUTHORING: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_basic_authoring.py",
    _TOOLS_SCHEMATIC_CIRCUIT_COMPILATION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_circuit_compilation.py",
    _TOOLS_SCHEMATIC_CONNECTIVITY_AUTHORING: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_connectivity_authoring.py",
    _TOOLS_SCHEMATIC_DESTRUCTIVE_EDIT: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_destructive_edit.py",
    _TOOLS_SCHEMATIC_DOCUMENT_SETTINGS: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_document_settings.py",
    _TOOLS_SCHEMATIC_SYMBOL_MUTATION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_symbol_mutation.py",
    _TOOLS_SCHEMATIC_TEMPLATE_CATALOG: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_catalog.py",
    _TOOLS_SCHEMATIC_TEMPLATE_INSTANTIATION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_instantiation.py",
    _TOOLS_SCHEMATIC_TOPOLOGY: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_topology.py",
    _TOOLS_SCHEMATIC_HIERARCHY_AUTHORING: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_hierarchy_authoring.py",
    _TOOLS_SCHEMATIC_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_inspection.py",
    _TOOLS_SCHEMATIC_LIFECYCLE_AUTHORING: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_lifecycle_authoring.py",
    _TOOLS_SCHEMATIC_LAYOUT_AUTOMATION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_automation.py",
    _TOOLS_SCHEMATIC_LAYOUT_INSPECTION: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_inspection.py",
    _TOOLS_SCHEMATIC_RENDERING: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_rendering.py",
    _TOOLS_SCHEMATIC_SEMANTIC_IR: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_semantic_ir.py",
    "kicad_mcp.tools.schematic_constants": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_constants.py",
    "kicad_mcp.tools.schematic_transfer": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_transfer.py",
}

PURE_HELPERS = {
    "kicad_mcp.validation.drc_runner",
    "kicad_mcp.export.board_stats",
    "kicad_mcp.export.bom",
    "kicad_mcp.export.drill",
    "kicad_mcp.export.gerber",
    "kicad_mcp.export.manufacturing_package",
    "kicad_mcp.export.netlist",
    "kicad_mcp.export.pcb_3d_pdf",
    "kicad_mcp.export.pcb_3d_render",
    "kicad_mcp.export.pcb_file_formats",
    "kicad_mcp.export.pcb_manufacturing_outputs",
    "kicad_mcp.export.pcb_pdf",
    "kicad_mcp.export.pcb_vector",
    "kicad_mcp.export.sch_pdf",
    "kicad_mcp.export.sch_python_bom",
    "kicad_mcp.export.sch_vector",
    "kicad_mcp.library.catalog",
    "kicad_mcp.library.local_authoring",
    "kicad_mcp.library.component_contract",
    "kicad_mcp.validation.policy_state",
    "kicad_mcp.companion.context",
    "kicad_mcp.ipc.command_queue",
    "kicad_mcp.models.contract_verifier",
    "kicad_mcp.models.sch_transaction",
    "kicad_mcp.models.visual_qa",
    "kicad_mcp.pcb.basic_inspection",
    _PCB_BOARD_ACCESS,
    "kicad_mcp.pcb.board_inspection",
    _PCB_GEOMETRY,
    "kicad_mcp.pcb.file_inspection",
    "kicad_mcp.pcb.groups_inspection",
    "kicad_mcp.pcb.origin_management",
    "kicad_mcp.pcb.session_inspection",
    "kicad_mcp.pcb.stackup_management",
    "kicad_mcp.pcb.title_block_management",
    "kicad_mcp.pcb.transaction_lifecycle",
    "kicad_mcp.schematic.back_annotation",
    "kicad_mcp.schematic.basic_authoring",
    "kicad_mcp.schematic.circuit_compilation",
    "kicad_mcp.schematic.connectivity_authoring",
    "kicad_mcp.schematic.destructive_edit",
    "kicad_mcp.schematic.document_settings",
    "kicad_mcp.schematic.hierarchy_authoring",
    "kicad_mcp.schematic.inspection",
    "kicad_mcp.schematic.lifecycle_authoring",
    "kicad_mcp.schematic.layout_automation",
    "kicad_mcp.schematic.layout_inspection",
    "kicad_mcp.schematic.rendering",
    "kicad_mcp.schematic.semantic_ir",
    "kicad_mcp.schematic.sheet_pins",
    "kicad_mcp.schematic.sheet_wiring",
    "kicad_mcp.schematic.symbol_mutation",
    "kicad_mcp.schematic.template_catalog",
    "kicad_mcp.schematic.template_instantiation",
    "kicad_mcp.schematic.topology",
    "kicad_mcp.tools.schematic_constants",
}

FORBIDDEN_PURE_IMPORT_PREFIXES = (
    "kicad_mcp.server",
    "kicad_mcp.connection",
    _TOOLS_PCB,
    _TOOLS_SCHEMATIC,
    "mcp",
    "pcbnew",
    "wx",
    "kipy",
)

ADAPTER_FORBIDDEN_IMPORT_PREFIXES = {
    _TOOLS_VALIDATION_POLICY_STATE: (_TOOLS_VALIDATION,),
    _TOOLS_EXPORT_BOM: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_BOARD_STATS: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_DRILL: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_GERBER: ("kicad_mcp.tools.export",),
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_NETLIST: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_PCB_3D_PDF: ("kicad_mcp.tools.export",),
    _EXPORT_PCB_3D_RENDER_ADAPTER: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_PCB_FILE_FORMATS: ("kicad_mcp.tools.export",),
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_PCB_PDF: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_PCB_VECTOR: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_SCH_PDF: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_SCH_PYTHON_BOM: ("kicad_mcp.tools.export",),
    _TOOLS_EXPORT_SCH_VECTOR: ("kicad_mcp.tools.export",),
    _LIBRARY_CATALOG_ADAPTER: ("kicad_mcp.tools.library",),
    _LIBRARY_DATASHEET_ADAPTER: ("kicad_mcp.tools.library",),
    _TOOLS_PCB_BASIC_INSPECTION: (_TOOLS_PCB,),
    _TOOLS_PCB_BOARD_INSPECTION: (_TOOLS_PCB,),
    _TOOLS_PCB_FILE_INSPECTION: (_TOOLS_PCB,),
    _TOOLS_PCB_GROUPS_INSPECTION: (_TOOLS_PCB,),
    _TOOLS_PCB_ORIGIN_MANAGEMENT: (_TOOLS_PCB,),
    _TOOLS_PCB_SESSION_INSPECTION: (_TOOLS_PCB,),
    _TOOLS_PCB_STACKUP_MANAGEMENT: (_TOOLS_PCB,),
    _TOOLS_PCB_TITLE_BLOCK_MANAGEMENT: (_TOOLS_PCB,),
    _TOOLS_PCB_TRANSACTION_LIFECYCLE: (_TOOLS_PCB,),
    _TOOLS_SCHEMATIC_BACK_ANNOTATION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_BASIC_AUTHORING: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_CIRCUIT_COMPILATION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_CONNECTIVITY_AUTHORING: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_DESTRUCTIVE_EDIT: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_DOCUMENT_SETTINGS: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_HIERARCHY_AUTHORING: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_INSPECTION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_LIFECYCLE_AUTHORING: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_LAYOUT_AUTOMATION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_LAYOUT_INSPECTION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_RENDERING: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_SEMANTIC_IR: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_SYMBOL_MUTATION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_TEMPLATE_CATALOG: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_TEMPLATE_INSTANTIATION: (_TOOLS_SCHEMATIC,),
    _TOOLS_SCHEMATIC_TOPOLOGY: (_TOOLS_SCHEMATIC,),
}

REGISTER_LINE_LIMITS = {
    _TOOLS_PCB: 300,
    _TOOLS_EXPORT_BOM: 100,
    _TOOLS_EXPORT_BOARD_STATS: 100,
    _TOOLS_EXPORT_DRILL: 100,
    _TOOLS_EXPORT_GERBER: 100,
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: 100,
    _TOOLS_EXPORT_NETLIST: 100,
    _TOOLS_EXPORT_PCB_3D_PDF: 100,
    _EXPORT_PCB_3D_RENDER_ADAPTER: 140,
    _TOOLS_EXPORT_PCB_FILE_FORMATS: 100,
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: 100,
    _TOOLS_EXPORT_PCB_PDF: 100,
    _TOOLS_EXPORT_PCB_VECTOR: 100,
    _TOOLS_EXPORT_SCH_PDF: 100,
    _TOOLS_EXPORT_SCH_PYTHON_BOM: 100,
    _TOOLS_EXPORT_SCH_VECTOR: 100,
    _LIBRARY_CATALOG_ADAPTER: 160,
    _LIBRARY_DATASHEET_ADAPTER: 100,
    _LIBRARY_LOCAL_AUTHORING_ADAPTER: 100,
    _LIBRARY_COMPONENT_CONTRACT_ADAPTER: 100,
    _TOOLS_VALIDATION: 300,
    _TOOLS_VALIDATION_POLICY_STATE: 300,
    _TOOLS_PCB_BASIC_INSPECTION: 300,
    _TOOLS_PCB_BOARD_INSPECTION: 300,
    _TOOLS_PCB_FILE_INSPECTION: 300,
    _TOOLS_PCB_GROUPS_INSPECTION: 300,
    _TOOLS_PCB_ORIGIN_MANAGEMENT: 300,
    _TOOLS_PCB_SESSION_INSPECTION: 300,
    _TOOLS_PCB_STACKUP_MANAGEMENT: 300,
    _TOOLS_PCB_TITLE_BLOCK_MANAGEMENT: 300,
    _TOOLS_PCB_TRANSACTION_LIFECYCLE: 300,
    _TOOLS_SCHEMATIC: 300,
    _TOOLS_SCHEMATIC_BACK_ANNOTATION: 300,
    _TOOLS_SCHEMATIC_BASIC_AUTHORING: 300,
    _TOOLS_SCHEMATIC_CIRCUIT_COMPILATION: 300,
    _TOOLS_SCHEMATIC_CONNECTIVITY_AUTHORING: 300,
    _TOOLS_SCHEMATIC_DESTRUCTIVE_EDIT: 300,
    _TOOLS_SCHEMATIC_DOCUMENT_SETTINGS: 300,
    _TOOLS_SCHEMATIC_HIERARCHY_AUTHORING: 300,
    _TOOLS_SCHEMATIC_INSPECTION: 300,
    _TOOLS_SCHEMATIC_LIFECYCLE_AUTHORING: 300,
    _TOOLS_SCHEMATIC_LAYOUT_AUTOMATION: 300,
    _TOOLS_SCHEMATIC_LAYOUT_INSPECTION: 300,
    _TOOLS_SCHEMATIC_RENDERING: 300,
    _TOOLS_SCHEMATIC_SEMANTIC_IR: 300,
    _TOOLS_SCHEMATIC_SYMBOL_MUTATION: 300,
    _TOOLS_SCHEMATIC_TEMPLATE_CATALOG: 300,
    _TOOLS_SCHEMATIC_TEMPLATE_INSTANTIATION: 300,
    _TOOLS_SCHEMATIC_TOPOLOGY: 300,
}


CANONICAL_HELPER_OWNERS = {
    "board_tracks": Path("kicad_mcp/pcb/board_access.py"),
    "board_vias": Path("kicad_mcp/pcb/board_access.py"),
    "board_footprints": Path("kicad_mcp/pcb/board_access.py"),
    "board_pads": Path("kicad_mcp/pcb/board_access.py"),
    "board_zones": Path("kicad_mcp/pcb/board_access.py"),
    "board_shapes": Path("kicad_mcp/pcb/board_access.py"),
    "board_nets": Path("kicad_mcp/pcb/board_access.py"),
    "board_nets_filtered": Path("kicad_mcp/pcb/board_access.py"),
    "point_xy_mm": Path("kicad_mcp/pcb/geometry.py"),
    "track_segment_length_mm": Path("kicad_mcp/pcb/geometry.py"),
    "classify_drc_report": Path("kicad_mcp/validation/drc_runner.py"),
    "classify_legacy_drc_result": Path("kicad_mcp/validation/drc_runner.py"),
    "run_drc_report": Path("kicad_mcp/validation/drc_runner.py"),
}

LEGACY_HELPER_REPLACEMENTS = {
    "_board_tracks": ("board_tracks", _PCB_BOARD_ACCESS),
    "_board_vias": ("board_vias", _PCB_BOARD_ACCESS),
    "_board_footprints": ("board_footprints", _PCB_BOARD_ACCESS),
    "_board_pads": ("board_pads", _PCB_BOARD_ACCESS),
    "_board_zones": ("board_zones", _PCB_BOARD_ACCESS),
    "_board_shapes": ("board_shapes", _PCB_BOARD_ACCESS),
    "_board_nets": ("board_nets", _PCB_BOARD_ACCESS),
    "_track_length_mm": ("track_segment_length_mm", _PCB_GEOMETRY),
    "_footprint_position_mm": ("point_xy_mm", _PCB_GEOMETRY),
}


def _source_location(source_root: Path, path: Path, line: int) -> str:
    return f"src/{path.relative_to(source_root).as_posix()}:{line}"


def _targeted_helper_definition_errors(
    source_root: Path,
    *,
    canonical_owners: dict[str, Path] | None = None,
    legacy_replacements: dict[str, tuple[str, str]] | None = None,
) -> list[str]:
    """Return actionable errors for duplicated correctness-sensitive helpers.

    Only top-level functions under ``src`` are inspected. Protocol/class methods,
    nested fixtures, and distinctly named domain-specific helpers are intentionally
    outside this narrow guard.
    """
    owners = CANONICAL_HELPER_OWNERS if canonical_owners is None else canonical_owners
    replacements = (
        LEGACY_HELPER_REPLACEMENTS if legacy_replacements is None else legacy_replacements
    )
    target_names = set(owners) | set(replacements)
    definitions: dict[str, list[tuple[Path, int]]] = {name: [] for name in target_names}
    errors: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(
                f"Could not inspect targeted shared helpers in "
                f"{_source_location(source_root, path, exc.lineno or 1)}: {exc.msg}."
            )
            continue
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in target_names
            ):
                definitions[node.name].append((path, node.lineno))

    for helper_name, owner in sorted(owners.items()):
        found = definitions.get(helper_name, [])
        expected = source_root / owner
        if len(found) == 1 and found[0][0] == expected:
            continue
        locations = (
            ", ".join(_source_location(source_root, found_path, line) for found_path, line in found)
            or "no definition"
        )
        errors.append(
            f"Targeted shared helper '{helper_name}' must be defined exactly once in "
            f"src/{owner.as_posix()}; found {locations}. Import the canonical helper or "
            "use a distinctly named domain-specific helper."
        )

    for legacy_name, (replacement, module_name) in sorted(replacements.items()):
        found = definitions.get(legacy_name, [])
        if not found:
            continue
        locations = ", ".join(
            _source_location(source_root, found_path, line) for found_path, line in found
        )
        errors.append(
            f"Legacy duplicate helper '{legacy_name}' is forbidden at {locations}. "
            f"Import '{replacement}' from '{module_name}' or use a distinctly named "
            "domain-specific helper."
        )

    return errors


def _module_package(module_name: str) -> str:
    return module_name.rsplit(".", 1)[0]


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = _module_package(module_name).split(".")
    if node.level > len(package_parts):
        return node.module or ""
    base = ".".join(package_parts[: len(package_parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base


def _imports_for(module_name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import(module_name, node)
            if resolved:
                imports.add(resolved)
    return imports


def _function_span(path: Path, function_name: str) -> int | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(matches) != 1:
        return None
    node = matches[0]
    if node.end_lineno is None:
        return None
    return node.end_lineno - node.lineno + 1


def _domain_target(import_name: str) -> str | None:
    for module_name in DOMAIN_MODULES:
        if import_name == module_name or import_name.startswith(f"{module_name}."):
            return module_name
    return None


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            index = stack.index(node)
            return [*stack[index:], node]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for child in sorted(graph[node]):
            cycle = visit(child)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return []


def main() -> int:
    errors: list[str] = _targeted_helper_definition_errors(SRC_ROOT)
    imports_by_module: dict[str, set[str]] = {}

    for module_name, path in DOMAIN_MODULES.items():
        if not path.exists():
            errors.append(f"Missing extracted module: {path.relative_to(REPO_ROOT)}")
            continue
        imports = _imports_for(module_name, path)
        imports_by_module[module_name] = imports
        if module_name in PURE_HELPERS:
            for import_name in sorted(imports):
                if import_name.startswith(FORBIDDEN_PURE_IMPORT_PREFIXES):
                    errors.append(f"{module_name} must stay pure; forbidden import: {import_name}")
        for import_name in sorted(imports):
            forbidden_prefixes = ADAPTER_FORBIDDEN_IMPORT_PREFIXES.get(module_name, ())
            if import_name.startswith(forbidden_prefixes):
                errors.append(
                    f"{module_name} must not import its composition-root monolith: {import_name}"
                )

        register_limit = REGISTER_LINE_LIMITS.get(module_name)
        if register_limit is not None:
            register_span = _function_span(path, "register")
            if register_span is None:
                errors.append(f"{module_name} must define exactly one top-level register()")
            elif register_span > register_limit:
                errors.append(
                    f"{module_name}.register spans {register_span} lines; limit is {register_limit}"
                )

    graph = {
        module_name: {
            target
            for import_name in imports
            for target in [_domain_target(import_name)]
            if target is not None and target != module_name
        }
        for module_name, imports in imports_by_module.items()
    }
    cycle = _find_cycle(graph)
    if cycle:
        errors.append("Import cycle among extracted domain modules: " + " -> ".join(cycle))

    if errors:
        print("Architecture boundary check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Architecture boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
