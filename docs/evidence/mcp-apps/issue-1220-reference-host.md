# Issue #1220 — MCP Apps reference-host acceptance evidence

**Observed:** 2026-11-16, AMD2700X, Windows 11 Pro, Chrome 160 (browser-agent session).
**Scope:** disposable synthetic data only. No real KiCad application, files, Cloud connector, manufacturing, write permission, public server or deployment was exercised.
**Status:** the host did render the isolated review component in a sandbox. This is **reference-host compatibility**, not ChatGPT or Claude certification.

## Reproduction pins

| Component | Exact version or identity |
| --- | --- |
| MCP Apps specification | stable 2026-01-26, `io.modelcontextprotocol/ui` |
| Research widget SDK | `@modelcontextprotocol/ext-apps@2.0.4` |
| MCP client/server | `@modelcontextprotocol/client@2.4.0` and `@modelcontextprotocol/server@2.4.0` |
| Node / pnpm | Node 26.13.1 / pnpm 11.28.6 |
| Reference host | `modelcontextprotocol/ext-apps` at `ea3e9d0e624a20bc1c51310292f09d9b8ed17161`, `examples/basic-host` v2.1.0 |
| Host toolchain | Bun 1.4.4; built via its pinned npm lockfile and Vite build |
| Fixture HTTP | `http://127.0.0.1:3001/mcp` (loopback only) |
| Host / iframe origins | `http://localhost:8080` (host) and `http://localhost:8081` (sandbox) |

Pinned basic-host was built **outside the KiCad repository** and started with a single configured fixture server URL. The only fixture tool is `review_kicad_fixture`; the only UI resource is `ui://kicad-mcp-pro/readonly-review`. No root production package, npm workspace or Python MCP registry was changed.

## Observed real-browser results

| Scenario | Result |
| --- | --- |
| Host connected over Streamable HTTP | PASS — host discovered exactly one tool and one resource; resource read and iframe load succeeded |
| PCB / DRC, default tool input `{}` | PASS — synthetic Sensor Controller Example displayed 2 errors and 1 warning |
| Filter `Warnings` | PASS — native browser click reduced visible list to the single silkscreen warning |
| Schematic / ERC, input `{"variant":"schematic-erc"}` | PASS — synthetic Power Supply Example displayed 1 error and 1 warning |
| Empty result, `{"variant":"empty"}` | PASS — 0/0 counts and explicit “No findings.” |
| Invalid path-like variant, `{"variant":"../secrets"}` | PASS — MCP returned input-validation error; iframe displayed “Review unavailable” without revealing a path |
| 360 CSS-pixel mobile viewport and dark emulation | PASS — card content was readable at the narrow width; an initial incorrect light-mode fallback was corrected with failing-then-passing tests and observed in a subsequent dark iframe |
| No-UI MCP client | PASS (protocol test) — tool returns full human-readable text in `content` in addition to `structuredContent` |
| Host UI handshake and result delivery | PASS — host console showed UI resource transfer and iframe initialization, and the visual findings confirmed delivery |

The pinned reference host was exercised again after the stricter localhost-only CORS change; it connected to the restarted fixture and rendered the PCB/DRC 2-error/1-warning review. The safety check did not break the supported host. One initial browser invocation exposed invalid script syntax caused by string-replacement interpolation in the HTML bundler; a regression test reproduced the failure. After correcting the bundler, subsequent real-host calls rendered and supported filtering. A separate browser-theme regression was reproduced and corrected.

## Sandboxing, CSP, permissions and limitations

- The inspected **reference host iframe** loaded from port 8081 (distinct origin from host port 8080) with `sandbox="allow-scripts allow-same-origin allow-forms"`; the host did not grant additional `allow` permissions.
- The **fixture resource metadata** uses `_meta.ui.csp` with all four arrays `connectDomains`, `resourceDomains`, `frameDomains`, `baseUriDomains` empty.
- The reference host returned the following effective CSP header on the sandbox document: `connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'` plus script/style resource policies. **Important limitation:** the host's own default `script-src` permits `'unsafe-inline'`, `'unsafe-eval'`, `blob:` and `data:`; its iframe has `allow-same-origin` and `allow-forms`. Thus this proof does **not** claim an especially strict host-supplied script policy. A different production host must be assessed independently before opt-in.
- Loopback server request enforcement: HTTP test verified the host's localhost:8080 CORS preflight is accepted; arbitrary Host, external Origin, alternate loopback Origin and sandbox Origin (`localhost:8081`) are denied; over-budget request bodies receive HTTP 413. No application code invokes a tool from the iframe.
- Network records observed during the successful tool calls showed only the configured local MCP endpoint and local sandbox document; **not a comprehensive network-exfiltration audit**. No external origin is configured in the widget.
- Node/TypeScript tests (24/24 PASS after the CORS, bidi-control and static-analysis fixes) cover schema validation, HTML-as-text rendering, tool/resource contract, invalid inputs, CORS, CSP metadata, bundle syntax, empty/error states, repeated-result replacement, and explicit/unspecified theme.
- Keyboard navigation was exercised in Chrome: focus moved from Errors to All with Shift+Tab, and Enter restored all findings. The native buttons and ARIA states are also exercised at DOM level. Full screen-reader acceptance and third-party conversational-host certification were **not** performed.
- The reference host builds successfully but reports upstream Rollup warning comments from Zod. These warnings do not come from the fixture.
- Python tests were rerun in a repository-pinned, isolated **uv 0.13.7** environment with dev + components extras and an agent-owned temporary directory: **10/10 targeted tests passed** (three new isolation tests plus native MCP 2026 host/protocol checks). Earlier global Python had unrelated OpenTelemetry import problems and the default Windows pytest temporary directory had a permission error; neither required a production dependency change. The **entire** Python test suite was not run locally.

**Stop boundary:** This is a disposable read-only research demonstration, not authorization to surface Apps from the production KiCad MCP server. The existing ChatGPT connector and Cloud WRITE authorization are separate issues. If this reference host's permissive CSP is unsuitable for a production use case, evaluate a stricter host before promotion.

## Verification and teardown

Run from `tests/research/mcp_apps_readonly`:

```sh
pnpm install --frozen-lockfile
pnpm test
pnpm typecheck
pnpm audit --prod --audit-level high
```

For the fast isolation test without root conftest:

```sh
python -m pytest -q --noconftest tests/unit/test_mcp_apps_research_isolation.py
```

For the full targeted Python check, use the repository-pinned uv version with `--extra dev --extra components` and a private pytest `--basetemp` directory. Stop the **specific** temporary fixture and host processes after testing; verify ports 3001, 8080 and 8081 are no longer listening. Never terminate unrelated processes by port without checking ownership. No service was deployed.
