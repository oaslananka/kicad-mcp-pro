# Privacy Policy

**Effective date:** 2026-05-15
**Service:** KiCad MCP Pro
**Operator:** Osman Aslan (oaslananka)
**Contact:** https://github.com/oaslananka

---

## 1. Overview

KiCad MCP Pro is a **local stdio MCP server** that runs entirely on your machine.
It communicates with KiCad via the KiCad CLI and local file system.
No data is transmitted to external servers by default. Operators may explicitly
configure OpenTelemetry export to their own OTLP collector for operational
monitoring.

---

## 2. Data We Collect

| Data Type                        | Collected?        | Notes                                                       |
| -------------------------------- | ----------------- | ----------------------------------------------------------- |
| Personal information             | **No**            |                                                             |
| File contents (schematics, PCBs) | **No**            | Processed locally only                                      |
| Usage telemetry                  | **No by default** | Optional OpenTelemetry export must be explicitly configured |
| IP addresses                     | **No**            |                                                             |
| Cookies                          | **No**            |                                                             |

KiCad MCP Pro does not have a backend, does not phone home, and does not store
any user data. Optional OpenTelemetry export sends only operational spans and
metrics to the collector configured by the operator; exported attributes omit
project paths, design contents, request arguments, CLI output, and collector
headers.

---

## 3. Local Processing Only

All tool calls (DRC, export, schematic parsing, etc.) are executed by spawning
`kicad-cli` on the **user's local machine**. Results are returned to the calling
MCP client (e.g. Claude Desktop) over a local stdio transport. Nothing leaves
the user's machine through this server unless the operator explicitly enables
OpenTelemetry export to a collector they control.

---

## 4. Optional Integrations

If the user configures optional integrations (e.g. Freerouting via Docker, Nexar
component API), those third-party services are governed by their own privacy
policies. KiCad MCP Pro passes only the minimum data required for each
integration.

---

## 5. Children's Privacy

This software is a developer tool not directed at children under 13. We do not
knowingly collect data from children.

---

## 6. Changes

If this policy changes materially, the effective date above will be updated and
the change will be noted in the repository CHANGELOG.

---

## 7. Contact

Open an issue at https://github.com/oaslananka/kicad-mcp-pro/issues or contact
via GitHub profile: https://github.com/oaslananka
