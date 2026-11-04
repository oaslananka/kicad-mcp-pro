# Gemini CLI Integration

## Quick Start

```bash
uvx kicad-mcp-pro quickstart --agent gemini
```

To install only for one trusted project, use
`kicad-mcp-pro setup gemini --project-dir /path/to/project --scope project --write`.
This merges the read-only KiCad server into `<project>/.gemini/settings.json`
without changing your user-wide Gemini settings or other MCP servers.

Or manually add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "uvx",
      "args": ["kicad-mcp-pro"],
      "env": {
        "KICAD_MCP_PROJECT_DIR": "$PWD",
        "KICAD_MCP_PROFILE": "default",
        "KICAD_MCP_OPERATING_MODE": "readonly"
      },
      "cwd": ".",
      "timeout": 30000,
      "trust": false,
      "includeTools": [
        "kicad_get_project_info",
        "project_quality_gate",
        "run_erc",
        "run_drc",
        "validate_design"
      ]
    }
  }
}
```

## Verification

```
/mcp  →  verify the kicad server is connected
```

## Slash Prompt

Add to your Gemini repo instructions:

> When the task involves KiCad, use the kicad MCP server.
> Default policy: inspect before editing. Run quality gates before suggesting release.
> Never run destructive tools without explicit user confirmation.
> Prefer read-only tools first.

## Remote

```json
{
  "mcpServers": {
    "kicad-cloud": {
      "httpUrl": "https://kicad-mcp-pro.oaslananka.dev/mcp",
      "timeout": 30000,
      "trust": false
    }
  }
}
```


Gemini CLI supports standard OAuth discovery for remote MCP connections;
run the /mcp auth kicad-cloud command if the client requires authentication.
The current Cloud advertises only projects:read, and a separately authorized
project grant is required; the remote connector does not supply desktop
write/edit tools.

Google Gemini Apps custom MCP connections are a separate host product.
Per Google's November 2026 documentation, they are currently available
only to eligible US personal Google accounts with Gemini activity enabled
and in English. Even on eligible accounts, Google may require dynamic client
registration (RFC 7591), client metadata compatibility and additional
redirect allowlisting; an authorization server advertising CIMD is not
proof of successful Google registration. Do not bypass Google geo/account
limits or downgrade OAuth to unauthenticated access. Use the Gemini CLI
path above for a host-independent protocol smoke test.

- [Official Gemini CLI MCP + OAuth guide](https://geminicli.com/docs/tools/mcp-server/)
- [Google Gemini Apps custom MCP prerequisites](https://support.google.com/gemini/answer/17209137)
- [Google Connected Apps troubleshooting](https://developers.google.com/connected-apps/gpc/troubleshooting)

## Gemini CLI extension pilot (opt-in)

A local, unsubmitted extension combines the MCP server connection with the
**seven generated Agent Skills**. See
[`integrations/gemini-cli/kicad-mcp-pro/`](../../integrations/gemini-cli/kicad-mcp-pro/).
On a trusted developer machine where Gemini CLI and `uvx` are installed:

```bash
gemini extensions install ./integrations/gemini-cli/kicad-mcp-pro
gemini extensions list
```

Gemini copies local extension packages, so installed copies do not update when
this repository changes. The extension defaults to **readonly** mode and requests the
version-matched published PyPI package through `uvx --from` rather than a
floating latest package.
This is version pinning, **not** independently verified wheel provenance or a
lock of every transitive dependency. A pre-existing `settings.json` entry can
override its MCP server definition.
Review that precedence before declaring the installation safe. A static
manifest check is **not** real-host verification: follow
[the host smoke checklist](host-verification.md) and log the actual outcome.
