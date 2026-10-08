# Windows desktop and dashboard regression smoke

Scope: the Tauri Windows installer and the Python-backed local dashboard.
This is **not** a claim that Linux tests prove native Windows installer behavior.
Use a clean supported Windows VM for the release smoke and retain the evidence
in the relevant GUI CI/release run.

## Native desktop lifecycle (Windows)

1. Install **one** Windows distribution package (MSI *or* NSIS) in a clean VM.
   Verify the version and publisher identity of that package. If switching
   installer formats, uninstall the previous installation first.
2. Start KiCad MCP Pro. Exactly **one** application-owned system-tray icon
   should appear; the backend should listen only on loopback port 3334.
3. Click the **left** mouse button on the tray icon. The main window should
   become visible and focused, including when previously minimized or closed
   into the tray. Right-click should expose **Show Window** and **Quit**.
4. Launch the same GUI from the Start menu a second time: no new window,
   backend process, or tray icon should survive. The existing window should
   return to the foreground. Quit and restart to verify clean lifecycle.
5. Start an incompatible process on port 3334 and verify fail-closed version
   negotiation (never silently attach or switch backend versions). Check
   error feedback and cleanup without dumping user project files or secrets.

## KiCad CLI detection (Windows)

- With a supported KiCad 10 installation, detect the **existing** executable
  and verify its version; never assume KiCad 11 is present.
- With no KiCad executable installed, show the honest **degraded** state and
  actionable installation/settings hint, rather than a fictional 11.0 path.
- With an explicitly configured but invalid CLI path, show that exact path
  so the user can correct it, without silently overriding the configuration.
- With a supported executable discovered from PATH, prefer the real PATH
  result; do not run guessed binaries or claim native engine success.

## Responsive UI, accessibility and security

- Inspect Dashboard, Logs, Tools, Preview, Settings and Setup at 1200px,
  900px and 390px, including keyboard-only navigation.
- Inject a long Windows CLI path in the health card. Verify it wraps inside
  the card with no overlap, clipping, horizontal scrolling or misleading
  "healthy" status.
- Verify navigation works using mouse, Enter and visible keyboard focus;
  refresh/status/diagnostic links must be functional.
- Preserve loopback-only backend access, exact backend release pinning,
  Tauri CSP boundaries and no extra shell/plugin capabilities.

## Automated evidence and remaining native boundary

- Python discovery and health message regression tests run in the unit suite.
- E2E Playwright checks responsive health-card layout and keyboard navigation.
- GitHub **GUI CI** builds/tests Rust/Tauri on Linux, macOS and **Windows** with
  Cargo locked dependencies. Native installation, Start-menu second launch
  and real Windows tray interaction still require the clean-VM smoke above
  before calling the installer user-verified.
- A GitHub Release that predates these changes is **not** retroactively fixed;
  verify the corrected GUI binary in a subsequently built release.
