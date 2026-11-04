# KiCad MCP Cloud — public agent integration guidance

## Overview
Use the HTTPS MCP endpoint and standard OAuth discovery to access only explicitly granted read-only KiCad project metadata. The client is not permitted to execute arbitrary commands or modify the owner's projects through this Cloud endpoint.

## Installation

Install KiCad MCP Pro on the owner's computer using the [official installation guide](https://oaslananka.github.io/kicad-mcp-pro/installation/).
Run `kicad-mcp-pro cloud setup` locally; `--browse` can open a native folder picker
for a KiCad project. Approve device pairing in your own browser.
Project paths and KiCad files are not uploaded by this setup guidance.

## Configuration

Connect a compatible AI client to the HTTPS MCP endpoint below.
Use OAuth Protected Resource Metadata to discover its authorization server
and PKCE S256; request only the advertised `projects:read` scope.
The owner must separately grant that client access to a specific project.

## Usage examples

After OAuth, use `get_service_status` to inspect which hosted features exist.
Use `list_devices` and `list_projects` to discover only granted device and
project aliases. Empty lists mean there is no active client-specific grant.
Do not infer that KiCad is running, an edit is authorized or a design has passed
ERC/DRC from a connected session.

## Discovery
- MCP: https://kicad-mcp-pro.oaslananka.dev/mcp
- OAuth Protected Resource: https://kicad-mcp-pro.oaslananka.dev/.well-known/oauth-protected-resource
- Public docs: https://oaslananka.github.io/kicad-mcp-pro/
- Privacy: https://oaslananka.github.io/kicad-mcp-pro/privacy/

## Access boundaries
A signed-in Cloud account, a paired local device, and an OAuth client grant are separate approvals. Never assume one authorizes the others. The current hosted scope is projects:read; do not invent cloud write tools or request unrestricted filesystem access.

## Safety and failure
If the device or project is absent, or OAuth authorization is denied, report the condition. Never work around project isolation, request provider secrets, send project files externally, or claim completed PCB validation based on metadata alone.
