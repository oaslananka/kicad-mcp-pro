# Distribution and onboarding readiness

This matrix separates repository contract evidence from physical/product evidence.
A file existing in the repository is not enough to mark a surface verified.
Historical Claude Code and Codex host runs are retained in the
[dated agent-host evidence index](../evidence/agent-host-smoke-history.md).
They do not establish current host/skill/extension compatibility; see #1219.

| Surface | Current status | Objective evidence | Notes |
| --- | --- | --- | --- |
| CLI / `uvx` | Existing verified surface | `tests/e2e/test_stdio_startup.py`, Python release workflow | Remains the first-class power-user and automation path. |
| PyPI | Existing release surface | `.github/workflows/publish-python.yml`, release-evidence tests | PCM does not replace Python distribution. |
| npm launcher | Existing release surface | `.github/workflows/publish-npm.yml`, npm package CI | Separate launcher for supported MCP clients. |
| MCPB | Existing release surface | `.github/workflows/publish-mcpb.yml`, `tests/unit/test_release_hardening.py` | Attested/versioned release asset contract. |
| Docker / GHCR | Existing release surface | `.github/workflows/publish-mcp-container.yml`, container tests | No change from PCM work. |
| Local browser dashboard | Active local UI | `tests/e2e/test_web_dashboard.py`, [installation guide](../installation.md) | Account-free loopback HTTP; historic Tauri installers are archive-only ([#1676](https://github.com/oaslananka/kicad-mcp-pro/pull/1676), [#1680](https://github.com/oaslananka/kicad-mcp-pro/pull/1680)). |
| **KiCad PCM** | **IPC package: Linux virtual-display lifecycle and behavior verified; Windows/macOS interactive acceptance pending** | [Current 4.24.0 IPC evidence](../evidence/kicad-pcm/2026-11-27/kicad-10.0.8-ipc.md), [Linux physical evidence](../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md), [Windows physical evidence](../evidence/kicad-pcm/2026-08-29/windows-kicad-10.0.5.md), `tests/unit/test_kicad_pcm_packaging.py`, `tests/unit/test_companion_context.py`, `.github/workflows/publish-kicad-pcm.yml` | Linux KiCad 10.0.8: PCM file lifecycle and separate toolbar/repair/read/sync checks. Windows: dependency and transport checks passed; board read returned AS_NOT_READY on an inactive private desktop. Historical SWIG-era evidence does not qualify current IPC; macOS physical host unavailable. |
| Claude Code guided config | Real client connect verified | [Linux physical evidence](../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md), `tests/unit/test_issue_731_onboarding.py` | Claude Code `2.1.238` used its native `mcp add`/`mcp get` flow against the live loopback backend and reported `Status: Connected`; user configuration was isolated. |
| Codex guided config | Real client connect verified | [Linux physical evidence](../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md), `tests/unit/test_issue_731_onboarding.py` | Codex CLI `0.150.1` completed initialize/initialized/tools-list and a real read-only `kicad_get_version` tool call after negotiated-protocol compatibility was fixed in #813. |
| Cursor guided config | Physical guided transaction verified | [Linux physical evidence](../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md), `tests/unit/test_issue_731_onboarding.py` | A disposable project-scoped config exercised side-effect-free preview, explicit write, unrelated-key preservation, backup, exact-targeting, and hash-exact restore. A Cursor binary connect is not claimed. |
| VS Code / Copilot config | Existing config contract | `tests/unit/test_setup.py`, `docs/agents/vscode-copilot.md` | Physical PCM-guided onboarding is not claimed by this tranche. |
| Official PCM listing | **Not submitted** | [KiCad PCM submission plan](../submission/kicad-pcm.md) | Submission waits for a public release asset plus physical package evidence. |

## Promotion rule

Historical SWIG-era PCM lifecycle evidence covers two independent Linux hosts
and the historical Windows physical PCM flow, including install/restart, health,
MCP, uninstall and rollback on the documented 3.33.3 release. It must not be
promoted to current IPC qualification. The [current IPC evidence](../evidence/kicad-pcm/2026-11-27/kicad-10.0.8-ipc.md) records
the exact published 4.23.0 and 4.24.0 Linux virtual-display PCM lifecycle,
separate toolbar/repair/read/sync checks and the Windows readiness blocker.
These are separate acceptance runs, not a single integrated physical flow.
Keep the package in development status until the outstanding integrated and
applicable platform evidence is verified. Official listing remains not submitted.

Physical evidence must identify the exact source revision and artifact SHA256 without
exposing local credentials, private paths, or unrelated desktop content.

Client rows similarly distinguish unit-level transaction safety from a real
installed-client flow. A successful config unit test does not prove the external
client binary accepted or used that config.
