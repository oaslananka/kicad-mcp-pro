# Issue #888 Power Reference Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every writer-generated `#PWR` schematic reference contains only decimal digits after the prefix so generated schematics pass the project and `kicad-sch-api` reference validators.

**Architecture:** Keep reference generation in the FastMCP-independent schematic domain. Add one small deterministic helper shared by the basic-authoring and connectivity-authoring services, preserving the current 16-bit UUID-prefix entropy while rendering it in decimal. Existing explicit references and circuit-compilation sequential references remain unchanged.

**Tech Stack:** Python 3.13, pytest, kicad-sch-api 0.5.x, KiCad schematic S-expressions.

**Spec:** GitHub issue `oaslananka/kicad-mcp-pro#888`.

## Global Constraints

- Tests change before production behavior changes.
- Do not bypass the schematic service/adapter boundary.
- Preserve writer uniqueness semantics: use the same first four UUID hex digits, converted to base-10.
- Do not change public MCP tool schemas.

---

### Task 1: Add a valid power-reference generator

**Files:**
- Create: `src/kicad_mcp/schematic/references.py`
- Create: `tests/unit/test_schematic_references.py`

**Interfaces:**
- Consumes: UUID strings returned by the existing injected `new_uuid()` callables.
- Produces: `power_reference_from_uuid(uuid_value: str) -> str` returning `#PWR` plus decimal digits only.

- [ ] **Step 1: Write the failing test**

```python
from kicad_mcp.schematic.references import power_reference_from_uuid


def test_power_reference_converts_hex_prefix_to_decimal_digits() -> None:
    assert power_reference_from_uuid("abcd1234-0000-0000-0000-000000000000") == "#PWR43981"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --all-extras pytest tests/unit/test_schematic_references.py -q`
Expected: FAIL because `kicad_mcp.schematic.references` does not yet exist.

- [ ] **Step 3: Write minimal implementation**

```python
def power_reference_from_uuid(uuid_value: str) -> str:
    return f"#PWR{int(uuid_value[:4], 16)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --all-extras pytest tests/unit/test_schematic_references.py -q`
Expected: PASS.

### Task 2: Route all UUID-based power writers through the helper

**Files:**
- Modify: `src/kicad_mcp/schematic/basic_authoring.py`
- Modify: `src/kicad_mcp/schematic/connectivity_authoring.py`
- Modify: `tests/unit/test_schematic_basic_authoring_service.py`
- Modify: `tests/unit/test_schematic_connectivity_authoring_service.py`

**Interfaces:**
- Consumes: `power_reference_from_uuid()` from Task 1.
- Produces: basic `add_power_symbol()` and connectivity `add_pin_labels()` blocks with validator-safe references.

- [ ] **Step 1: Change the existing basic-authoring regression expectation**

For UUID `abcd1234`, assert the captured reference is `#PWR43981`, not `#PWRabcd`, and assert the suffix after `#PWR` is decimal digits.

- [ ] **Step 2: Add a connectivity regression test**

Inject a UUID beginning with hexadecimal letters, create a power terminal, capture `place_symbol_block(reference=...)`, and assert the emitted reference is `#PWR43981` and contains no `a-f` suffix characters.

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `uv run --all-extras pytest tests/unit/test_schematic_basic_authoring_service.py tests/unit/test_schematic_connectivity_authoring_service.py -q`
Expected: FAIL on the old `#PWRabcd` behavior.

- [ ] **Step 4: Replace both inline `f"#PWR{self.new_uuid()[:4]}"` expressions**

Import and call `power_reference_from_uuid(self.new_uuid())` in both services.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run the same pytest command; expected PASS.

### Task 3: Verify schematic writer compatibility

**Files:**
- Test only; no additional production files expected.

**Interfaces:**
- Consumes: completed writer changes.
- Produces: evidence that the fix is compatible with nearby integration behavior.

- [ ] **Step 1: Run related unit/integration tests**

Run: `uv run --all-extras pytest tests/unit/test_schematic_references.py tests/unit/test_schematic_basic_authoring_service.py tests/unit/test_schematic_connectivity_authoring_service.py tests/integration/test_schematic_tools.py tests/integration/test_schematic_pin_labels_power_symbols.py -q`

- [ ] **Step 2: Run change-scoped repository gate**

Run: `python3 scripts/run_uv.py run --all-extras python scripts/hook_pre_push.py`

- [ ] **Step 3: Review diff**

Confirm only reference-generation behavior and regression tests changed; no tool schema/generated docs changed.
