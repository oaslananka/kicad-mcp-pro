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

## Future sponsor demo — review-before-publication contract

**Status:** no sponsor-facing video approved or included in this PR. The preceding PCB-pan and scrolling-tool-log prototype recordings were explicitly rejected as unclear to viewers and have been removed. Historical backend proofs do not substitute for a visible, meaningful engineering workflow.

The next candidate must demonstrate a **real, visibly changing KiCad schematic or PCB** and answer the viewer's questions: what engineering task was requested; how did a named AI agent use KiCad MCP Pro; what exactly changed; did KiCad ERC/DRC independently confirm the result; and what happens on failure? A deterministic MCP harness must be labeled as such and cannot be sold as autonomous AI.

Acceptance requirements before any sponsor-facing claim:

1. Present a 45–90 second storyboard with the **problem**, the visible **before** state, a *real* agent/MCP operation, the visible **after** state, and independently checked ERC/DRC or another task-appropriate quality gate.
2. Do not show static mockups, pre-rendered steps, arbitrary cursor movement or scrolling logs in place of demonstrated product functionality. Clearly distinguish agent decisions from scripted MCP actions, and real KiCad editor views from static renders.
3. Use a disposable, license-clear sample with an exact pinned starting SHA and a reversible change; capture complete attempts, including failure/rollback, without cherry-picking unsupported success claims.
4. Verify safety, playback, privacy, relevant source/version provenance and measured results. No manufacturing readiness or full autonomy claim without the applicable benchmark.
5. **Owner review gate:** keep each proposed video **outside the PR and public assets until explicitly reviewed and approved**. Only after approval add it to the PR and update its public links/claims.

Historical [tool-smoke evidence](../evidence/agent-host-smoke-history.md) and the separate [native-live benchmark example](../evidence/task-outcomes/2026-08-28-native-live-example/README.md) are not full autonomous design-task success evidence. The maintained reference-board success criteria remain open (#729 and #730).

## Refresh before outreach

1. Re-read GitHub stars/forks from the [repository](https://github.com/oaslananka/kicad-mcp-pro) or the official GitHub API.
2. Re-read PyPI download events from the [pepy.tech project page](https://pepy.tech/projects/kicad-mcp-pro), including its update timestamp and CI-traffic note.
3. Replace numerical claims in any external pitch with newly dated values; never convert them to unique users.
4. Obtain explicit approval before sending a company email or sponsor application.
