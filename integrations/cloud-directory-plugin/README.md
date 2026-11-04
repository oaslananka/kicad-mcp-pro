# KiCad Cloud Review — directory candidate (NOT SUBMITTED)

This directory is a remote, read-only plugin candidate for
https://kicad-mcp-pro.oaslananka.dev/mcp. It is deliberately separate
from the root portable plugin.json and mcp.json, which install the local
KiCad CLI over stdio and must not be silently converted to a remote service.

## Platforms

- OpenAI Plugins (With MCP): package plugin.json, mcp.json and
  skills/cloud-project-review/SKILL.md using the portable Agent Plugins
  format. OpenAI-specific OAuth uses CIMD with only projects:read; no
  credentials or callback tokens are stored in this repository.
- Claude: the remote .mcp.json and .claude-plugin/plugin.json are provided
  for the native Claude plugin format. Claude's single MCP connector
  listing is a simpler initial option, while the plugin route can
  include this read-only skill.

## Make separate submission archives (do not upload before acceptance)

From this package directory, create only the files for the selected host:

    zip -X -q /tmp/kicad-cloud-openai-candidate.zip       plugin.json mcp.json skills/cloud-project-review/SKILL.md

    zip -X -q /tmp/kicad-cloud-claude-candidate.zip       .claude-plugin/plugin.json .mcp.json       skills/cloud-project-review/SKILL.md

The repository root's local stdio manifests must not be included. These
source candidate archives are **not** a platform approval and must not include
any reviewer credentials or test secrets. Inspect the archive file list before
upload. The OpenAI-specific OAuth extension in mcp.json requires validation
through OpenAI's real importer because the generic Agent Plugins MCP schema
does not yet recognize vendor extensions on server entries.

## Not yet reviewed or approved

The presence of an OAuth discovery document and a 401 response from an
anonymous MCP call does not prove real authorization-code + PKCE, refresh,
revocation, per-client project grants, or reviewer fixture access. Before
submission, verify those operations with actual ChatGPT and Claude clients,
using a dedicated demo-only project, then complete OpenAI's required 5
positive / 3 negative review scenarios and demo recording. Reviewer
credentials belong only in the platforms' secure review forms. Do not package
them or create a second authentication system to satisfy a checklist.

This package provides no local KiCad write access, no unapproved desktop
filesystem access, no automatic background actions and no support for
sending board files to a manufacturer.

See docs/submission/platform-compatibility-2026-11-04.md in the repository
for current compatibility evidence and remaining acceptance tasks.
