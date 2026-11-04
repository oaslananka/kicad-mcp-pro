# KiCad MCP Cloud — public agent integration guidance

## Overview
Use the HTTPS MCP endpoint and standard OAuth discovery to access only explicitly granted read-only KiCad project metadata. The client is not permitted to execute arbitrary commands or modify the owner's projects through this Cloud endpoint.

## Discovery
- MCP: https://kicad-mcp-pro.oaslananka.dev/mcp
- OAuth Protected Resource: https://kicad-mcp-pro.oaslananka.dev/.well-known/oauth-protected-resource
- Public docs: https://oaslananka.github.io/kicad-mcp-pro/
- Privacy: https://oaslananka.github.io/kicad-mcp-pro/privacy/

## Access boundaries
A signed-in Cloud account, a paired local device, and an OAuth client grant are separate approvals. Never assume one authorizes the others. The current hosted scope is projects:read; do not invent cloud write tools or request unrestricted filesystem access.

## Safety and failure
If the device or project is absent, or OAuth authorization is denied, report the condition. Never work around project isolation, request provider secrets, send project files externally, or claim completed PCB validation based on metadata alone.
