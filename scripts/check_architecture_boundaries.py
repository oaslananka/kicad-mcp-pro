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
_LIBRARY_FOOTPRINT_ENGINEERING_ADAPTER = "kicad_mcp.tools.library_footprint_engineering"
_LIBRARY_LOCAL_AUTHORING_ADAPTER = "kicad_mcp.tools.library_local_authoring"
_LIBRARY_SOURCING_ADAPTER = "kicad_mcp.tools.library_sourcing"
_LIBRARY_COMPONENT_CONTRACT_ADAPTER = "kicad_mcp.tools.library_component_contract"
_LIBRARY_ROOT_MODULE = "kicad_mcp.tools.library"
_PROJECT_CONTEXT_ADAPTER = "kicad_mcp.tools.project_context"
_PROJECT_CREATION_ADAPTER = "kicad_mcp.tools.project_creation"
_PROJECT_DESIGN_SPEC_ADAPTER = "kicad_mcp.tools.project_design_spec"
_PROJECT_DISCOVERY_ADAPTER = "kicad_mcp.tools.project_discovery"
_PROJECT_EDIT_IMPACT_ADAPTER = "kicad_mcp.tools.project_edit_impact"
_PROJECT_EDIT_REVALIDATION_ADAPTER = "kicad_mcp.tools.project_edit_revalidation"
_PROJECT_HELP_ADAPTER = "kicad_mcp.tools.project_help"
_PROJECT_NEXT_ACTION_ADAPTER = "kicad_mcp.tools.project_next_action"
_PROJECT_REPORTING_ADAPTER = "kicad_mcp.tools.project_reporting"
_PROJECT_RUNTIME_ADAPTER = "kicad_mcp.tools.project_runtime"
_PROJECT_VALIDATION_LOOPS_ADAPTER = "kicad_mcp.tools.project_validation_loops"
_PROJECT_WORKFLOW_ADAPTER = "kicad_mcp.tools.project_workflow"
_PROJECT_ROOT_MODULE = "kicad_mcp.tools.project"
_MANUFACTURING_ROOT_MODULE = "kicad_mcp.tools.manufacturing"
_MANUFACTURING_CPL_ROTATION_ADAPTER = "kicad_mcp.tools.manufacturing_cpl_rotation"
_MANUFACTURING_PANELIZATION_ADAPTER = "kicad_mcp.tools.manufacturing_panelization"
_MANUFACTURING_IMPORT_ADAPTER = "kicad_mcp.tools.manufacturing_imports"
_MANUFACTURING_RELEASE_EVIDENCE_ADAPTER = "kicad_mcp.tools.manufacturing_release_evidence"
_MANUFACTURING_RELEASE_MANIFEST_ADAPTER = "kicad_mcp.tools.manufacturing_release_manifest"
_MANUFACTURING_TEST_PLAN_ADAPTER = "kicad_mcp.tools.manufacturing_test_plan"
_ROUTING_ROOT_MODULE = "kicad_mcp.tools.routing"
_ROUTING_TUNING_PROFILES_ADAPTER = "kicad_mcp.tools.routing_tuning_profiles"
_ROUTING_SPECCTRA_STAGING_ADAPTER = "kicad_mcp.tools.routing_specctra_staging"
_ROUTING_NET_CLASS_RULES_ADAPTER = "kicad_mcp.tools.routing_net_class_rules"
_ROUTING_DIFFERENTIAL_PAIR_ADAPTER = "kicad_mcp.tools.routing_differential_pair"
_ROUTING_LENGTH_TUNING_ADAPTER = "kicad_mcp.tools.routing_length_tuning"
_ROUTING_DIFF_PAIR_LENGTH_ADAPTER = "kicad_mcp.tools.routing_diff_pair_length"
_ROUTING_BOARD_CONSTRAINTS_ADAPTER = "kicad_mcp.tools.routing_board_constraints"
_ROUTING_TIME_DOMAIN_TUNING_ADAPTER = "kicad_mcp.tools.routing_time_domain_tuning"
_ROUTING_MANUAL_TRACKS_ADAPTER = "kicad_mcp.tools.routing_manual_tracks"
_ROUTING_SES_APPLY_ADAPTER = "kicad_mcp.tools.routing_ses_apply"
_ROUTING_AUTOROUTER_ADAPTER = "kicad_mcp.tools.routing_autorouter"
_POWER_INTEGRITY_ROOT_MODULE = "kicad_mcp.tools.power_integrity"
_POWER_INTEGRITY_VOLTAGE_DROP_ADAPTER = "kicad_mcp.tools.power_integrity_voltage_drop"
_POWER_INTEGRITY_DECOUPLING_ADAPTER = "kicad_mcp.tools.power_integrity_decoupling"
_POWER_INTEGRITY_THERMAL_PLANE_ADAPTER = "kicad_mcp.tools.power_integrity_thermal_plane"
_POWER_INTEGRITY_PDN_MESH_ADAPTER = "kicad_mcp.tools.power_integrity_pdn_mesh"
_POWER_INTEGRITY_THERMAL_VIA_ADAPTER = "kicad_mcp.tools.power_integrity_thermal_via"
_POWER_INTEGRITY_COPPER_WEIGHT_ADAPTER = "kicad_mcp.tools.power_integrity_copper_weight"
_POWER_INTEGRITY_THERMAL_POUR_ADAPTER = "kicad_mcp.tools.power_integrity_thermal_pour"
_SIGNAL_INTEGRITY_ROOT_MODULE = "kicad_mcp.tools.signal_integrity"
_SIGNAL_INTEGRITY_IMPEDANCE_ADAPTER = "kicad_mcp.tools.signal_integrity_impedance"
_SIGNAL_INTEGRITY_DIELECTRIC_MATERIALS_ADAPTER = (
    "kicad_mcp.tools.signal_integrity_dielectric_materials"
)
_SIGNAL_INTEGRITY_SOLVER_CAPABILITIES_ADAPTER = (
    "kicad_mcp.tools.signal_integrity_solver_capabilities"
)
_SIGNAL_INTEGRITY_STACKUP_GENERATION_ADAPTER = "kicad_mcp.tools.signal_integrity_stackup_generation"
_SIGNAL_INTEGRITY_HIGH_SPEED_CHANNEL_ADAPTER = "kicad_mcp.tools.signal_integrity_high_speed_channel"
_SIGNAL_INTEGRITY_STACKUP_SYNTHESIS_ADAPTER = "kicad_mcp.tools.signal_integrity_stackup_synthesis"
_SIGNAL_INTEGRITY_NET_CLASS_BINDING_ADAPTER = "kicad_mcp.tools.signal_integrity_net_class_binding"
_SIGNAL_INTEGRITY_LENGTH_MATCHING_ADAPTER = "kicad_mcp.tools.signal_integrity_length_matching"
_SIGNAL_INTEGRITY_DIFFERENTIAL_PAIR_SKEW_ADAPTER = (
    "kicad_mcp.tools.signal_integrity_differential_pair_skew"
)
_SIGNAL_INTEGRITY_DECOUPLING_PLACEMENT_ADAPTER = (
    "kicad_mcp.tools.signal_integrity_decoupling_placement"
)
_SIGNAL_INTEGRITY_VIA_STUB_ADAPTER = "kicad_mcp.tools.signal_integrity_via_stub"

