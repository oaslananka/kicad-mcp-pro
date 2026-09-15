# Licensing transition review

Status: review only — no license change is authorized by this document.

KiCad MCP Pro is currently distributed under the MIT License. This review records the conditions that must be satisfied before the project considers a future source-available/noncommercial or dual-licensing transition.

## Current boundary

- `LICENSE` remains MIT.
- Existing releases, tags, forks, and copies already distributed under MIT keep the rights granted by those MIT terms.
- This review does not attempt to revoke, narrow, or rewrite rights already granted for prior releases.
- No current README, package metadata, release metadata, or source file should claim PolyForm or another restrictive license until a separate approved transition is complete.

## Why this repository needs a rights review

The repository contains merged external human contributions, including work from `peterus` and `nerpatech`.

`CONTRIBUTING.md` currently uses the Developer Certificate of Origin (DCO) 1.1. The DCO documents provenance and a contributor's right to submit work under the project license in effect for the contribution. It is not, by itself, a copyright assignment or a blanket grant for future relicensing under materially different terms.

Therefore a unilateral replacement of the MIT license for contributed code is not treated as safe by this project review.

## Evidence required before any transition

Before changing the project-authored license, the maintainer should complete and retain a reviewable record for all of the following:

1. Identify non-trivial merged contributions whose copyright is not solely held by the maintainer.
2. Distinguish project-authored code from vendored, copied, generated, or third-party material and preserve every applicable third-party license.
3. Obtain explicit contributor permission or another reviewed legal basis for relicensing affected contributed code, or exclude/rework code that cannot be relicensed.
4. Define a prospective release boundary. Previously published MIT versions remain MIT; only a future release can adopt new terms for code the project has the right to relicense.
5. Establish a Contributor License Agreement (CLA) process for future non-trivial external contributions if commercial dual licensing or future relicensing flexibility is required.
6. Review package metadata, documentation, release archives, SBOMs, notices, and distribution artifacts so they all describe the same licensing boundary.

## Candidate future model

If the rights review is completed, the currently preferred commercial-control model is:

- current/future project-authored source under PolyForm Noncommercial 1.0.0;
- commercial use available only under a separate written commercial license; and
- historical MIT releases explicitly preserved under the MIT terms that applied when published.

That model is source-available, not OSI open source. If OSI-approved open source is later prioritized instead, AGPL-3.0 with a separate commercial license is a distinct option, but AGPL does not prohibit commercial use.

## Safe transition sequence

A future implementation PR should not be opened until the rights review is complete. When it is complete, the transition should be implemented on a dedicated branch and should:

1. keep Git history and historical MIT license evidence intact;
2. add the new license text without editing third-party license text;
3. add separate commercial-licensing and contributor-licensing guidance;
4. state the exact release/tag boundary between historical MIT releases and future terms;
5. update package/readme/release metadata consistently; and
6. run the repository's complete release, security, documentation, and packaging validation before merge.

## Non-goals of this review

This document does not grant permission to relicense any contributor's work, does not alter the MIT License, does not create a CLA, and is not a substitute for legal review when contributor rights or third-party obligations are unclear.

Until the evidence above is complete, the repository should continue to present its current code and releases as MIT-licensed.