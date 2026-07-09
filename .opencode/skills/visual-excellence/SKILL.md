---
name: visual-excellence
description: Drive a KiCad schematic to a professional, cosmetically clean state through a score → fix → render → verify loop using KiCad MCP Pro cosmetic tools.
---

# Visual Excellence Skill

Use this skill when an AI agent is asked to make a KiCad schematic *look*
professional — clean, readable, and conventionally drawn — not just electrically
correct. It closes the loop between measuring cosmetic quality, applying safe
fixes, and visually confirming the result.

This skill is specific to `oaslananka/kicad-mcp-pro` and should be kept
synchronized with `docs/tools-reference.generated.md`.

## When to use

- Post-capture cleanup before layout or review
- Preparing a schematic for a datasheet, report, or customer hand-off
- Whenever a sheet "works but looks rushed": off-grid parts, diagonal wires,
  colliding labels, sideways power symbols, inconsistent fonts

Do **not** use this skill to claim electrical correctness. Cosmetic fixes never
substitute for ERC, connectivity review, or human engineering approval. Run
`sch_visual_qa` / `run_erc` separately for correctness.

## The invariant you can rely on

Every cosmetic fixer treats **electrical connectivity as a hard invariant**. It
computes a coordinate-independent connectivity signature before and after the
change; a fixer that would alter any net is *refused* on apply and never writes.
So you can apply fixes without fear of silently breaking a net — but always
confirm with the render and the visual diff, and finish with an ERC pass.

## Required context

- Active project path and the schematic file(s)
- The target cosmetic score (default: 80/100)
- Whether you are allowed to modify the schematic (this skill mutates on
  `apply=true`; it needs write operating mode)

## Primary MCP tools

### Measure

- `sch_cosmetic_score` — 0–100 score with a per-category penalty breakdown and
  the `worst_category` to fix first (`grid`, `wiring`, `typography`,
  `orientation`, `layout_balance`, `readability`, `documentation`)
- `sch_visual_qa` — readability findings (overlaps, off-sheet, dense fanout)

### Fix (dry-run by default; pass `apply=true` to commit)

- `sch_align_to_grid` — snap off-grid symbols, labels, wires, junctions
- `sch_straighten_wires` — flatten almost-orthogonal wire segments
- `sch_resolve_label_overlaps` — flip label justify so text stops colliding
- `sch_normalize_power_orientation` — upright sideways power/ground symbols
- `sch_normalize_text_sizes` — normalise outlier fonts onto the dominant size

### See and verify

- `sch_render_png` — render the sheet so you can visually evaluate it
- `sch_render_visual_diff` — the exact before/after pixel delta of your last
  mutation, plus the list of changed objects
- `run_erc` — the electrical safety net after cosmetic edits

## The loop

Run this loop per sheet until the score meets the target or no fixer applies:

1. **Measure.** Call `sch_cosmetic_score`. If `cosmetic_score` ≥ target, stop —
   the sheet is clean. Otherwise read `worst_category`.
2. **Plan (dry run).** Call the fixer matching `worst_category` with the default
   `apply=false`. Read `connectivity_preserved` and the `changes` list.
   - `grid` → `sch_align_to_grid`
   - `wiring` → `sch_straighten_wires`
   - `readability` (label overlaps) → `sch_resolve_label_overlaps`
   - `orientation` → `sch_normalize_power_orientation`
   - `typography` → `sch_normalize_text_sizes`
3. **Decide.** If `connectivity_preserved` is `false`, do **not** apply — the fix
   would change a net. Report it and hand back to the human (or fix the
   underlying wiring first). If `true`, continue.
4. **Apply.** Call the same fixer with `apply=true`. A `refused` status means the
   invariant caught a connectivity change at commit time — treat it as step 3.
5. **See.** Call `sch_render_png` and evaluate the image against the rubric
   below. Call `sch_render_visual_diff` and confirm the red delta covers only the
   objects you intended to move.
6. **Re-measure.** Call `sch_cosmetic_score` again. Confirm the score rose and no
   new category regressed. Return to step 1.
7. **Guard.** After the loop, run `run_erc` to confirm the cosmetic pass left the
   design electrically intact.

Stop after a full pass where every applicable fixer reports `no_change`, even if
the score is still below target — the remaining gap needs human layout judgment,
not an automated fixer. Report what is left and why.

## Rubric — what "professional" looks like

When you evaluate a `sch_render_png`, check for:

- **Grid** — parts and wires sit on a regular grid; nothing looks hand-nudged.
- **Orthogonal wiring** — wires run horizontally/vertically; no diagonals.
- **Legible labels** — net labels and reference designators do not overlap and
  read cleanly against nearby text.
- **Conventional symbols** — power up, ground down, no sideways power symbols.
- **Consistent typography** — one dominant font size across the sheet.
- **Balanced composition** — content spreads across the sheet rather than
  crowding one corner.
- **Complete title block** — title, revision, date, and company are filled in.

Judge the rendered image, not just the score: the score is a fast proxy, but the
render is the ground truth for readability.

## Guardrails

- Cosmetic ≠ correct. Never sign off electrical behavior from this skill.
- Prefer dry runs first; only apply once `connectivity_preserved` is `true`.
- If a fixer is refused, the underlying net topology needs a human — surface it,
  do not force it.
- End with `run_erc`; a clean cosmetic pass must also be a clean electrical one.
