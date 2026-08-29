# Distribution and onboarding readiness

This matrix separates repository contract evidence from physical/product evidence.
A file existing in the repository is not enough to mark a surface verified.

| Surface | Current status | Objective evidence | Notes |
| --- | --- | --- | --- |
| CLI / `uvx` | Existing verified surface | `tests/e2e/test_stdio_startup.py`, Python release workflow | Remains the first-class power-user and automation path. |
| PyPI | Existing release surface | `.github/workflows/publish-python.yml`, release-evidence tests | PCM does not replace Python distribution. |
| npm launcher | Existing release surface | `.github/workflows/publish-npm.yml`, npm package CI | Separate launcher for supported MCP clients. |
| MCPB | Existing release surface | `.github/workflows/publish-mcpb.yml`, `tests/unit/test_release_hardening.py` | Attested/versioned release asset contract. |
| Docker / GHCR | Existing release surface | `.github/workflows/publish-mcp-container.yml`, container tests | No change from PCM work. |
| Desktop | Existing release surface | GUI CI/release workflows and desktop/backend compatibility tests | Exact-release backend compatibility remains independent of PCM. |
| **KiCad PCM** | **Physical Linux + Windows verified; macOS physical host pending** | [Linux physical evidence](../evidence/kicad-pcm/2026-08-29/linux-kicad-10.0.5.md), [Windows physical evidence](../evidence/kicad-pcm/2026-08-29/windows-kicad-10.0.5.md), `tests/unit/test_kicad_pcm_packaging.py`, `tests/unit/test_companion_context.py`, `.github/workflows/publish-kicad-pcm.yml` | Linux install/restart/health/MCP/update/incompatible/uninstall/rollback is physically verified on two independent Linux hosts. Windows physical PCM flow verified for install/restart/health/MCP/incompatible/uninstall/rollback. macOS physical host unavailable, so CI is not presented as physical evidence. |
| Claude Code guided config | Transaction contract verified; physical flow pending | `tests/unit/test_issue_731_onboarding.py` | Preview is side-effect-free; explicit write is merge-safe/backed up/reversible. |
| Codex guided config | Transaction contract verified; physical flow pending | `tests/unit/test_issue_731_onboarding.py` | Owned TOML sections are replaced without replacing unrelated text/tables. |
| Cursor guided config | Transaction contract verified; physical flow pending | `tests/unit/test_issue_731_onboarding.py` | JSON server-map merge preserves unrelated configuration. |
| VS Code / Copilot config | Existing config contract | `tests/unit/test_setup.py`, `docs/agents/vscode-copilot.md` | Physical PCM-guided onboarding is not claimed by this tranche. |
| Official PCM listing | **Not submitted** | [KiCad PCM submission plan](../submission/kicad-pcm.md) | Submission waits for a public release asset plus physical package evidence. |

## Promotion rule

The PCM surface may be described as **physically verified on Linux and Windows**.
Two independent Linux hosts and one Windows host demonstrate the versioned artifact
through install/update or clean install, restart/discovery, backend health, MCP
lifecycle/read-only smoke, incompatible-version fail-closed behavior, uninstall, and
rollback. Full cross-platform **Verified** status remains blocked only because the
macOS physical host unavailable boundary is explicitly documented as CI-only rather
than physical evidence.

Physical evidence must identify the exact source revision and artifact SHA256 without
exposing local credentials, private paths, or unrelated desktop content.

Client rows similarly distinguish unit-level transaction safety from a real
installed-client flow. A successful config unit test does not prove the external
client binary accepted or used that config.
