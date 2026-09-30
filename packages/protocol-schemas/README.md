# KiCad Protocol Schemas

`@oaslananka/kicad-protocol-schemas` owns the product-neutral JSON Schema
contracts shared by the KiCad Studio extension and `kicad-mcp-pro`.

The package has no VS Code API dependency and no Python server runtime
dependency. TypeScript consumers can import the schema registry and Ajv-backed
validators. Python contract tests read the same `schemas/*.schema.json` files
directly with `jsonschema`.

## Included Contracts

- MCP tool discovery payloads returned by `tools/list`.
- Tool capability metadata advertised by `kicad-mcp-pro`.
- Reviewed tool-effect manifests for external fail-closed policy consumers.
- Extension-to-MCP active context payloads.
- Normalized DRC/ERC diagnostic records.
- BOM and netlist summary payloads.
- MCP server health/version payloads.
- Compatibility manifests for cross-product schema support.
- The existing KiCad MCP server-info contract.

## Schema versioning policy

Every schema file carries an `x-kicad-studio-kit.schemaVersion` value using
`MAJOR.MINOR.PATCH`. Breaking schema changes require a major version bump.
Backward-compatible field additions use a minor version bump, and documentation
or constraint-only fixes use a patch version bump.

The package version follows the highest schema major in the package. A consumer
that supports schema major `1` may accept any `1.x.y` payload after validation.
Consumers must reject unknown major versions unless the caller explicitly opts
into compatibility fallback behavior.

## Migration policy

Schema migrations are additive first. When a field must be renamed or removed,
the old field remains accepted for one minor line and the new field is documented
in this README and in the affected schema description. The next major version
may remove the deprecated field after extension and MCP contract tests both pass
against the replacement payload.

Run the schema package checks from the repository root:

```bash
corepack pnpm run check:protocol-schemas
```