DOMAIN_MODULES = {
    "kicad_mcp.ir.engineering_graph": SRC_ROOT / "kicad_mcp" / "ir" / "engineering_graph.py",
    "kicad_mcp.ir.engineering_graph_from_ir": SRC_ROOT
    / "kicad_mcp"
    / "ir"
    / "engineering_graph_from_ir.py",
    "kicad_mcp.tools.pcb": SRC_ROOT / "kicad_mcp" / "tools" / "pcb.py",
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
    _MANUFACTURING_ROOT_MODULE: SRC_ROOT / "kicad_mcp" / "tools" / "manufacturing.py",
    "kicad_mcp.manufacturing.cpl_rotation": SRC_ROOT
    / "kicad_mcp"
    / "manufacturing"
    / "cpl_rotation.py",
    "kicad_mcp.manufacturing.panelization": SRC_ROOT
    / "kicad_mcp"
    / "manufacturing"
    / "panelization.py",
    "kicad_mcp.manufacturing.imports": SRC_ROOT / "kicad_mcp" / "manufacturing" / "imports.py",
    "kicad_mcp.manufacturing.release_evidence": SRC_ROOT
    / "kicad_mcp"
    / "manufacturing"
    / "release_evidence.py",
    "kicad_mcp.manufacturing.release_manifest": SRC_ROOT
    / "kicad_mcp"
    / "manufacturing"
    / "release_manifest.py",
    "kicad_mcp.manufacturing.test_plan": SRC_ROOT / "kicad_mcp" / "manufacturing" / "test_plan.py",
    "kicad_mcp.library.catalog": SRC_ROOT / "kicad_mcp" / "library" / "catalog.py",
    "kicad_mcp.library.local_authoring": SRC_ROOT / "kicad_mcp" / "library" / "local_authoring.py",
    "kicad_mcp.library.footprint_engineering": SRC_ROOT
    / "kicad_mcp"
    / "library"
    / "footprint_engineering.py",
    "kicad_mcp.library.sourcing": SRC_ROOT / "kicad_mcp" / "library" / "sourcing.py",
    "kicad_mcp.library.component_contract": SRC_ROOT
    / "kicad_mcp"
    / "library"
    / "component_contract.py",
    "kicad_mcp.project.context": SRC_ROOT / "kicad_mcp" / "project" / "context.py",
    "kicad_mcp.project.creation": SRC_ROOT / "kicad_mcp" / "project" / "creation.py",
    "kicad_mcp.project.design_spec": SRC_ROOT / "kicad_mcp" / "project" / "design_spec.py",
    "kicad_mcp.project.discovery": SRC_ROOT / "kicad_mcp" / "project" / "discovery.py",
    "kicad_mcp.project.edit_impact": SRC_ROOT / "kicad_mcp" / "project" / "edit_impact.py",
    "kicad_mcp.project.help": SRC_ROOT / "kicad_mcp" / "project" / "help.py",
    "kicad_mcp.project.next_action": SRC_ROOT / "kicad_mcp" / "project" / "next_action.py",
    "kicad_mcp.project.reporting": SRC_ROOT / "kicad_mcp" / "project" / "reporting.py",
    "kicad_mcp.project.runtime": SRC_ROOT / "kicad_mcp" / "project" / "runtime.py",
    "kicad_mcp.project.validation_loops": SRC_ROOT
    / "kicad_mcp"
    / "project"
    / "validation_loops.py",
    "kicad_mcp.project.workflow": SRC_ROOT / "kicad_mcp" / "project" / "workflow.py",
    "kicad_mcp.tools.export_bom": SRC_ROOT / "kicad_mcp" / "tools" / "export_bom.py",
    "kicad_mcp.tools.export_board_stats": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_board_stats.py",
    "kicad_mcp.tools.export_drill": SRC_ROOT / "kicad_mcp" / "tools" / "export_drill.py",
    "kicad_mcp.tools.export_gerber": SRC_ROOT / "kicad_mcp" / "tools" / "export_gerber.py",
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_manufacturing_package.py",
    "kicad_mcp.tools.export_netlist": SRC_ROOT / "kicad_mcp" / "tools" / "export_netlist.py",
    "kicad_mcp.tools.export_pcb_3d_pdf": SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_3d_pdf.py",
    _EXPORT_PCB_3D_RENDER_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_3d_render.py",
    "kicad_mcp.tools.export_pcb_file_formats": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_pcb_file_formats.py",
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_pcb_manufacturing_outputs.py",
    "kicad_mcp.tools.export_pcb_pdf": SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_pdf.py",
    "kicad_mcp.tools.export_pcb_vector": SRC_ROOT / "kicad_mcp" / "tools" / "export_pcb_vector.py",
    "kicad_mcp.tools.export_sch_pdf": SRC_ROOT / "kicad_mcp" / "tools" / "export_sch_pdf.py",
    "kicad_mcp.tools.export_sch_python_bom": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "export_sch_python_bom.py",
    "kicad_mcp.tools.export_sch_vector": SRC_ROOT / "kicad_mcp" / "tools" / "export_sch_vector.py",
    _LIBRARY_CATALOG_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "library_catalog.py",
    _LIBRARY_DATASHEET_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "library_datasheet.py",
    _LIBRARY_LOCAL_AUTHORING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "library_local_authoring.py",
    _LIBRARY_FOOTPRINT_ENGINEERING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "library_footprint_engineering.py",
    _LIBRARY_SOURCING_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "library_sourcing.py",
    _LIBRARY_COMPONENT_CONTRACT_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "library_component_contract.py",
    _MANUFACTURING_CPL_ROTATION_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "manufacturing_cpl_rotation.py",
    _MANUFACTURING_PANELIZATION_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "manufacturing_panelization.py",
    _MANUFACTURING_IMPORT_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "manufacturing_imports.py",
    _MANUFACTURING_RELEASE_EVIDENCE_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "manufacturing_release_evidence.py",
    _MANUFACTURING_RELEASE_MANIFEST_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "manufacturing_release_manifest.py",
    _MANUFACTURING_TEST_PLAN_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "manufacturing_test_plan.py",
    _ROUTING_ROOT_MODULE: SRC_ROOT / "kicad_mcp" / "tools" / "routing.py",
    "kicad_mcp.routing.tuning_profiles": SRC_ROOT / "kicad_mcp" / "routing" / "tuning_profiles.py",
    "kicad_mcp.routing.specctra_staging": SRC_ROOT
    / "kicad_mcp"
    / "routing"
    / "specctra_staging.py",
    "kicad_mcp.routing.net_class_rules": SRC_ROOT / "kicad_mcp" / "routing" / "net_class_rules.py",
    "kicad_mcp.routing.differential_pair_rules": SRC_ROOT
    / "kicad_mcp"
    / "routing"
    / "differential_pair_rules.py",
    "kicad_mcp.routing.length_tuning": SRC_ROOT / "kicad_mcp" / "routing" / "length_tuning.py",
    "kicad_mcp.routing.board_constraints": SRC_ROOT
    / "kicad_mcp"
    / "routing"
    / "board_constraints.py",
    "kicad_mcp.routing.time_domain_tuning": SRC_ROOT
    / "kicad_mcp"
    / "routing"
    / "time_domain_tuning.py",
    "kicad_mcp.routing.manual_tracks": SRC_ROOT / "kicad_mcp" / "routing" / "manual_tracks.py",
    "kicad_mcp.routing.ses_apply": SRC_ROOT / "kicad_mcp" / "routing" / "ses_apply.py",
    "kicad_mcp.routing.autorouter": SRC_ROOT / "kicad_mcp" / "routing" / "autorouter.py",
    _ROUTING_TUNING_PROFILES_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_tuning_profiles.py",
    _ROUTING_SPECCTRA_STAGING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_specctra_staging.py",
    _ROUTING_NET_CLASS_RULES_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_net_class_rules.py",
    _ROUTING_DIFFERENTIAL_PAIR_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_differential_pair.py",
    _ROUTING_LENGTH_TUNING_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "routing_length_tuning.py",
    _ROUTING_DIFF_PAIR_LENGTH_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_diff_pair_length.py",
    _ROUTING_BOARD_CONSTRAINTS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_board_constraints.py",
    _ROUTING_TIME_DOMAIN_TUNING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "routing_time_domain_tuning.py",
    _ROUTING_MANUAL_TRACKS_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "routing_manual_tracks.py",
    _ROUTING_SES_APPLY_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "routing_ses_apply.py",
    _ROUTING_AUTOROUTER_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "routing_autorouter.py",
    _POWER_INTEGRITY_ROOT_MODULE: SRC_ROOT / "kicad_mcp" / "tools" / "power_integrity.py",
    "kicad_mcp.power_integrity.voltage_drop": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "voltage_drop.py",
    _POWER_INTEGRITY_VOLTAGE_DROP_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_voltage_drop.py",
    "kicad_mcp.power_integrity.decoupling": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "decoupling.py",
    _POWER_INTEGRITY_DECOUPLING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_decoupling.py",
    "kicad_mcp.power_integrity.thermal_plane_spreading": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "thermal_plane_spreading.py",
    _POWER_INTEGRITY_THERMAL_PLANE_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_thermal_plane.py",
    "kicad_mcp.power_integrity.pdn_mesh_check": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "pdn_mesh_check.py",
    _POWER_INTEGRITY_PDN_MESH_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_pdn_mesh.py",
    "kicad_mcp.power_integrity.thermal_via": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "thermal_via.py",
    _POWER_INTEGRITY_THERMAL_VIA_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_thermal_via.py",
    "kicad_mcp.power_integrity.copper_weight": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "copper_weight.py",
    _POWER_INTEGRITY_COPPER_WEIGHT_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_copper_weight.py",
    "kicad_mcp.power_integrity.thermal_pour": SRC_ROOT
    / "kicad_mcp"
    / "power_integrity"
    / "thermal_pour.py",
    _POWER_INTEGRITY_THERMAL_POUR_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "power_integrity_thermal_pour.py",
    _SIGNAL_INTEGRITY_ROOT_MODULE: SRC_ROOT / "kicad_mcp" / "tools" / "signal_integrity.py",
    "kicad_mcp.signal_integrity.impedance": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "impedance.py",
    "kicad_mcp.signal_integrity.dielectric_materials": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "dielectric_materials.py",
    "kicad_mcp.signal_integrity.solver_capabilities": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "solver_capabilities.py",
    "kicad_mcp.signal_integrity.stackup_generation": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "stackup_generation.py",
    "kicad_mcp.signal_integrity.high_speed_channel": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "high_speed_channel.py",
    "kicad_mcp.signal_integrity.stackup_synthesis": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "stackup_synthesis.py",
    "kicad_mcp.signal_integrity.net_class_binding": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "net_class_binding.py",
    "kicad_mcp.signal_integrity.length_matching": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "length_matching.py",
    "kicad_mcp.signal_integrity.differential_pair_skew": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "differential_pair_skew.py",
    "kicad_mcp.signal_integrity.decoupling_placement": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "decoupling_placement.py",
    "kicad_mcp.signal_integrity.via_stub": SRC_ROOT
    / "kicad_mcp"
    / "signal_integrity"
    / "via_stub.py",
    _SIGNAL_INTEGRITY_IMPEDANCE_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_impedance.py",
    _SIGNAL_INTEGRITY_DIELECTRIC_MATERIALS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_dielectric_materials.py",
    _SIGNAL_INTEGRITY_SOLVER_CAPABILITIES_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_solver_capabilities.py",
    _SIGNAL_INTEGRITY_STACKUP_GENERATION_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_stackup_generation.py",
    _SIGNAL_INTEGRITY_HIGH_SPEED_CHANNEL_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_high_speed_channel.py",
    _SIGNAL_INTEGRITY_STACKUP_SYNTHESIS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_stackup_synthesis.py",
    _SIGNAL_INTEGRITY_NET_CLASS_BINDING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_net_class_binding.py",
    _SIGNAL_INTEGRITY_LENGTH_MATCHING_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_length_matching.py",
    _SIGNAL_INTEGRITY_DIFFERENTIAL_PAIR_SKEW_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_differential_pair_skew.py",
    _SIGNAL_INTEGRITY_DECOUPLING_PLACEMENT_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_decoupling_placement.py",
    _SIGNAL_INTEGRITY_VIA_STUB_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "signal_integrity_via_stub.py",
    _PROJECT_CONTEXT_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_context.py",
    _PROJECT_CREATION_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_creation.py",
    _PROJECT_DESIGN_SPEC_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_design_spec.py",
    _PROJECT_DISCOVERY_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_discovery.py",
    _PROJECT_EDIT_IMPACT_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_edit_impact.py",
    _PROJECT_EDIT_REVALIDATION_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "project_edit_revalidation.py",
    _PROJECT_HELP_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_help.py",
    _PROJECT_NEXT_ACTION_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_next_action.py",
    _PROJECT_REPORTING_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_reporting.py",
    _PROJECT_RUNTIME_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_runtime.py",
    _PROJECT_VALIDATION_LOOPS_ADAPTER: SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "project_validation_loops.py",
    _PROJECT_WORKFLOW_ADAPTER: SRC_ROOT / "kicad_mcp" / "tools" / "project_workflow.py",
    "kicad_mcp.tools.validation": SRC_ROOT / "kicad_mcp" / "tools" / "validation.py",
    "kicad_mcp.validation.drc_runner": SRC_ROOT / "kicad_mcp" / "validation" / "drc_runner.py",
    "kicad_mcp.validation.policy_state": SRC_ROOT / "kicad_mcp" / "validation" / "policy_state.py",
    "kicad_mcp.tools.validation_policy_state": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "validation_policy_state.py",
    "kicad_mcp.tools.schematic": SRC_ROOT / "kicad_mcp" / "tools" / "schematic.py",
    "kicad_mcp.companion.context": SRC_ROOT / "kicad_mcp" / "companion" / "context.py",
    "kicad_mcp.ipc.command_queue": SRC_ROOT / "kicad_mcp" / "ipc" / "command_queue.py",
    "kicad_mcp.models.contract_verifier": SRC_ROOT
    / "kicad_mcp"
    / "models"
    / "contract_verifier.py",
    "kicad_mcp.models.sch_transaction": SRC_ROOT / "kicad_mcp" / "models" / "sch_transaction.py",
    "kicad_mcp.models.visual_qa": SRC_ROOT / "kicad_mcp" / "models" / "visual_qa.py",
    "kicad_mcp.pcb.basic_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "basic_inspection.py",
    "kicad_mcp.pcb.board_access": SRC_ROOT / "kicad_mcp" / "pcb" / "board_access.py",
    "kicad_mcp.pcb.geometry": SRC_ROOT / "kicad_mcp" / "pcb" / "geometry.py",
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
    "kicad_mcp.tools.pcb_groups_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_groups_inspection.py",
    "kicad_mcp.pcb.board_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "board_inspection.py",
    "kicad_mcp.tools.pcb_board_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_board_inspection.py",
    "kicad_mcp.tools.pcb_basic_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_basic_inspection.py",
    "kicad_mcp.tools.pcb_file_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_file_inspection.py",
    "kicad_mcp.tools.pcb_origin_management": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_origin_management.py",
    "kicad_mcp.tools.pcb_session_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_session_inspection.py",
    "kicad_mcp.pcb.stackup_management": SRC_ROOT / "kicad_mcp" / "pcb" / "stackup_management.py",
    "kicad_mcp.tools.pcb_stackup_management": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_stackup_management.py",
    "kicad_mcp.tools.pcb_title_block_management": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_title_block_management.py",
    "kicad_mcp.tools.pcb_transaction_lifecycle": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_transaction_lifecycle.py",
    "kicad_mcp.tools.schematic_back_annotation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_back_annotation.py",
    "kicad_mcp.tools.schematic_basic_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_basic_authoring.py",
    "kicad_mcp.tools.schematic_circuit_compilation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_circuit_compilation.py",
    "kicad_mcp.tools.schematic_connectivity_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_connectivity_authoring.py",
    "kicad_mcp.tools.schematic_destructive_edit": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_destructive_edit.py",
    "kicad_mcp.tools.schematic_document_settings": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_document_settings.py",
    "kicad_mcp.tools.schematic_symbol_mutation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_symbol_mutation.py",
    "kicad_mcp.tools.schematic_template_catalog": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_catalog.py",
    "kicad_mcp.tools.schematic_template_instantiation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_instantiation.py",
    "kicad_mcp.tools.schematic_topology": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_topology.py",
    "kicad_mcp.tools.schematic_hierarchy_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_hierarchy_authoring.py",
    "kicad_mcp.tools.schematic_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_inspection.py",
    "kicad_mcp.tools.schematic_lifecycle_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_lifecycle_authoring.py",
    "kicad_mcp.tools.schematic_layout_automation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_automation.py",
    "kicad_mcp.tools.schematic_layout_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_inspection.py",
    "kicad_mcp.tools.schematic_rendering": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_rendering.py",
    "kicad_mcp.tools.schematic_semantic_ir": SRC_ROOT
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
    "kicad_mcp.power_integrity.voltage_drop",
    "kicad_mcp.power_integrity.decoupling",
    "kicad_mcp.power_integrity.thermal_plane_spreading",
    "kicad_mcp.power_integrity.pdn_mesh_check",
    "kicad_mcp.power_integrity.thermal_via",
    "kicad_mcp.power_integrity.copper_weight",
    "kicad_mcp.power_integrity.thermal_pour",
    "kicad_mcp.signal_integrity.impedance",
    "kicad_mcp.signal_integrity.dielectric_materials",
    "kicad_mcp.signal_integrity.solver_capabilities",
    "kicad_mcp.signal_integrity.stackup_generation",
    "kicad_mcp.signal_integrity.high_speed_channel",
    "kicad_mcp.signal_integrity.stackup_synthesis",
    "kicad_mcp.signal_integrity.net_class_binding",
    "kicad_mcp.signal_integrity.length_matching",
    "kicad_mcp.signal_integrity.differential_pair_skew",
    "kicad_mcp.signal_integrity.decoupling_placement",
    "kicad_mcp.signal_integrity.via_stub",
    "kicad_mcp.routing.tuning_profiles",
    "kicad_mcp.routing.specctra_staging",
    "kicad_mcp.routing.net_class_rules",
    "kicad_mcp.routing.differential_pair_rules",
    "kicad_mcp.routing.length_tuning",
    "kicad_mcp.routing.board_constraints",
    "kicad_mcp.routing.time_domain_tuning",
    "kicad_mcp.routing.manual_tracks",
    "kicad_mcp.routing.ses_apply",
    "kicad_mcp.routing.autorouter",
    "kicad_mcp.manufacturing.cpl_rotation",
    "kicad_mcp.manufacturing.panelization",
    "kicad_mcp.manufacturing.imports",
    "kicad_mcp.manufacturing.release_evidence",
    "kicad_mcp.manufacturing.release_manifest",
    "kicad_mcp.manufacturing.test_plan",
    "kicad_mcp.ir.engineering_graph",
    "kicad_mcp.ir.engineering_graph_from_ir",
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
    "kicad_mcp.library.footprint_engineering",
    "kicad_mcp.library.sourcing",
    "kicad_mcp.library.component_contract",
    "kicad_mcp.project.context",
    "kicad_mcp.project.creation",
    "kicad_mcp.project.design_spec",
    "kicad_mcp.project.discovery",
    "kicad_mcp.project.edit_impact",
    "kicad_mcp.project.help",
    "kicad_mcp.project.next_action",
    "kicad_mcp.project.reporting",
    "kicad_mcp.project.runtime",
    "kicad_mcp.project.validation_loops",
    "kicad_mcp.project.workflow",
    "kicad_mcp.validation.policy_state",
    "kicad_mcp.companion.context",
    "kicad_mcp.ipc.command_queue",
    "kicad_mcp.models.contract_verifier",
    "kicad_mcp.models.sch_transaction",
    "kicad_mcp.models.visual_qa",
    "kicad_mcp.pcb.basic_inspection",
    "kicad_mcp.pcb.board_access",
    "kicad_mcp.pcb.board_inspection",
    "kicad_mcp.pcb.geometry",
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
    "kicad_mcp.tools.pcb",
    "kicad_mcp.tools.schematic",
    "mcp",
    "pcbnew",
    "wx",
    "kipy",
)

