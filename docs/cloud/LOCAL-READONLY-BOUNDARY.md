# KiCad Cloud — owner-controlled local project summary (pre-production)

**Status: paired implementation remains DRAFT and production pairing OFF.** The
local client is [KiCad MCP Pro PR #1513](https://github.com/oaslananka/kicad-mcp-pro/pull/1513)
and the signed approval-state API is
[KiCad Cloud PR #75](https://github.com/oaslananka/kicad-mcp-pro-cloud/pull/75).
Earlier Cloud infrastructure PR #64 and browser UX PR #73 have merged, but
production reports `remoteConnector=not_implemented` and both pairing and
connector feature flags remain OFF. Do not merge or enable these features
without independent security review and genuine owner acceptance.

## What works in an approved isolated environment

The local operator can explicitly invoke two commands:

- `python -m kicad_mcp.cloud_pair --begin-pairing` creates or safely reuses an
  owner-only Ed25519 key. It initiates a device challenge over verified HTTPS,
  displays the short user code and challenge UUID, and **waits for an actual
  signed-in owner to approve it in the Cloud browser**. Only after this
  confirmation does it sign the one-use device proof and redeem the challenge.
  The resulting device is **enrolled but disabled**. No private-key bytes are
  uploaded. The local key directory must exist, be owned by the same POSIX
  user, have no symlink substitution and forbid group/other access.
- `python -m kicad_mcp.cloud_once --allow-once` opens an authenticated
  HTTPS/WSS session with an already enrolled and explicitly enabled device
  and independently chosen local KiCad project. It permits **one** owner-approved
  `project_summary` presence-only read, with a 30-second local lease; it
  closes the session on completion or denial. It does not start automatically
  or require the existing local KiCad MCP service to be restarted.

The Cloud's actual OAuth JWT verifier and PostgreSQL gates require a
`projects:read` client consent, an enabled unrevoked owner device, an enabled
owner project and a separate per-client `readonly` project grant. The
Cloud browser `/devices` page exposes device activation, metadata-only
project registration (opaque UUID, alias, no local path), owner subject and
the **explicit project-to-OAuth-client grant/revoke form**. The existing
`/connections` page lists clients with OAuth consent and supports revoke.
Browser mutations use same-origin, owner/session/action-specific signed CSRF;
a revoked key cannot be reactivated and a revoked client needs **fresh**
consent after its cutoff to receive another grant.

## Reproducible manual workflow (isolated test deployment only)

The Cloud instance must be independently provisioned with **only the reviewed
database migrations, built-in OAuth identity, valid HTTPS/WSS ingress and
trusted device source**. Do not use production credentials, flags or shared
proxy settings to make a test pass. The instructions below are for a
separately approved, isolated Cloud test environment with these features
already enabled; they will fail closed against current production.

On a POSIX workstation with this checkout and `uv`:

```sh
# Private key stays on this workstation. Do not commit, upload or echo it.
umask 077
KEY_DIR="$HOME/.local/share/kicad-mcp-cloud"
install -d -m 0700 "$KEY_DIR" "$KEY_DIR/keys" "$KEY_DIR/projects"

# Set the independently verified HTTPS origin of the ISOLATED Cloud.
CLOUD_ORIGIN="https://cloud-test.example.invalid"

uv run --all-extras python -m kicad_mcp.cloud_pair \
  --cloud-origin "$CLOUD_ORIGIN" \
  --alias "My test workstation" \
  --begin-pairing
```

In a browser **signed in as the intended owner of that isolated Cloud**,
inspect the first-party device approval page opened by the client. Verify
that its short code matches the one in the terminal, and explicitly select
**Approve device** before the five-minute challenge expires. **Before showing
the owner the browser page**, the client must first verify that the separate
Ed25519-signed, read-only status endpoint works and that the fresh challenge
is still pending. If that endpoint is unavailable (for example, the deployed
Cloud version is too old), no approval page is opened and the attempt fails
closed without wasting a human click. After the browser is shown, the client
polls no faster than once every eight seconds and automatically attempts one
separately signed redemption only after actual owner approval.
**No terminal Enter is required.** If the owner denies approval or the deadline
expires, enrollment fails closed. The command still requires stdin and stdout attached
to a real foreground terminal; redirected or piped invocation is rejected
before key creation or issuing a challenge. An agent-owned PTY under the same
OS user is not independent human approval.
Save the printed `deviceId` and `Local key slot` UUID as non-secret
identifiers. A fresh owner-only key is created at the fixed application path
`~/.local/share/kicad-mcp-cloud/keys/<keySlot>.pem`; neither the LLM nor
the pairing command can choose a filesystem pathname. Never disclose the key
contents. Do not interpret enrollment as device activation.

In the Cloud browser `/devices`, explicitly enable the newly enrolled
device and register one read-only test project. Note its `projectId` and
your displayed `ownerSub`. Separately consent to an authorized AI client
with `projects:read` and explicitly grant *that client* `readonly` access
to *that project*. No Cloud action selects a local directory.

For this DRAFT, **there is no automatic, agent-trusted profile issuer**:
before any read, the human operator must independently provision a local
private record at the fixed path
`~/.local/share/kicad-mcp-cloud/projects/<projectId>.json`
(mode `0600`, under a mode `0700`, owner-owned `projects` directory).
Its **exact seven string keys** are `ownerSub`, `cloudOrigin`, `deviceId`,
`projectId`, `keySlot`, `directory` and `filenameStem`.
For example, with *synthetic placeholders* rather than credentials:

```json
{
  "ownerSub": "owner-from-cloud",
  "cloudOrigin": "https://cloud-test.example.invalid",
  "deviceId": "11111111-1111-4111-8111-111111111111",
  "projectId": "22222222-2222-4222-8222-222222222222",
  "keySlot": "33333333-3333-4333-8333-333333333333",
  "directory": "/absolute/path/to/owner-selected/test-project",
  "filenameStem": "test-project"
}
```

The owner must manually replace the placeholders and protect the record;
the project directory must exist, be absolute and contain no symlink
ancestors. A missing, malformed, group-accessible, linked or
cross-owner/device/project/origin record denies the read. This manual
record is **not** independent human authorization: a same-UID or sudo-capable
agent can still modify it. Do not enable production with this DRAFT.

The one-shot read CLI now accepts **identifiers only**, never the project
directory, filename stem or PEM path:

```sh
uv run --all-extras python -m kicad_mcp.cloud_once \
  --cloud-origin "$CLOUD_ORIGIN" \
  --owner-sub "<ownerSub from Cloud /devices>" \
  --device-id "<deviceId from successful pairing>" \
  --project-id "<projectId registered in Cloud>" \
  --allow-once
```

There is no legacy CLI path fallback. Old path arguments fail at parsing.
The command reads the owner-private project record, selects its validated
`keySlot` under the fixed private key directory, and continues only if the
existing owner-binding fingerprint, origin, device, session and consent
checks pass. An AI-supplied project UUID is never sufficient by itself.

For the minimal presence-only pilot, the separately authorized AI client
invokes the Cloud MCP tool `get_project_presence(project_id)` while the
one-shot local session is active. Cloud derives the owner, OAuth client and
device from the verified bearer and existing project grant; it does not
accept caller-supplied local paths or device identity. The older
`POST /api/v1/connector/project-summary` two-step review route belongs
to the separate higher-assurance owner-consent flow, not this pilot.

Never paste the bearer token into logs, shell history, PR comments or
documentation. The Cloud checks token/grant/session state before dispatch
and again before the response. The only returned data are
`projectPresent`, `boardPresent` and `schematicPresent` booleans;
no local filename, project contents or private key leave the device.
Denied or unavailable reads reveal no private project data.

## Security boundary and evidence

- All local file checks are on the **owner-selected direct child** of an
  absolute folder, using POSIX descriptor-relative no-follow metadata
  access. Symlinks, multiply hard-linked KiCad project files and unsupported
  Windows-native handle semantics **fail closed**; Windows support requires
  its own independently reviewed handle/reparse-point implementation.
  The metadata-only scan rejects project files with `st_nlink != 1`, so a
  regular file linked from outside the owner-selected folder cannot masquerade
  as an approved project child. This does not defend against same-UID/root
  access, malicious mounting, or missing independent owner authentication.
- Owner PEM and pairing sidecar reads use pinned no-follow descriptor
  access with nonblocking opens: substituting a FIFO for either
  basename cannot hang the CLI before the regular-file/owner/mode
  checks. The two negative thread-bounded tests fail closed without any
  network or production access.
- Ed25519 device/session signatures use domain-separated Cloud v1 bytes.
  The local client checks hostname and CA before signing; compressed
  WebSocket frames and alternate origins/paths are rejected. Both the HTTPS
  pairing client and signed WSS connector reject origins with an empty
  query/fragment delimiter (`?` or `#`) before use; otherwise the appended
  WebSocket endpoint path would become a query or fragment. Enrollment also
  rejects DNS names ending in a dot, which the WSS connector forbids. Both
  entry points reject raw control/whitespace characters and non-ASCII origin
  spellings before URL parsing, including CR/LF/tab that Python's URL parser
  would silently remove and could otherwise alter the WebSocket request path.
  These mismatches were reproduced as failing tests before correction. Pairing
  requests use verified HTTPS, bounded response size, **no redirects or
  automatic retries**. Owner keys use exclusive creation and mode 0600.
  When reopening an owner key or its origin/device-binding sidecar, the client
  also requires exactly one hard-link reference (`st_nlink == 1`) on the
  pinned, no-follow regular-file descriptor. Hard-linked aliases are denied
  even when both names are same-owner mode 0600; this does **not** provide
  independent owner authentication against a same-UID/admin-capable agent.
- Only `project_summary` is accepted. Native KiCad execution, DRC/ERC,
  PCB mutation, manufacturing/export, local path discovery and arbitrary
  file reads are all denied. There is no background worker, persistent
  online connection or unattended reconnect.
- Real Cloud TypeScript handlers, PostgreSQL 17 migrations, JWT cryptographic
  verifier and Python TLS/Ed25519 one-shot reader have passed a **combined
  isolated cross-language acceptance** using synthetic owner/client/project
  identities and an isolated KiCad file-presence fixture. Cloud owner
  activation/grant/revocation tests have separately passed against a
  disposable PostgreSQL 17 database. These tests do **not** establish
  production owner OAuth login, approval of real project files or live
  end-to-end device provisioning.
- `tests/cloud/test_enrollment_one_shot_integration.py` additionally
  bridges the **actual local** enrollment implementation to the one-shot
  CLI with the **same generated Ed25519 key and persisted origin/device
  binding**. It verifies a synthetic owner challenge/redeem signature,
  strict private metadata, one direct-child project-presence summary,
  and rejection of a second read. The browser approval and network
  transport are **synthetic fixtures**; this is **not** a production Cloud,
  real browser OAuth, or real-owner acceptance test.
- `tests/cloud/test_enrollment_real_wss_integration.py` exercises the
  **actual persisted browser-paired Ed25519 identity** through verified
  localhost HTTPS-origin to a **real temporary CA-signed TLS WebSocket**
  peer, checking both device/session challenge signatures and a single
  `connector.read_result`/ACK with only three presence booleans. It uses
  synthetic pairing HTTP responses and synthetic browser approval, plus a
  disposable local KiCad file-presence fixture. Unlike the previous
  local-only transport stub, the actual outbound WSS client and read
  dispatcher execute; unlike a real owner acceptance, it exercises **no
  signed-in OAuth user, production Cloud server, or production data**.
- The 30-second local owner authorization window starts **immediately after
  the foreground confirmation**, not when the Cloud TLS/WebSocket proof
  finishes. Immutable wall-clock and monotonic deadlines are passed to the
  connect path and checked before key use, again at handshake completion,
  and for each one-time read. Delayed handshakes cannot renew consent.
- The **real temporary localhost TLS/WSS** owner-enrollment integration
  fixture now also simulates that 30-second expiration *between* verified
  device/session Ed25519 proofs and the Cloud `connector.ready` frame. It
  asserts the local client denies the exchange and closes its socket
  **before any `connector.read_result`**, while the successful single-summary
  and read-ACK scenario remains green. This is a synthetic test clock and
  synthetic owner browser, **not** actual OAuth acceptance.

- The one-shot transport additionally revalidates the **actual original
  authorized read frame** after the metadata inspection worker finishes
  and before it sends `connector.read_result` over WSS. The current local
  grant/consent, request deadline, device/session identity and inspected
  request ID must still match. A regression with real temporary localhost
  TLS/WebSocket advances the consent clock **after the worker returns**,
  confirming no metadata response leaves the client; a separate
  dispatcher test checks a revoked grant and expired signed deadline.
  The send remains asynchronous, so independent Cloud-side delivery
  authorization and revocation checks are required.
- **Independent-human-consent risk confirmed, not remediated:**
  `test_same_uid_pty_is_not_independent_human_approval` launches a real
  separate same-UID process under a synthetic POSIX PTY. Without monkeypatching
  the terminal check, reading any owner key, or contacting Cloud, that process
  answers the fresh challenge and the local confirmation succeeds. This is a
  **threat-characterization test of the current unsafe trust assumption**,
  not a negative security gate and not evidence of authorized owner consent.
  The 0600 key and interactive prompt cannot protect against unrestricted
  same-UID automation; browser OAuth/project grants are separate server-side
  protections and were not attacked by this probe.

  A production-ready boundary requires an **independently authenticated owner**
  approving the exact Cloud origin, device, project, operation and one-shot
  expiry through a trusted channel that an agent cannot drive with a PTY,
  same-UID shell, localhost requests or reusable credentials. Run the agent
  in a separately confined principal without owner key/project access,
  privilege escalation or access to the owner-approval endpoint; prove these
  exclusions with actual negative cross-principal/loopback tests. A separate
  UID by itself is insufficient when it retains admin or container-host
  privileges. No such boundary is implemented in this DRAFT.
- The local `tests/cloud/` suite is included in the full Python CI runner.
  For proportionate local validation, run
  `uv run --all-extras pytest -q tests/cloud/` and check the latest exact
  PR-head CI, coverage, security and supported-platform gates. Do not
  dismiss alerts to bypass a failing gate.

For the independent owner-authentication trust model, privileged-agent
preconditions and negative acceptance cases, see
[Owner consent boundary acceptance](OWNER-CONSENT-BOUNDARY-ACCEPTANCE.md).
This is a design, not a completed owner-authentication implementation.

**Release blockers:** verified real-owner login/consent and device enrollment
in a privately approved isolated environment, review of trusted TLS ingress
and device-source rules, revocation during an actual local read, both PRs'
exact-head CI/security acceptance, and separate explicit production approval.
Until then, both PRs remain DRAFT and production flags remain OFF.
