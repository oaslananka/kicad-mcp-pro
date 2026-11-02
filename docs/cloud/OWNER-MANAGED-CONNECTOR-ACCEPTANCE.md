# Owner-managed Cloud Connector: user acceptance contract

Status: **design and acceptance criteria only**. The current one-shot pilot
does **not** satisfy this contract. Do not enable an unreviewed service or
assume this document authorizes new device-key usage.

## The experience

1. Reuse the existing enrolled device and explicitly choose one registered
   project, without another account, OAuth app, or domain.
2. Enable **read-only project presence** once. Thereafter the already-granted
   Cloud MCP client works without terminal commands, one-use codes, or timing
   two separate applications.
3. Status truthfully reports **Off**, **Connecting**, **Connected**, or
   **Unavailable**. A saved permission never counts as live connectivity.
4. Ordinary network interruptions and restart recover automatically while
   enabled, without a new prompt or repeated challenge floods.
5. **Off** stops pending and future reads until deliberately re-enabled.
   Revoking the existing Cloud client/project grant also denies subsequent
   results. A disabled Connector stays disabled after restart.

## Smallest viable technical scope

Reuse the existing device identity, local project registration, Cloud
PostgreSQL sessions, and per-client OAuth project grants. No new account,
domain, identity provider, cross-repository service, paid platform, or
arbitrary remote filesystem access.

- **Local:** owner-controlled enable/off, truthful connection state, stable
  installed package, bounded reconnect. Check current scope before reading
  and again before returning any result. Never load the device signing key
  or start a service before the owner's own activation.
- **Cloud:** separate, initially disabled owner-managed read-only mode.
  Do not reinterpret existing one-shot operator flags, a device signature,
  or a missing independent verifier as unlimited reading authority.
  Recheck the authenticated OAuth client/project grant and exact operation.
- **Transport:** permit serial, bounded requests on an authenticated
  connection, or a bounded renewal model that respects session lifetimes and
  rate limits. User-facing timer prompts are prohibited; ordinary technical
  timeouts and anti-replay restrictions remain.
- **Data:** first deliver only three project-file presence booleans.
  Never send board data, full paths, project content, secrets, or general
  commands. DRC and additional aggregate tools are separate opt-ins.
- **Trust:** the stronger independent owner-verification path remains
  fail-closed. Persistent authorization must be independently reviewed
  as a deliberately chosen, narrowly scoped product mode.

## Acceptance matrix

| Scenario | Required observation |
| --- | --- |
| Fresh install | Off; no key use or outbound session |
| Enable one registered project | One comprehensible action; scope visible |
| Valid granted client requests presence twice | Two real results, no repeated owner challenge |
| Mismatched client/device/project | Denied; no private path disclosure |
| Network disconnect and recovery | Auto-reconnect, no flood or reapproval |
| Restart while enabled | Resumes from stable package at identical scope |
| Turn Off with a pending read | No late result; remains Off on restart |
| Cloud OAuth project grant revoked | In-flight and subsequent read denied |
| Corrupt, symlinked, public local grant | Fail closed before key use |
| Native command or arbitrary path request | Denied |
| Socket offline but permission enabled | Status Unavailable, not Connected |
| Expired technical deadline or replay | Bounded failure, no user countdown |

## Done means real operation

Only ship after exercising the *local and Cloud implementations* in
automated tests, successful reconnection and revocation of a real enrolled
device, and repeatable project-presence responses to an authorized MCP
client against the **current deployed** Cloud. Required exact-head GitHub
checks and SonarCloud must pass. Do not change production or the user's
Claude Always allow setting just to run these tests.
