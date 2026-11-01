# Owner-operated presence pilot

The Cloud service already has a lower-assurance, opt-in presence-only pilot.
It does not require a second OAuth app, domain, WebAuthn issuer, or background
agent. This path sends only the three KiCad project-file presence booleans;
it does not operate on KiCad, read contents or edit files.

Launch manually from the separately approved owner's terminal:

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
