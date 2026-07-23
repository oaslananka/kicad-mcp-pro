# Schematic Document Settings Service Design

## Context

Issue #434 is incrementally reducing `src/kicad_mcp/tools/schematic.py` from a domain-heavy registry into a small composition root. The remaining document-level settings tools still combine FastMCP registration, target selection, file transformation, transaction reporting, sheet-size policy, and reload orchestration in one nested scope.

This tranche extracts three related tools:

- `sch_set_title_block_info`
- `sch_set_sheet_size`
- `sch_auto_resize_sheet`

They form one stable capability boundary: editing schematic document metadata and selecting the sheet paper size. Rendering, placement, routing, templates, and circuit construction remain outside this tranche.

## Goals

- Make document settings behavior directly unit-testable without constructing FastMCP.
- Preserve exact public tool names, signatures, descriptions, schemas, defaults, annotations, transaction text, hashes, ordering, and errors.
- Keep target resolution, parsing, transaction writing, reload behavior, and existing geometry helpers injected from the composition root.
- Keep the new FastMCP adapter at or below 300 lines.
- Prevent the service or adapter from importing `kicad_mcp.tools.schematic`.

## Non-goals

- No new paper sizes or title-block fields.
- No public schema or metadata changes.
- No change to dry-run semantics, transaction verification, or reload ordering.
- No change to automatic placement or rendering behavior.
- No broad extraction of shared constants in this tranche.

## Recommended Architecture

Create `SchematicDocumentSettingsService` in `src/kicad_mcp/schematic/document_settings.py`. It owns the existing orchestration and document transformation behavior while depending on injected callables and immutable configuration values.

Create `src/kicad_mcp/tools/schematic_document_settings.py` as the thin FastMCP adapter. The adapter preserves the current nested function signatures, docstrings, defaults, and `headless_compatible` annotations, then delegates directly to the service.

Keep `src/kicad_mcp/tools/schematic.py` as the composition root. It constructs the service with the existing helpers and registers the adapter before the remaining nested tools.

## Service Interface

```python
@dataclass(frozen=True)
class SchematicDocumentSettingsService:
    def set_title_block_info(
        self,
        sheet: str | None,
        sheet_file: str | None,
        title: str | None,
        rev: str | None,
        date: str | None,
        company: str | None,
        comment1: str | None,
        comment2: str | None,
        comment3: str | None,
        comment4: str | None,
        dry_run: bool,
    ) -> str: ...

    def set_sheet_size(self, paper: str) -> str: ...

    def auto_resize_sheet(self) -> str: ...
```

Injected dependencies include:

- active schematic path lookup
- schematic target resolution
- schematic parser
- title-block update transformation
- transaction writer
- schematic reload
- target-detail formatting
- sheet-paper reader
- usable column and row calculators
- paper-size mapping
- layout origin, margin, and symbol half-size constants

The service may use `Path.read_text`, `hashlib`, and `re` directly. It remains FastMCP-free and does not import the registry module.

## Behavior Preservation

### Title block updates

The service builds the update mapping in the existing field order. Missing values are omitted, and an empty update returns the existing non-error message. It resolves the requested root or child schematic, computes the planned content, and preserves both dry-run and committed `MutatingToolResult` payloads.

Dry-run behavior must preserve:

- changed file and object lists
- SHA-256 before/after hashes
- `planned_not_written` verification
- exact summary text
- no write and no reload

Committed behavior must preserve:

- transactional write target
- post-write file read before reload
- reload ordering
- formatted target detail
- `validated` verification
- exact summary and compatibility text

### Explicit sheet size

The service trims the paper keyword, validates it against the injected paper-size mapping, and preserves the sorted available-size error. It keeps the current regex replacement/insertion behavior and the private no-change sentinel.

It preserves:

- existing paper detection and default to A4
- exact already-set and write-failure messages
- reload only after a successful write
- old/new dimensions
- usable grid calculations
- origin and margin text
- placement follow-up tip

### Automatic sheet size

The service parses symbols and power symbols, computes required dimensions with the existing half-size and margin constants, and selects the first fitting candidate from the current ordered list.

It preserves:

- empty schematic result
- candidate order
- no-standard-size result
- current-size-sufficient result
- delegation to `set_sheet_size` for the chosen size

## Error Handling

No new exception translation is introduced. Existing title-block helper and target-resolution exceptions continue to propagate as before. Explicit sheet resizing continues to catch its no-change sentinel separately and converts all other write-time exceptions to the existing compatibility string.

## Testing Strategy

Direct service tests cover:

- empty title-block updates
- field ordering and target selection
- dry-run hashes, transaction metadata, and absence of writes/reloads
- committed write/reload order and exact result text
- valid, invalid, missing, already-set, and failed sheet-size writes
- usable grid forwarding
- empty, fitting, oversized, and delegated automatic resize paths

Adapter tests cover exact public names, descriptions, defaults, input schemas, annotations, and argument delegation.

Architecture tests enforce service purity, adapter isolation, and the 300-line registration limit. Full-server metadata is compared byte-for-byte with `main`, and the committed tool-surface snapshot must remain unchanged.

## Expected Result

The main schematic `register()` function loses approximately 200 lines while all observable tool behavior remains unchanged. The extracted service can be tested without FastMCP, and future document-setting changes have a narrow review and regression surface.
