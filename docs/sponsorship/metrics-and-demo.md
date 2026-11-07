# Sponsor evidence, metrics and real-demo plan

**Evidence snapshot compiled: 2026-11-07.** Counts may change. This file is a dated audit aid; refresh primary sources before each outbound proposal. Do not copy a frozen statistic into an undated evergreen headline.

## What is verifiable now

| Signal | Observation | Source and scope |
| --- | --- | --- |
| PyPI lifetime download events | **108,995** | [pepy.tech](https://pepy.tech/projects/kicad-mcp-pro), observed 7 Nov 2026; page indicates update 4 Nov 2026 |
| PyPI rolling 30-day download events | **24,427** | Same pepy.tech snapshot; rolling window, includes CI activity |
| GitHub stars | **183** | GitHub repository API `GET /repos/oaslananka/kicad-mcp-pro`, observed 7 Nov 2026 |
| GitHub forks | **35** | Same official GitHub API response, observed 7 Nov 2026 |
| MIT-licensed project and published distributions | Verified repository metadata and README | [source repository](https://github.com/oaslananka/kicad-mcp-pro), [PyPI](https://pypi.org/project/kicad-mcp-pro/), [npm](https://www.npmjs.com/package/kicad-mcp-pro) |
| Independent written engineering coverage | A supplier-written tutorial exists; **not** sponsorship/endorsement | [JLCPCB's independent tutorial](https://jlcpcb.com/blog/kicad-mcp-how-to-design-a-pcb-with-claude-code); limitations and follow-up linked in the README |

**Interpretation limits:** Downloads are not unique people. CI, scripted installs, crawlers and repeated installs can inflate event totals. A star/fork is not a paid customer, an active installation or commercial conversion. No claim is made here about active users, revenue, supplier sales, representative live-board task success or manufacturing qualification. A public npm-total badge exists, but an authoritative numeric snapshot is not recorded here.

## Demo media already in the repository

[`docs/demo-media.md`](../demo-media.md) describes a ~30-second **deterministic, synthetic** terminal cast (`docs/assets/demo.cast`) and GIF. It is useful to explain basic commands but **cannot be labeled as a real live KiCad/agent integration recording**. Its own procedure says to replace simulated output with an actual fresh recording if presenting it as real evidence.

Existing [historical native-agent smoke evidence](../evidence/agent-host-smoke-history.md) documents a real read-only host integration under the stated host/version constraints. The [native-live benchmark example](../evidence/task-outcomes/2026-08-28-native-live-example/README.md) explicitly reports **insufficient evidence** for headline task-success targets. Neither document independently establishes current desktop acceptance or general manufacturing readiness.

## Real sponsor demo — proposed 35–45-second capture

**Status: storyboard prepared; new real end-to-end video has not been recorded or verified by this sponsorship task.**

1. **0–7 s — provenance:** show the exact source/version and a disposable sample KiCad project; redact paths, account details and tokens.
2. **7–15 s — genuine MCP connection:** show a real local agent client discovering the server's read-only tools. Preserve the recorded original command and full uncut output elsewhere for audit.
3. **15–27 s — board inspection:** open the board in KiCad and execute a real read-only project/board inspection through an MCP tool. Show the actual observed result, not a synthetic expected response.
4. **27–38 s — validation:** use a tool that actually invokes KiCad's ERC/DRC engine in that tested setup; label real counts exactly. If a safe read-only rule-check is unavailable for that installed version, omit it and explain why.
5. **38–45 s — scope:** end with the product and the explicit message `Human engineering review required before manufacture`.

### Capture acceptance checklist

- Exact software, KiCad and agent versions pinned; demonstrator source and temporary example project identified.
- Screen capture of a real application and real tool traffic, not an animated mockup; no synthetic or edited JSON passed off as live results.
- Demonstration shows no secret, private board, personal path, credential or unrelated desktop content.
- Record whether command succeeded, what was measured, and what was **not** verified (e.g. native desktop onboarding, PCB fabrication, full-corpus task success).
- No unauthorised design mutation, external manufacturing order or sponsor-branded claim.
- Publish only after the capture file has been reviewed and playback can be independently verified.

**Current gap:** the ~45-second verified real capture needs a physical KiCad+MCP run and review. The present record establishes a safe scenario and existing evidence, not the video itself.

## Refresh before outreach

1. Re-read GitHub stars/forks from the [repository](https://github.com/oaslananka/kicad-mcp-pro) or the official GitHub API.
2. Re-read PyPI download events from the [pepy.tech project page](https://pepy.tech/projects/kicad-mcp-pro), including its update timestamp and CI-traffic note.
3. Replace numerical claims in any external pitch with newly dated values; never convert them to unique users.
4. Obtain explicit approval before sending a company email or sponsor application.
