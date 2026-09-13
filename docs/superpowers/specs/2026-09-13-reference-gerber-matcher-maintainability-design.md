# Reference Gerber Matcher Maintainability Design

## Problem

Sonar rule `python:S8786` reports the Gerber and drill `Created by` metadata regular expressions in `src/kicad_mcp/evals/reference_mcp_server.py` as susceptible to super-linear backtracking. They are used only to recognize whole KiCad-generated Gerber/drill metadata lines before timestamp normalization.

## Requirements

- Preserve the current accepted `Created by` line shapes exactly enough for existing KiCad 10 output: `G04 Created by KiCad (PCBNEW <value>) date <value>*` and `; DRILL file KiCad <value> date <value>`.
- Reject embedded CR/LF and malformed prefix/suffix near-misses that the current full-match regular expressions reject.
- Preserve all non-matching bytes unchanged.
- Do not change `.gbrjob` or drill normalization behavior, the public/MCP surface, manufacturing artifact semantics, or normalization rule version.
- Remove the two `python:S8786` Gerber regex findings rather than suppressing them.

## Design

Replace only the two affected `Created by` regex checks with small bounded byte predicates built from `startswith`, `endswith`, delimiter presence, and CR/LF rejection. Keep the existing normalization output construction unchanged. Add behavior tests for valid lines and near-miss lines plus a source-level maintainability guard preventing the removed regex constants from returning.
