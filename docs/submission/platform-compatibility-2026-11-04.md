# KiCad MCP Pro — 2026-11-04 platform compatibility and submission gate

**Status: source candidate, not submitted.** This is an evidence snapshot,
not a certification by OpenAI, Anthropic or the MCP project. Recheck
published requirements on the actual submission date.

## Architecture assessment

| Component | Observed version/behavior | Decision |
| --- | --- | --- |
| Hosted Cloud MCP | The TypeScript server package is @modelcontextprotocol/server 2.4.0, matching the modern MCP 2026-07-28 SDK family. | Keep v2; no wholesale rewrite. |
| OAuth/CIMD | better-auth 1.7.13 includes @better-auth/mcp and @better-auth/cimd with metadataProfile mcp-2026-07-28. | Modern foundation; real browser OAuth acceptance still pending. |
| Hosted read-only tools | The registered tools expose only client-granted project metadata, status and bounded counts. All declare read-only annotations. | Do not market this as full local design editing or manufacturing signoff. |
| Existing root plugin | Root portable manifests and the Claude plugin use local stdio and include seven agent skills. | Preserve them for local KiCad workflows. |
| Remote directory package | integrations/cloud-directory-plugin contains OpenAI portable MCP + Skills and Claude remote MCP + skill metadata. | Packaging prepared, submission NOT performed. |
| Separate ChatGPT Apps sample | integrations/chatgpt-app/apps-sdk still uses MCP SDK 1.x; existing dashboard works in its own tests but is not a verified remote MCP Apps UI. | Modernize with the MCP Apps extension only in a separate scoped change. |
| MCP Apps | Standardized tool-attached UI resources can render within ChatGPT and Claude. | Optional enhancement, not a gate for an honest read-only text plugin. |
| MCP Tasks | The 2026-07-28 Tasks extension targets longer asynchronous operations. | Do not add a worker/task system for bounded metadata reads. |
| MCP Skills extension | Skills served over MCP are described by the beta extension. Ordinary Agent Skills remain portable files in plugin packages. | Use the existing SKILL.md format; no mandatory beta dependency. |
| Enterprise Managed Authorization | Extension is available to enterprise environments. | Not needed for individual-user launch. |

## Read-only live probes performed 2026-11-04

- Public HTTPS /health: HTTP 200, status ok, remoteConnector managed_read,
  deployed SHA 849a63ad09484c5c64925cafc0f7859d9725b477.
- Protected Resource Metadata: HTTP 200 at
  /.well-known/oauth-protected-resource, resource ending in /mcp, scoped
  authorization server under /api/auth, scopes_supported projects:read.
- Authorization Server Metadata: HTTP 200 at
  /api/auth/.well-known/oauth-authorization-server. The issuer is /api/auth,
  authorization/token endpoints are advertised, S256 PKCE is advertised,
  refresh_token is listed among supported grants, and CIMD metadata support
  is declared. This still does not prove a successful real client flow.
  A root-level
  /.well-known/oauth-authorization-server 404 is not proof of a broken issuer
  when the protected-resource document advertises a path-based issuer.
- Anonymous POST /mcp with server/discover: HTTP 401 with a Bearer
  WWW-Authenticate resource-metadata challenge. No access was granted.
- Coolify Cloud application was healthy but its deployed revision is behind
  main. Four Cloud UI files have changed. This is not evidence that current
  main has been deployed or visually accepted.

**These probes do not demonstrate real authorization-code / PKCE,
client-metadata acceptance, refresh tokens, revocation, or a complete client
session.** No test accounts, tokens, callback registrations, device
permissions or key material were created or changed.

## Official submission tracks as of 2026-11-04

**OpenAI Plugins Directory:** Remote MCP with HTTPS is submitted with MCP;
the current format is a portable Agent Plugins package with MCP configuration
and optional Agent Skills. The candidate declares OAuth/CIMD with read-only
scope, without any embedded OAuth secret or invented client ID. Initial
remote-MCP review requires five positive cases, three negative cases, a
reviewer-accessible demonstration, domain verification and a real connection.
The legacy separate ChatGPT Apps form/document is not sufficient by itself.

**Claude:** The September 2026 directory accepts a remote MCP connector
directly or an MCP plus Agent Skills plugin. A locally executed stdio plugin
remains a different product surface. The Claude plugin configuration in the
candidate references the same public /mcp endpoint and no bearer secret.

## Portable schema and vendor authentication compatibility

The published Agent Plugins 1.0 MCP JSON schema currently rejects any
server-level vendor-specific extensions property, although the current OpenAI
Plugins packaging guide explicitly documents placing OAuth/CIMD at
mcpServers.<name>.extensions.com.openai.auth. The candidate follows the
OpenAI submission instructions and preserves an otherwise schema-valid
streamable-http server. Do **not** describe the entire mcp.json as valid under
the unextended portable MCP schema until the published schema and importer
converge. OpenAI dashboard import/connection validation is a separate gate;
do not silently drop the OAuth declaration merely to pass a generic schema
validator.

## Remaining acceptance steps (NOT DONE)

- [ ] Verify actual OAuth code+PKCE login in ChatGPT and Claude, through
      the correct /api/auth issuer, without permanent secrets in the repo.
- [ ] Confirm token refresh, expiry, client revocation and per-project
      permission withdrawal; cross-client project isolation must deny reads.
- [ ] Grant only a public/demo KiCad fixture project to a reviewer client and
      demonstrate real calls to list_projects and an available read-only
      project tool with a foreground owner connector session.
- [ ] Test five successful reviewer prompts and three denial cases:
      ungranted/foreign project, malformed project ID, and a write/export
      request not present in the hosted tool catalog.
- [ ] Prepare safe reviewer-accessible media and a demo recording; enter any
      reviewer credentials ONLY into secure platform review fields.
- [ ] Verify domain ownership and platform organization/publisher identity.
- [ ] Validate the four updated Cloud UI files with browser smoke tests on
      an accepted new deployment, separately from plugin packaging.
- [ ] Only then upload to OpenAI/Claude for review. No support tickets, email
      or application submission have been sent.

**Stop rule:** No extra staging environment, paid service, local passkey/FIDO2
gate, multi-agent coordinator, arbitrary background task system or speculative
MCP Apps UI rewrite. Add a capability when an actual user/reviewer workflow
and platform host acceptance require it.

## Official reference links

- MCP 2026-07-28: https://blog.modelcontextprotocol.io/posts/2026-07-28/
- MCP Skills beta: https://skills.extensions.modelcontextprotocol.io/specification/beta/skills
- MCP Apps: https://apps.extensions.modelcontextprotocol.io/api/
- OpenAI portable plugins: https://developers.openai.com/plugins/build/plugins
- OpenAI review: https://developers.openai.com/plugins/deploy/submission
- OpenAI authentication: https://developers.openai.com/plugins/build/auth
- Claude 2026 directory: https://claude.com/resources/articles/build-plugins-for-claude
- Claude remote connectors:
  https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
