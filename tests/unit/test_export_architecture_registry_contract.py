"""Export adapter identities must agree across architecture guard registries."""

import pytest

from scripts import check_architecture_boundaries as boundaries


@pytest.mark.parametrize(
    "module_name",
    (
        "kicad_mcp.tools.export_pcb_3d_pdf",
        "kicad_mcp.tools.export_pcb_file_formats",
        "kicad_mcp.tools.export_pcb_vector",
    ),
)
def test_export_adapter_identity_is_consistent_across_guards(module_name: str) -> None:
    expected_path = (
        boundaries.SRC_ROOT / "kicad_mcp" / "tools" / f"{module_name.rsplit('.', 1)[-1]}.py"
    )
    assert boundaries.DOMAIN_MODULES[module_name] == expected_path
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[module_name] == ("kicad_mcp.tools.export",)
    assert boundaries.REGISTER_LINE_LIMITS[module_name] == 100
