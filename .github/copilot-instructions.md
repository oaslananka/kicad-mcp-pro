# KiCad MCP Pro — GitHub Copilot entry point

Follow the repository [`AGENTS.md`](../AGENTS.md) router and the nearest scoped
`AGENTS.md` for every change. Do not replace them with duplicated policy text.

- Start in read-only mode; use KiCad MCP tools before local file transformations.
- Never rewrite `.kicad_pcb` or `.kicad_sch` by shell/regex when a safe MCP
  mutation tool is unavailable. Ask for the required profile/tool instead.
- Do not bypass branch protection, workflow gates, path checks, release guards,
  or manufacturing approvals. ERC/DRC is evidence, not human engineering signoff.
- Load only relevant skills from `.agents/skills/`; canonical source: `skills/`.
  Change canonical skills then run `python scripts/sync_agent_skills.py --write`.
- Verify scope and security with repository-native tests and policies.
