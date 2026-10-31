# Independent owner approval — Cloud read trust boundary

**Status (2026-10-31): independent per-read approval NOT implemented or release-authorized.** Local [PR #1513](https://github.com/oaslananka/kicad-mcp-pro/pull/1513) remains DRAFT. Cloud [PR #64](https://github.com/oaslananka/kicad-mcp-pro-cloud/pull/64) merged into Cloud main on 2026-10-30, but production still reports `remoteConnector=not_implemented` and the remote-read feature remains OFF. A source merge is not a deployment or read authorization.

## Reproduced root cause

`test_same_uid_pty_is_not_independent_human_approval` launches a separate same-UID process with a genuine PTY, reads the fresh CLI challenge and replies `APPROVE` automatically. No human, private key or Cloud connection is involved. This shows that the foreground prompt is an *invocation check*, not independent human authentication.

Owner directory mode `0700`, PEM mode `0600` and `O_NOFOLLOW` help defend against filesystem errors and other unprivileged UIDs, **not** a same-UID agent or root escalation. A disposable-file host probe demonstrated that a different unprivileged user could not read the fixture, while a passwordless-sudo-capable process could read it as root. No owner key was touched. A different UID by itself fails when the agent retains sudo, Docker-host access, privileged sockets or access to the owner session/approval endpoint.

## Required trust boundary (before remote-read approval or activation)

1. **Confine automation:** Isolate its principal from owner key, owner project, GUI/browser session, approval endpoint, sudo/root, container-admin groups and privileged IPC. Verify the *actual* host and loopback privileges, not just UID names. Do not change current host sudoers, users or services as part of this DRAFT.
2. **Independent owner authenticator:** Use a trusted user-verifying device/channel whose signing key the agent cannot access, ideally hardware-backed on a separately controlled device. Device-transport Ed25519 signing keys are *not* owner-consent keys. Neither a PTY response, a reusable browser cookie nor a service listening only on localhost suffices.
3. **Single-use exact authorization:** Cloud originates a high-entropy challenge tied to the trusted origin, owner, OAuth client, device, project, single `project_summary` operation, request ID and short expiry. The human sees the exact intended operation. The assertion signs those exact challenge bytes; Cloud, not a CLI flag, determines the trusted owner public key.
4. **Server-side verification:** Before dispatch, independently verify signer/user verification, origin and grant bindings, OAuth token, device and project state. Atomically mark the one-shot challenge consumed, denying replay/concurrency. Re-check token, grant, revocation and deadline before returning the three presence booleans.
5. **Fail closed:** If the independent approval service, credential, valid nonce or per-read proof is missing, deny. No fallback to terminal approval, owner-only filesystem permissions, device signature, automatic OAuth browser action or reusable token.
6. **Real isolated acceptance:** Test an actual trusted owner authenticator, separate restricted agent, genuine OAuth consent, TLS/WS, revocation and release qualification. Existing synthetic test fixtures do not establish human presence or production readiness.

## Negative cases (must never release presence data)

| Threat | Acceptance condition |
| --- | --- |
| Agent-owned PTY types the challenge | Does not grant a Cloud read |
| Same-UID agent reads owner `0600` key | Device proof cannot substitute for owner assertion |
| Agent UID separated but retains sudo/Docker/host socket | Reject environment as privileged |
| Agent calls localhost approval endpoint | No approval without separate owner verification |
| Assertion for another owner/client/device/project/origin/operation | Deny before dispatch |
| Replayed, concurrent or expired challenge | No additional read |
| Revoke token/grant/device during read | No project-presence response |
| Owner channel unavailable or browser consent abandoned | Deny without fallback |
| Windows path cannot guarantee no-follow semantics | Deny; do not downgrade |
| Genuine owner authorizes one valid isolated read | One result, three booleans only; no path/content/native KiCad operation |

## Delivery order

Prove actual non-admin agent confinement and inaccessible localhost/IPC first. Implement independent owner-key enrollment and per-read server challenge verification second. Then add cross-principal, replay, race, mismatch, revocation and real owner OAuth/TLS acceptance evidence. The nine PR #1513 Sonar `pythonsecurity:S8707` issues are now **CLOSED/FIXED** in the 2026-10-31 public analyzer result, with Quality Gate OK; this fixes analyzer findings, **not** the independent human-authorization requirement. Never suppress or bypass the scanner gate. Require separate release/deployment authorization.

No email, external support request, additional device enrollment, credential disclosure or production configuration change is authorized by a generic “continue.”
