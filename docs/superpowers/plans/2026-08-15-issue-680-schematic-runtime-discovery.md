# Issue #680 Schematic Runtime Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep file-backed schematic tools discoverable without a live schematic window while preserving IPC-only gating for `sch_reload`.

**Architecture:** Make capability classification match the actual schematic backend: the `schematic` router category is file-backed by default and only explicitly live-editor operations receive `RuntimeRequirement.KICAD_IPC`. Keep `sch_reload` as the sole verified live-editor exception and mirror that fact in registration metadata with `@requires_kicad_running`. Prove the contract both at capability-registry level and at the actual `tools/list` runtime filter.

**Tech Stack:** Python 3.13, FastMCP/mcp types, pytest, Ruff, mypy/pyright, repo generators, exact repo uv `0.11.31` via `uvx --from uv==0.11.31 uv ...`.

## Global Constraints

- Work only in `C:\Users\Admin\Desktop\REPOLAR\kicad-mcp-pro-issue680` on `fix/issue-680-schematic-runtime-discovery`.
- Do not modify or clean the original checkout at `C:\Users\Admin\Desktop\REPOLAR\kicad-mcp-pro`.
- `schematic` tools default to `RuntimeRequirement.NONE`; only a verified live-editor exception may use `RuntimeRequirement.KICAD_IPC`.
- `sch_reload` remains the verified IPC-only schematic exception.
- Do not change PCB runtime classification or schematic write/reload semantics.
- Do not introduce a 40+ tool allowlist.
- Use TDD: add the failing regression before each behavior change.
- Do not merge the resulting PR automatically; open it with `Fixes #680`.

---

### Task 1: Correct schematic capability runtime classification

**Files:**
- Modify: `tests/unit/test_capabilities.py`
- Modify: `src/kicad_mcp/capabilities.py`

**Interfaces:**
- Consumes: `all_records()`, `get(name)`, `RuntimeRequirement`, router category `schematic`.
- Produces: `_runtime_for_tool(name, category, tier)` classifies ordinary schematic tools as `NONE` and `sch_reload` as `KICAD_IPC`.

- [ ] **Step 1: Write the failing capability regression**

Add these tests to `tests/unit/test_capabilities.py`:

```python
def test_file_backed_schematic_category_tools_do_not_require_live_ipc() -> None:
    records = all_records()
    file_backed = {
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
    }

    assert file_backed.issubset(records)
    for tool_name in file_backed:
        record = records[tool_name]
        assert record.runtime is RuntimeRequirement.NONE, tool_name
        assert record.writes_files is True, tool_name
        assert record.writes_kicad_gui_state is False, tool_name


def test_sch_reload_remains_live_ipc_only() -> None:
    record = get("sch_reload")

    assert record is not None
    assert record.runtime is RuntimeRequirement.KICAD_IPC
    assert record.writes_kicad_gui_state is True
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_capabilities.py::test_file_backed_schematic_category_tools_do_not_require_live_ipc tests/unit/test_capabilities.py::test_sch_reload_remains_live_ipc_only -q
```

Expected: the file-backed representatives currently classified by the blanket schematic-write rule fail because their runtime is `kicad_ipc`.

- [ ] **Step 3: Implement the minimal classification rule**

In `src/kicad_mcp/capabilities.py::_runtime_for_tool`, handle the schematic category before the generic PCB IPC rule:

```python
if category == "schematic":
    return (
        RuntimeRequirement.KICAD_IPC
        if name == "sch_reload"
        else RuntimeRequirement.NONE
    )
```

Then narrow the existing generic rule from:

```python
if category in {"pcb_read", "pcb_write", "schematic"} and tier is not AccessTier.READ:
```

to:

```python
if category in {"pcb_read", "pcb_write"} and tier is not AccessTier.READ:
```

Keep simulation, external dependency, CLI, export, and validation rules unchanged.

