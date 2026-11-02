# Owner-operated presence pilot

The Cloud service already has a lower-assurance, opt-in presence-only pilot.
It does not require a second OAuth app, domain, WebAuthn issuer, or background
agent. This path sends only the three KiCad project-file presence booleans;
it does not operate on KiCad, read contents or edit files.

Launch manually from the separately approved owner's terminal. If there is
**exactly one** previously registered project, use the simpler command from
an installed version of this repository:

    python -m kicad_mcp.cloud_registered_pilot

Optional, separately owner-approved one-shot inspection modes:

    python -m kicad_mcp.cloud_registered_pilot --mode inspection
    python -m kicad_mcp.cloud_registered_pilot --mode board-counts
    python -m kicad_mcp.cloud_registered_pilot --mode schematic-counts
    python -m kicad_mcp.cloud_registered_pilot --mode native-drc

This launcher survives machine restarts because it lives in the installed
Python package, not under temporary `/run/user` storage. It uses the
preexisting private registration and rejects missing, ambiguous, symlinked
or incorrectly permissioned registrations. The existing operator CLI still
performs the **same fresh terminal approval** before any owner key use or
Cloud connection; these convenience commands are NOT unattended operation
and do NOT create a persistent Connector session. Native DRC requires its
own explicit approval text and uses the original read-only temporary-copy
boundary. If the project is not already registered, do not auto-enroll it.

The original explicit-selector form remains available:

    python -m kicad_mcp.cloud_operator_pilot --cloud-origin https://CLOUD-ORIGIN --owner-sub OWNER --device-id ENROLLED-DEVICE-UUID --project-id REGISTERED-PROJECT-UUID --allow-once

Prerequisites: existing owner-pinned device key and local registry; manual
one-time terminal consent; active verified Cloud OAuth client/project grant;
trusted device WSS ingress; Cloud's operator, pairing and WSS pilot flags.
This program does not enable flags, register devices or start automatically.

This mode is weaker than physical WebAuthn verification: a same-UID agent
can spoof a PTY confirmation. Never use it for unattended agents, remote
KiCad tools, file contents or public access. The separate cloud_once path
retains its independent WebAuthn hard stop. A real owner-controlled physical
pair/read/revoke test is still required before any production pilot.