ADAPTER_FORBIDDEN_IMPORT_PREFIXES = {
    _POWER_INTEGRITY_VOLTAGE_DROP_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_DECOUPLING_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_THERMAL_PLANE_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_PDN_MESH_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_THERMAL_VIA_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_COPPER_WEIGHT_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _POWER_INTEGRITY_THERMAL_POUR_ADAPTER: (_POWER_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_IMPEDANCE_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_DIELECTRIC_MATERIALS_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_SOLVER_CAPABILITIES_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_STACKUP_GENERATION_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_HIGH_SPEED_CHANNEL_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_STACKUP_SYNTHESIS_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_NET_CLASS_BINDING_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_LENGTH_MATCHING_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_DIFFERENTIAL_PAIR_SKEW_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_DECOUPLING_PLACEMENT_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _SIGNAL_INTEGRITY_VIA_STUB_ADAPTER: (_SIGNAL_INTEGRITY_ROOT_MODULE,),
    _ROUTING_TUNING_PROFILES_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_SPECCTRA_STAGING_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_NET_CLASS_RULES_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_DIFFERENTIAL_PAIR_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_LENGTH_TUNING_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_DIFF_PAIR_LENGTH_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_BOARD_CONSTRAINTS_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_TIME_DOMAIN_TUNING_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_MANUAL_TRACKS_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_SES_APPLY_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _ROUTING_AUTOROUTER_ADAPTER: (_ROUTING_ROOT_MODULE,),
    _MANUFACTURING_RELEASE_EVIDENCE_ADAPTER: (_MANUFACTURING_ROOT_MODULE,),
    _MANUFACTURING_RELEASE_MANIFEST_ADAPTER: (_MANUFACTURING_ROOT_MODULE,),
    _MANUFACTURING_TEST_PLAN_ADAPTER: (_MANUFACTURING_ROOT_MODULE,),
    _MANUFACTURING_IMPORT_ADAPTER: (_MANUFACTURING_ROOT_MODULE,),
    _MANUFACTURING_PANELIZATION_ADAPTER: (_MANUFACTURING_ROOT_MODULE,),
    "kicad_mcp.tools.validation_policy_state": ("kicad_mcp.tools.validation",),
    "kicad_mcp.tools.export_bom": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_board_stats": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_drill": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_gerber": ("kicad_mcp.tools.export",),
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_netlist": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_pcb_3d_pdf": ("kicad_mcp.tools.export",),
    _EXPORT_PCB_3D_RENDER_ADAPTER: ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_pcb_file_formats": ("kicad_mcp.tools.export",),
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_pcb_pdf": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_pcb_vector": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_sch_pdf": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_sch_python_bom": ("kicad_mcp.tools.export",),
    "kicad_mcp.tools.export_sch_vector": ("kicad_mcp.tools.export",),
    _LIBRARY_CATALOG_ADAPTER: (_LIBRARY_ROOT_MODULE,),
    _LIBRARY_DATASHEET_ADAPTER: (_LIBRARY_ROOT_MODULE,),
    _LIBRARY_FOOTPRINT_ENGINEERING_ADAPTER: (_LIBRARY_ROOT_MODULE,),
    _LIBRARY_SOURCING_ADAPTER: (_LIBRARY_ROOT_MODULE,),
    _PROJECT_CONTEXT_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_CREATION_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_DESIGN_SPEC_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_DISCOVERY_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_EDIT_IMPACT_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_EDIT_REVALIDATION_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_HELP_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_NEXT_ACTION_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_REPORTING_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_RUNTIME_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_VALIDATION_LOOPS_ADAPTER: (_PROJECT_ROOT_MODULE,),
    _PROJECT_WORKFLOW_ADAPTER: (_PROJECT_ROOT_MODULE,),
    "kicad_mcp.tools.pcb_basic_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_board_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_file_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_groups_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_origin_management": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_session_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_stackup_management": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_title_block_management": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_transaction_lifecycle": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.schematic_back_annotation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_basic_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_circuit_compilation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_connectivity_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_destructive_edit": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_document_settings": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_hierarchy_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_inspection": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_lifecycle_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_layout_automation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_layout_inspection": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_rendering": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_semantic_ir": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_symbol_mutation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_template_catalog": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_template_instantiation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_topology": ("kicad_mcp.tools.schematic",),
}

REGISTER_LINE_LIMITS = {
    "kicad_mcp.tools.pcb": 300,
    "kicad_mcp.tools.export_bom": 100,
    "kicad_mcp.tools.export_board_stats": 100,
    "kicad_mcp.tools.export_drill": 100,
    "kicad_mcp.tools.export_gerber": 100,
    _EXPORT_MANUFACTURING_PACKAGE_ADAPTER: 100,
    "kicad_mcp.tools.export_netlist": 100,
    "kicad_mcp.tools.export_pcb_3d_pdf": 100,
    _EXPORT_PCB_3D_RENDER_ADAPTER: 140,
    "kicad_mcp.tools.export_pcb_file_formats": 100,
    _EXPORT_PCB_MANUFACTURING_OUTPUTS_ADAPTER: 100,
    "kicad_mcp.tools.export_pcb_pdf": 100,
    "kicad_mcp.tools.export_pcb_vector": 100,
    "kicad_mcp.tools.export_sch_pdf": 100,
    "kicad_mcp.tools.export_sch_python_bom": 100,
    "kicad_mcp.tools.export_sch_vector": 100,
    _LIBRARY_CATALOG_ADAPTER: 160,
    _LIBRARY_DATASHEET_ADAPTER: 100,
    _LIBRARY_LOCAL_AUTHORING_ADAPTER: 100,
    _LIBRARY_FOOTPRINT_ENGINEERING_ADAPTER: 150,
    _LIBRARY_SOURCING_ADAPTER: 180,
    _LIBRARY_COMPONENT_CONTRACT_ADAPTER: 100,
    _MANUFACTURING_CPL_ROTATION_ADAPTER: 80,
    _MANUFACTURING_PANELIZATION_ADAPTER: 95,
    _MANUFACTURING_ROOT_MODULE: 270,
    _MANUFACTURING_IMPORT_ADAPTER: 150,
    _MANUFACTURING_RELEASE_EVIDENCE_ADAPTER: 90,
    _MANUFACTURING_RELEASE_MANIFEST_ADAPTER: 75,
    _MANUFACTURING_TEST_PLAN_ADAPTER: 80,
    _ROUTING_ROOT_MODULE: 100,
    _ROUTING_TUNING_PROFILES_ADAPTER: 95,
    _ROUTING_SPECCTRA_STAGING_ADAPTER: 80,
    _ROUTING_NET_CLASS_RULES_ADAPTER: 75,
    _ROUTING_DIFFERENTIAL_PAIR_ADAPTER: 80,
    _ROUTING_LENGTH_TUNING_ADAPTER: 75,
    _ROUTING_DIFF_PAIR_LENGTH_ADAPTER: 75,
    _ROUTING_BOARD_CONSTRAINTS_ADAPTER: 65,
    _ROUTING_TIME_DOMAIN_TUNING_ADAPTER: 65,
    _ROUTING_MANUAL_TRACKS_ADAPTER: 120,
    _ROUTING_SES_APPLY_ADAPTER: 75,
    _ROUTING_AUTOROUTER_ADAPTER: 105,
    _POWER_INTEGRITY_ROOT_MODULE: 80,
    _POWER_INTEGRITY_VOLTAGE_DROP_ADAPTER: 50,
    _POWER_INTEGRITY_DECOUPLING_ADAPTER: 45,
    _POWER_INTEGRITY_THERMAL_PLANE_ADAPTER: 50,
    _POWER_INTEGRITY_PDN_MESH_ADAPTER: 55,
    _POWER_INTEGRITY_THERMAL_VIA_ADAPTER: 50,
    _POWER_INTEGRITY_COPPER_WEIGHT_ADAPTER: 45,
    _POWER_INTEGRITY_THERMAL_POUR_ADAPTER: 45,
    _SIGNAL_INTEGRITY_ROOT_MODULE: 60,
    _SIGNAL_INTEGRITY_IMPEDANCE_ADAPTER: 90,
    _SIGNAL_INTEGRITY_DIELECTRIC_MATERIALS_ADAPTER: 60,
    _SIGNAL_INTEGRITY_SOLVER_CAPABILITIES_ADAPTER: 55,
    _SIGNAL_INTEGRITY_STACKUP_GENERATION_ADAPTER: 75,
    _SIGNAL_INTEGRITY_HIGH_SPEED_CHANNEL_ADAPTER: 75,
    _SIGNAL_INTEGRITY_STACKUP_SYNTHESIS_ADAPTER: 75,
    _SIGNAL_INTEGRITY_NET_CLASS_BINDING_ADAPTER: 65,
    _SIGNAL_INTEGRITY_LENGTH_MATCHING_ADAPTER: 45,
    _SIGNAL_INTEGRITY_DIFFERENTIAL_PAIR_SKEW_ADAPTER: 45,
    _SIGNAL_INTEGRITY_DECOUPLING_PLACEMENT_ADAPTER: 40,
    _SIGNAL_INTEGRITY_VIA_STUB_ADAPTER: 45,
    _PROJECT_CONTEXT_ADAPTER: 55,
    _PROJECT_CREATION_ADAPTER: 55,
    _PROJECT_DESIGN_SPEC_ADAPTER: 120,
    _PROJECT_DISCOVERY_ADAPTER: 55,
    _PROJECT_EDIT_IMPACT_ADAPTER: 55,
    _PROJECT_EDIT_REVALIDATION_ADAPTER: 55,
    _PROJECT_HELP_ADAPTER: 55,
    _PROJECT_NEXT_ACTION_ADAPTER: 55,
    _PROJECT_REPORTING_ADAPTER: 55,
    _PROJECT_RUNTIME_ADAPTER: 55,
    _PROJECT_VALIDATION_LOOPS_ADAPTER: 55,
    _PROJECT_WORKFLOW_ADAPTER: 55,
    "kicad_mcp.tools.validation": 300,
    "kicad_mcp.tools.validation_policy_state": 300,
    "kicad_mcp.tools.pcb_basic_inspection": 300,
    "kicad_mcp.tools.pcb_board_inspection": 300,
    "kicad_mcp.tools.pcb_file_inspection": 300,
    "kicad_mcp.tools.pcb_groups_inspection": 300,
    "kicad_mcp.tools.pcb_origin_management": 300,
    "kicad_mcp.tools.pcb_session_inspection": 300,
    "kicad_mcp.tools.pcb_stackup_management": 300,
    "kicad_mcp.tools.pcb_title_block_management": 300,
    "kicad_mcp.tools.pcb_transaction_lifecycle": 300,
    "kicad_mcp.tools.schematic": 300,
    "kicad_mcp.tools.schematic_back_annotation": 300,
    "kicad_mcp.tools.schematic_basic_authoring": 300,
    "kicad_mcp.tools.schematic_circuit_compilation": 300,
    "kicad_mcp.tools.schematic_connectivity_authoring": 300,
    "kicad_mcp.tools.schematic_destructive_edit": 300,
    "kicad_mcp.tools.schematic_document_settings": 300,
    "kicad_mcp.tools.schematic_hierarchy_authoring": 320,
    "kicad_mcp.tools.schematic_inspection": 300,
    "kicad_mcp.tools.schematic_lifecycle_authoring": 300,
    "kicad_mcp.tools.schematic_layout_automation": 300,
    "kicad_mcp.tools.schematic_layout_inspection": 300,
    "kicad_mcp.tools.schematic_rendering": 300,
    "kicad_mcp.tools.schematic_semantic_ir": 300,
    "kicad_mcp.tools.schematic_symbol_mutation": 300,
    "kicad_mcp.tools.schematic_template_catalog": 300,
    "kicad_mcp.tools.schematic_template_instantiation": 300,
    "kicad_mcp.tools.schematic_topology": 300,
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
    "_board_tracks": ("board_tracks", "kicad_mcp.pcb.board_access"),
    "_board_vias": ("board_vias", "kicad_mcp.pcb.board_access"),
    "_board_footprints": ("board_footprints", "kicad_mcp.pcb.board_access"),
    "_board_pads": ("board_pads", "kicad_mcp.pcb.board_access"),
    "_board_zones": ("board_zones", "kicad_mcp.pcb.board_access"),
    "_board_shapes": ("board_shapes", "kicad_mcp.pcb.board_access"),
    "_board_nets": ("board_nets", "kicad_mcp.pcb.board_access"),
    "_track_length_mm": ("track_segment_length_mm", "kicad_mcp.pcb.geometry"),
    "_footprint_position_mm": ("point_xy_mm", "kicad_mcp.pcb.geometry"),
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


def _is_type_checking_guard(node: ast.If) -> bool:
    """Return True for ``if TYPE_CHECKING:`` / ``if typing.TYPE_CHECKING:``."""
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


class _RuntimeImportCollector(ast.NodeVisitor):
    """Collect imports reachable at runtime, skipping ``TYPE_CHECKING`` blocks.

    A module guarded by ``from __future__ import annotations`` never
    evaluates annotation-only imports at runtime, so a type-only import of an
    otherwise-forbidden module (KiCad IPC bindings, FastMCP, etc.) does not
    violate a pure module's "importable without that runtime" contract.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.imports: set[str] = set()

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node):
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        resolved = _resolve_import(self.module_name, node)
        if resolved:
            self.imports.add(resolved)


def _imports_for(module_name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _RuntimeImportCollector(module_name)
    collector.visit(tree)
    return collector.imports


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