- [ ] **Step 4: Run capability tests and verify GREEN**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_capabilities.py -q
```

Expected: all capability tests pass.

- [ ] **Step 5: Commit the capability change**

```powershell
git add src/kicad_mcp/capabilities.py tests/unit/test_capabilities.py
git commit -m "fix(schematic): classify file-backed tools without IPC"
```

---

### Task 2: Align `sch_reload` discovery metadata with capability metadata

**Files:**
- Modify: `tests/unit/test_schematic_lifecycle_authoring_registration.py`
- Modify: `src/kicad_mcp/tools/schematic_lifecycle_authoring.py`

**Interfaces:**
- Consumes: `requires_kicad_running` decorator and `get_tool_metadata()`.
- Produces: `get_tool_metadata("sch_reload").requires_kicad_running is True` while `sch_add_jumper` stays headless-compatible.

- [ ] **Step 1: Make the metadata expectation fail**

Change the end of `test_registration_preserves_metadata()` to:

```python
    assert metadata["sch_annotate"] is None

    reload_metadata = metadata["sch_reload"]
    assert reload_metadata is not None
    assert reload_metadata.headless_compatible is False
    assert reload_metadata.requires_kicad_running is True
```

- [ ] **Step 2: Run the metadata test and verify RED**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_schematic_lifecycle_authoring_registration.py::test_registration_preserves_metadata -q
```

Expected: FAIL because `sch_reload` currently has no discovery metadata.

- [ ] **Step 3: Mark only `sch_reload` as requiring KiCad**

Update the metadata import in `src/kicad_mcp/tools/schematic_lifecycle_authoring.py`:

```python
from .metadata import headless_compatible, requires_kicad_running
```

Decorate `sch_reload` in the same bottom-up metadata pattern used elsewhere:

```python
    @mcp.tool()
    @requires_kicad_running
    def sch_reload() -> str:
        """Ask KiCad to reload the active schematic."""
        return service.reload()
```

Do not change `sch_annotate` or `sch_add_jumper` behavior.

- [ ] **Step 4: Run the lifecycle registration suite and verify GREEN**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_schematic_lifecycle_authoring_registration.py -q
```

Expected: all lifecycle registration tests pass.

- [ ] **Step 5: Commit the metadata alignment**

```powershell
git add src/kicad_mcp/tools/schematic_lifecycle_authoring.py tests/unit/test_schematic_lifecycle_authoring_registration.py
git commit -m "fix(schematic): mark reload as live-runtime only"
```

---

### Task 3: Prove actual runtime filtering keeps file-backed tools in `tools/list`

**Files:**
- Create: `tests/unit/test_schematic_runtime_discovery.py`
- No production file expected unless the filter itself exposes a separate defect.

**Interfaces:**
- Consumes: `mcp.types.Tool`, private server helper `_filter_ipc_runtime_tools()` and capability records from Tasks 1-2.
- Produces: a regression guard matching issue #680's closed-schematic `tools/list` symptom.

- [ ] **Step 1: Add a closed-schematic runtime-filter regression**

Create `tests/unit/test_schematic_runtime_discovery.py`:

```python
# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.types import Tool

from kicad_mcp.server import _filter_ipc_runtime_tools


class _ClosedSchematicState:
    reachable = True
    live_pcb_read = True
    live_pcb_write = True
    live_schematic_read = False
    live_schematic_write = False
    operations: dict[str, object] = {}

    def tool_available(self, _tool_name: str) -> bool:
        return False


def test_file_backed_schematic_tools_remain_visible_when_editor_is_closed() -> None:
    names = [
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
        "sch_reload",
    ]
    tools = [Tool(name=name, inputSchema={}) for name in names]

    visible = {
        tool.name
        for tool in _filter_ipc_runtime_tools(tools, _ClosedSchematicState())  # type: ignore[arg-type]
    }

    assert {
        "sch_create_sheet",
        "sch_add_pin_labels",
        "sch_live_preview",
        "sch_delete_no_connect",
        "variant_create",
    }.issubset(visible)
    assert "sch_reload" not in visible
```

- [ ] **Step 2: Run the runtime-discovery test**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_schematic_runtime_discovery.py -q
```

Expected after Tasks 1-2: PASS. If it fails, inspect `_tool_requires_ipc()` / `_ipc_runtime_allows_tool()` and make only the minimal consistency fix needed; do not bypass runtime filtering globally.

- [ ] **Step 3: Run the combined issue #680 targeted regression set**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_capabilities.py tests/unit/test_schematic_lifecycle_authoring_registration.py tests/unit/test_schematic_runtime_discovery.py tests/unit/test_kicad11_ipc_readiness.py tests/unit/test_ipc_capabilities.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit the end-to-end regression guard**

```powershell
git add tests/unit/test_schematic_runtime_discovery.py
git commit -m "test(schematic): preserve file-backed runtime discovery"
```

---

### Task 4: Validate generated contracts, static checks, and prepare PR

**Files:**
- Modify generated artifacts only if a generator proves they are stale.
- Verify: `integrations/common/kicad-adapter-matrix.json`, `docs/compatibility/kicad-adapter-matrix.generated.md`, `integrations/common/toolsets.json`, `docs/tools-reference.generated.md`, `docs/tools-reference.md`, `docs/evidence/progressive-disclosure-profile-snapshot.json`.

**Interfaces:**
- Consumes: repository generator/check scripts and GitHub CLI.
- Produces: clean branch pushed to `origin` with a PR that closes issue #680.

- [ ] **Step 1: Run generated-artifact checks**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen python scripts/build_adapter_matrix.py --check
uvx --from uv==0.11.31 uv run --all-extras --frozen python scripts/build_toolsets.py --check
uvx --from uv==0.11.31 uv run --all-extras --frozen python scripts/generate_tools_reference.py --check
uvx --from uv==0.11.31 uv run --all-extras --frozen python scripts/profile_surface_report.py --check
uvx --from uv==0.11.31 uv run --all-extras --frozen python scripts/check_tool_contracts.py
```

If any deterministic artifact is stale, regenerate only with its corresponding script without `--check`, inspect the diff, and commit the generated output separately as `chore(schematic): refresh runtime capability evidence`.

- [ ] **Step 2: Run static checks on touched Python files**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen ruff check src/kicad_mcp/capabilities.py src/kicad_mcp/tools/schematic_lifecycle_authoring.py tests/unit/test_capabilities.py tests/unit/test_schematic_lifecycle_authoring_registration.py tests/unit/test_schematic_runtime_discovery.py
uvx --from uv==0.11.31 uv run --all-extras --frozen ruff format --check src/kicad_mcp/capabilities.py src/kicad_mcp/tools/schematic_lifecycle_authoring.py tests/unit/test_capabilities.py tests/unit/test_schematic_lifecycle_authoring_registration.py tests/unit/test_schematic_runtime_discovery.py
uvx --from uv==0.11.31 uv run --all-extras --frozen mypy src/kicad_mcp/capabilities.py src/kicad_mcp/tools/schematic_lifecycle_authoring.py
uvx --from uv==0.11.31 uv run --all-extras --frozen pyright src/kicad_mcp/capabilities.py src/kicad_mcp/tools/schematic_lifecycle_authoring.py tests/unit/test_schematic_runtime_discovery.py
```

- [ ] **Step 3: Run final focused regression and diff hygiene**

```powershell
uvx --from uv==0.11.31 uv run --all-extras --frozen pytest tests/unit/test_capabilities.py tests/unit/test_schematic_lifecycle_authoring_registration.py tests/unit/test_schematic_runtime_discovery.py tests/unit/test_kicad11_ipc_readiness.py tests/unit/test_ipc_capabilities.py -q
git diff --check origin/main...HEAD
git status --short
git log --oneline origin/main..HEAD
```

Expected: test set green, diff check clean, worktree clean, and commits limited to the design/plan plus issue #680 fix/tests/generated evidence if required.

- [ ] **Step 4: Re-fetch and ensure the branch still contains current `origin/main`**

```powershell
git fetch origin --prune
git merge-base --is-ancestor origin/main HEAD
```

Expected: exit code 0. If `main` advanced, merge current `origin/main`, resolve only genuine conflicts, and rerun Steps 1-3 before pushing.

- [ ] **Step 5: Push and open the PR without merging**

```powershell
git push -u origin fix/issue-680-schematic-runtime-discovery
gh pr create -R oaslananka/kicad-mcp-pro --base main --head fix/issue-680-schematic-runtime-discovery --title "fix(schematic): keep file-backed tools visible without editor" --body "Fixes #680`n`nTreat file-backed schematic tools as runtime-independent so they remain discoverable when the schematic editor is closed, while keeping sch_reload explicitly gated on live KiCad IPC. Includes capability, metadata, and tools/list runtime-filter regressions."
```

After PR creation, inspect required checks and unresolved review threads. Do not merge; report the PR URL and blockers to the user.