"""Embedded SPA dashboard HTML for KiCad MCP Pro.

Single-file single-page application with hash-routed views:
- #dashboard - Server status, health, quick actions
- #log-viewer - SSE live log viewer with filter/clear
- #tools-catalog - MCP tools browser with search
- #preview - Schematic live render gallery
- #settings - Config viewer/editor
- #setup-wizard - 5-step setup wizard
"""

from .. import __version__

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KiCad MCP Pro Dashboard</title>
<style>
  :root {
    --bg-canvas: #0b0f17;
    --bg: #0b0f17;
    --surface: #131926;
    --surface-2: #1a2336;
    --surface-hover: #222d42;
    --surface-active: #28354f;
    --border: #232d3f;
    --border-strong: #334155;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
    --text-dim: #64748b;
    --accent: #38bdf8;
    --accent-hover: #7dd3fc;
    --accent-subtle: rgba(56, 189, 248, 0.12);
    --success: #22c55e;
    --success-subtle: rgba(34, 197, 94, 0.12);
    --warning: #f59e0b;
    --warning-subtle: rgba(245, 158, 11, 0.12);
    --error: #ef4444;
    --error-subtle: rgba(239, 68, 68, 0.12);
    --info: #38bdf8;
    --sidebar-w: 230px;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --font-sans: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Consolas, monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  ::selection { background: rgba(56, 189, 248, 0.32); color: #ffffff; }
  body {
    font-family: var(--font-sans);
    background: var(--bg-canvas); color: var(--text); min-height: 100vh;
    display: flex; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased;
  }
  a { color: var(--accent); text-decoration: none; transition: color 0.15s ease; }
  a:hover { color: var(--accent-hover); text-decoration: underline; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  * { scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
  *::-webkit-scrollbar { width: 6px; height: 6px; }
  *::-webkit-scrollbar-track { background: transparent; }
  *::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
  *::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

  /* Sidebar */
  .sidebar {
    width: var(--sidebar-w); background: var(--surface);
    border-right: 1px solid var(--border); padding: 18px 0;
    display: flex; flex-direction: column; flex-shrink: 0;
  }
  .sidebar .brand {
    padding: 0 16px 14px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 10px; margin-bottom: 10px;
  }
  .sidebar .brand-icon {
    width: 28px; height: 28px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    border-radius: var(--radius-sm); background: var(--accent-subtle);
    border: 1px solid rgba(56, 189, 248, 0.25);
  }
  .sidebar .brand-icon svg { width: 18px; height: 18px; }
  .sidebar .brand-title { display: flex; flex-direction: column; gap: 2px; }
  .sidebar .brand h1 { font-size: 14px; font-weight: 700; letter-spacing: -0.01em; color: var(--text); }
  .sidebar .brand .badge {
    align-self: flex-start; font-size: 10px; padding: 1px 6px; border-radius: 10px;
    background: var(--accent-subtle); color: var(--accent); border: 1px solid rgba(56, 189, 248, 0.3);
    font-weight: 600; font-family: var(--font-mono);
  }
  .sidebar .status-row {
    padding: 6px 16px 12px; font-size: 12px; color: var(--text-muted);
    display: flex; align-items: center; gap: 8px; border-bottom: 1px solid var(--border);
    margin-bottom: 10px;
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0;
    box-shadow: 0 0 0 2px var(--surface);
  }
  .status-dot.ok { background: var(--success); box-shadow: 0 0 8px rgba(34, 197, 94, 0.4); }
  .status-dot.degraded { background: var(--warning); box-shadow: 0 0 8px rgba(245, 158, 11, 0.4); }
  .status-dot.error { background: var(--error); box-shadow: 0 0 8px rgba(239, 68, 68, 0.4); }

  .nav-items-container { display: flex; flex-direction: column; width: 100%; }
  .nav-item {
    display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
    padding: 9px 16px; font: inherit; font-size: 13px; cursor: pointer;
    color: var(--text-muted); background: transparent;
    transition: all 0.15s ease; border: 0; border-left: 3px solid transparent;
  }
  .nav-item svg {
    width: 16px; height: 16px; flex-shrink: 0; stroke: currentColor; fill: none;
    stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
  }
  .nav-item:hover { background: var(--surface-hover); color: var(--text); }
  .nav-item.active {
    background: var(--surface-2); color: var(--accent);
    border-left-color: var(--accent); font-weight: 600;
  }
  a.nav-item { text-decoration: none; }
  a.nav-item:hover { text-decoration: none; }
  .nav-sep { height: 1px; background: var(--border); margin: 10px 14px; }
  .nav-label {
    padding: 6px 16px 4px; font-size: 10px; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-dim); font-weight: 700;
  }
  .nav-support-group { margin-top: auto; padding-top: 10px; }
  .nav-support {
    margin: 4px 12px; padding: 7px 11px; border: 1px solid var(--border);
    border-radius: var(--radius-sm); color: var(--text); font-weight: 600; font-size: 12px;
    display: flex; align-items: center; gap: 8px; transition: transform 0.15s ease, background 0.15s ease;
  }
  .nav-support:hover { text-decoration: none; transform: translateY(-1px); }
  .nav-support.github { border-color: rgba(255, 140, 207, 0.35); color: #ff8ccf; background: rgba(255, 140, 207, 0.08); }
  .nav-support.github:hover { background: rgba(255, 140, 207, 0.16); }
  .nav-support.coffee { border-color: #d1b700; color: #171717; background: #ffdd00; }
  .nav-support.coffee:hover { background: #ffe433; }

  .local-workspace-intro { padding: 26px 27px 20px; margin-bottom: 25px; border: 1px solid rgba(56,189,248,.23); border-radius: 12px; background: radial-gradient(ellipse 67% 90% at 12% 2%,rgba(56,189,248,.08),transparent),var(--surface); }
  .local-workspace-kicker { display: block; margin-bottom: 8px; color:var(--accent);font-size:10px;font-weight:700;letter-spacing:.11em; }
  .local-workspace-intro h2 { font-size:clamp(22px,2.2vw,30px);margin-bottom:9px;letter-spacing:-.035em; }
  .local-workspace-intro p { font-size:13px;line-height:1.6;color:var(--text-muted);max-width:750px; }
  .local-workspace-actions { display:flex;gap:10px;flex-wrap:wrap;margin:17px 0 13px; }
  .local-workspace-actions .btn { margin-top:0;min-height:41px;padding:10px 15px;font-size:13px; }
  .local-workspace-actions .local-cloud-link { background:var(--surface-2);border:1px solid var(--border-strong);color:var(--text); }
  .local-workspace-actions .local-cloud-link:hover { background:var(--surface-hover); }
  .local-workspace-intro .local-workspace-safety { margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:11px; }
  @media (max-width:480px) { .local-workspace-intro{padding:20px 17px}.local-workspace-actions .btn{flex:1 1 100%;} }

  /* Main content */
  .main { flex: 1; min-width: 0; padding: 32px 36px; overflow-y: auto; max-height: 100vh; }
  .view { display: none; }
  .view.active { display: block; animation: fadeIn 0.2s ease-out; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: translateY(0); } }
  .view h2 {
    font-size: 18px; font-weight: 700; margin-bottom: 20px; letter-spacing: -0.01em; color: var(--text);
  }

  /* Cards & Grid */
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px; margin-bottom: 20px;
  }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-md); padding: 20px; min-width: 0;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .card:hover { border-color: var(--border-strong); }
  .card h3 {
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    color: var(--text-dim); margin-bottom: 12px; letter-spacing: 0.06em;
  }
  .card .row {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 12px; padding: 7px 0; font-size: 13px; line-height: 1.5; border-bottom: 1px solid rgba(255,255,255,0.03);
  }
  .card .row:last-child { border-bottom: none; }
  .card .row .label { color: var(--text-muted); flex-shrink: 0; }
  .card .row .value {
    font-weight: 500; min-width: 0; overflow-wrap: anywhere; text-align: right;
    font-family: var(--font-mono); font-size: 12px; color: var(--text);
  }
  #health-checks .row { display: block; padding: 10px 0; }
  #health-checks .row + .row { border-top: 1px solid var(--border); }
  #health-checks .row .label {
    display: block; margin-bottom: 5px; font-size: 11px; letter-spacing: 0.02em; font-family: var(--font-sans); font-weight: 600;
  }
  #health-checks .row .value {
    display: block; text-align: left; font-size: 12px; line-height: 1.6;
  }
  .card .row .value.ok, .badge-status.ok { color: var(--success); }
  .card .row .value.warn, .badge-status.warn { color: var(--warning); }
  .card .row .value.err, .badge-status.err { color: var(--error); }

  /* Buttons */
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    background: var(--surface-2); border: 1px solid var(--border-strong);
    color: var(--text); padding: 7px 14px; border-radius: var(--radius-sm);
    cursor: pointer; font-size: 13px; font-weight: 500; line-height: 1.4;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.1s ease;
  }
  .btn:hover { background: var(--surface-hover); border-color: var(--accent); color: var(--text); }
  .btn:active { transform: translateY(1px); }
  .btn-primary {
    background: var(--accent); border-color: var(--accent); color: #0b0f17; font-weight: 600;
  }
  .btn-primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); color: #0b0f17; }
  .btn-danger { background: var(--error-subtle); border-color: var(--error); color: #fca5a5; }
  .btn-danger:hover { background: var(--error); color: #fff; }
  .btn-success { background: var(--success); border-color: var(--success); color: #0b0f17; font-weight: 600; }
  .btn-success:hover { background: #4ade80; border-color: #4ade80; color: #0b0f17; }
  .btn-sm { padding: 5px 12px; font-size: 12px; min-height: 32px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }

  /* Forms */
  label { display: block; font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }
  input, textarea, select {
    width: 100%; padding: 8px 12px; background: var(--bg-canvas);
    border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text); font-size: 13px; font-family: inherit;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  input:focus-visible, textarea:focus-visible, select:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent);
  }
  textarea { font-family: var(--font-mono); font-size: 12px; }
  .form-group { margin-bottom: 16px; }
  .form-row { display: flex; gap: 14px; }
  .form-row .form-group { flex: 1; }

  /* Log viewer */
  .log-section { margin-top: 10px; }
  .log-controls { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
  .log-controls button {
    background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted);
    padding: 5px 12px; border-radius: var(--radius-sm); cursor: pointer; font-size: 12px; font-weight: 500;
    transition: all 0.12s ease; min-height: 32px;
  }
  .log-controls button:hover { background: var(--surface-hover); color: var(--text); border-color: var(--border-strong); }
  .log-controls button.active {
    background: var(--accent); color: #0b0f17; border-color: var(--accent); font-weight: 600;
  }
  .live-badge {
    color: var(--success); font-size: 12px; font-weight: 600; margin-left: auto;
    display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
    background: var(--success-subtle); border: 1px solid rgba(34, 197, 94, 0.25); border-radius: 12px;
  }
  .live-badge::before {
    content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--success);
    box-shadow: 0 0 6px var(--success);
  }
  .recent-list { display: grid; gap: 6px; }
  .recent-call {
    display: grid; grid-template-columns: 82px 1fr 70px 70px; gap: 10px;
    align-items: center; font-size: 12px; padding: 8px 10px; border-radius: var(--radius-sm);
    background: var(--bg-canvas); border: 1px solid var(--border); font-family: var(--font-mono);
  }
  .recent-call .ok { color: var(--success); font-weight: 600; }
  .recent-call .error { color: var(--error); font-weight: 600; }
  #log-container {
    background: #06090e; border: 1px solid var(--border); border-radius: var(--radius-md);
    height: 480px; overflow-y: auto; font-family: var(--font-mono);
    font-size: 12px; padding: 14px; line-height: 1.6;
  }
  #log-container .line {
    padding: 4px 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; cursor: pointer;
    transition: background 0.1s ease;
  }
  #log-container .line:hover { background: rgba(255,255,255,0.04); }
  #log-container .line.hidden { display: none; }
  #log-container .line .detail {
    display: none; color: var(--text-muted); padding: 8px 0 8px 24px;
    border-left: 2px solid var(--border-strong); margin: 4px 0 4px 10px;
  }
  #log-container .line.expanded .detail { display: block; }
  #log-container .line.debug { color: var(--text-dim); }
  #log-container .line.info { color: #7dd3fc; }
  #log-container .line.warning { color: var(--warning); }
  #log-container .line.error { color: var(--error); }
  #log-container .line.critical { color: #f87171; font-weight: bold; }

  /* Tools catalog */
  .tool-search { margin-bottom: 14px; }
  .tool-layout {
    display: grid; grid-template-columns: minmax(320px, 1.1fr) minmax(320px, 0.9fr);
    gap: 16px; align-items: start;
  }
  .tool-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }
  .tool-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-md); padding: 16px; cursor: pointer;
    transition: border-color 0.15s ease, transform 0.1s ease, box-shadow 0.15s ease;
  }
  .tool-card:hover { border-color: var(--border-strong); transform: translateY(-1px); }
  .tool-card.selected { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); background: var(--surface-2); }
  .tool-card h4 { font-size: 13px; font-family: var(--font-mono); margin-bottom: 6px; color: var(--text); }
  .tool-card .tool-desc { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; line-height: 1.5; }
  .tool-card .tool-meta { font-size: 11px; color: var(--text-dim); display: flex; gap: 8px; flex-wrap: wrap; }
  .tool-badge {
    padding: 2px 7px; border-radius: 4px; background: var(--bg-canvas);
    border: 1px solid var(--border); color: var(--accent); font-weight: 500;
  }
  .tool-card .tool-params {
    margin-top: 10px; font-size: 11px; background: var(--bg-canvas);
    padding: 8px 10px; border-radius: var(--radius-sm); max-height: 120px; overflow-y: auto;
    border: 1px solid rgba(255,255,255,0.04);
  }
  .tool-card .tool-params code { color: var(--accent); font-family: var(--font-mono); font-weight: 600; }
  .tool-detail { position: sticky; top: 16px; }
  .tool-detail pre {
    background: var(--bg-canvas); border: 1px solid var(--border); border-radius: var(--radius-sm);
    padding: 12px; font-size: 11px; font-family: var(--font-mono); overflow: auto; max-height: 280px;
    color: #e2e8f0; line-height: 1.5;
  }
  @media (max-width: 960px) {
    .tool-layout { grid-template-columns: 1fr; }
    .tool-detail { position: static; }
  }

  /* Setup wizard */
  .wizard-steps {
    display: flex; gap: 0; margin-bottom: 28px;
    border-bottom: 1px solid var(--border); padding-bottom: 16px; position: relative;
  }
  .wizard-step {
    flex: 1; text-align: center; font-size: 12px; color: var(--text-muted);
    padding: 8px 4px; position: relative;
  }
  .wizard-step .step-num {
    display: inline-flex; width: 26px; height: 26px; border-radius: 50%;
    background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted);
    align-items: center; justify-content: center; font-size: 11px; font-weight: 700; margin-bottom: 6px;
    transition: all 0.2s ease;
  }
  .wizard-step.active .step-num {
    background: var(--accent); color: #0b0f17; border-color: var(--accent);
    box-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
  }
  .wizard-step.completed .step-num {
    background: var(--success); color: #0b0f17; border-color: var(--success);
  }
  .wizard-step.active { color: var(--text); font-weight: 600; }
  .wizard-step.completed { color: var(--success); font-weight: 500; }
  .wizard-body { min-height: 220px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 24px; }
  .wizard-nav { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }
  .wizard-result {
    background: var(--bg-canvas); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 14px; margin-top: 14px;
    font-size: 12px; white-space: pre-wrap; max-height: 240px; overflow-y: auto;
    font-family: var(--font-mono); line-height: 1.55;
  }
  .wizard-result.success { border-color: var(--success); color: var(--success); background: var(--success-subtle); }
  .wizard-result.error { border-color: var(--error); color: var(--error); background: var(--error-subtle); }

  /* Messages */
  .msg {
    padding: 10px 14px; border-radius: var(--radius-sm); margin-bottom: 12px;
    font-size: 13px; line-height: 1.5; display: flex; align-items: center; gap: 8px;
  }
  .msg.info { background: var(--accent-subtle); border: 1px solid rgba(56,189,248,0.3); color: var(--text); }
  .msg.success { background: var(--success-subtle); border: 1px solid rgba(34,197,94,0.3); color: var(--text); }
  .msg.warn { background: var(--warning-subtle); border: 1px solid rgba(245,158,11,0.3); color: var(--text); }
  .msg.error { background: var(--error-subtle); border: 1px solid rgba(239,68,68,0.3); color: var(--text); }

  /* Spinner */
  .spinner {
    display: inline-block; width: 18px; height: 18px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { text-align: center; padding: 48px; color: var(--text-muted); font-size: 13px; }

  /* Reduced Motion */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }

  /* Responsive Mobile / Tablet Layout */
  @media (max-width: 768px) {
    body { flex-direction: column; }
    .sidebar {
      width: 100%; padding: 12px 14px 8px; border-right: none;
      border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100;
      background: rgba(19, 25, 38, 0.96); backdrop-filter: blur(10px);
    }
    .sidebar .brand { border-bottom: none; margin-bottom: 6px; padding: 0; justify-content: space-between; }
    .sidebar .status-row { display: none; }
    .nav-items-container {
      display: flex; flex-direction: row; gap: 6px; overflow-x: auto;
      width: 100%; padding: 4px 0; -webkit-overflow-scrolling: touch;
    }
    .nav-items-container::-webkit-scrollbar { display: none; }
    .nav-item {
      padding: 7px 12px; border-left: none; border-bottom: 2px solid transparent;
      border-radius: var(--radius-sm); white-space: nowrap; flex-shrink: 0; width: auto; font-size: 12px;
    }
    .nav-item.active { border-left-color: transparent; border-bottom-color: var(--accent); background: var(--surface-2); }
    .nav-sep, .nav-label { display: none; }
    /* Support must not disappear on compact browsers or desktop webviews. */
    .nav-support-group { display: flex; align-items: center; gap: 5px; padding: 7px 0 0; margin: 5px 0 0; border-top: 1px solid var(--border); }
    .nav-support-group .nav-support { flex: 1 1 auto; justify-content: center; min-height: 36px; margin: 0; padding: 8px 10px; white-space: nowrap; }
    .nav-support-group .nav-support svg:last-child { display: none; }
    .sidebar { overflow: visible; }
    @media (max-width: 430px) {
      .nav-support-group .nav-support { font-size: 11px; padding: 8px 6px; }
      .nav-support-group .nav-support svg:first-child { width: 13px; height: 13px; }
    }
    .main { padding: 18px 16px; max-height: none; }
    .grid { grid-template-columns: minmax(0, 1fr); }
    .form-row { flex-wrap: wrap; }
    .form-row .form-group { min-width: 100%; }
    .wizard-steps { overflow-x: auto; justify-content: flex-start; gap: 8px; padding-bottom: 10px; }
    .wizard-step { flex-shrink: 0; min-width: 80px; }
  }
</style>
</head>
<body>

<!-- Sidebar -->
<nav class="sidebar" aria-label="Main Navigation">
  <div class="brand">
    <div style="display:flex;align-items:center;gap:10px;">
      <div class="brand-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="3" stroke="var(--border-strong)"/>
          <circle cx="8" cy="8" r="2" fill="var(--accent)"/>
          <circle cx="16" cy="16" r="2" fill="var(--success)"/>
          <path d="M8 10v4a2 2 0 0 0 2 2h4"/>
        </svg>
      </div>
      <div class="brand-title">
        <h1>KiCad MCP Pro</h1>
        <span class="badge" id="navVersion">v{{version}}</span>
      </div>
    </div>
  </div>
  <div class="status-row" id="navStatusRow">
    <span class="status-dot ok" id="navStatusDot" aria-hidden="true"></span>
    <span id="navStatusText">Checking...</span>
  </div>
  <div class="nav-items-container">
    <button type="button" class="nav-item active" data-view="dashboard">
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>
      <span>Dashboard</span>
    </button>
    <button type="button" class="nav-item" data-view="log-viewer">
      <svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
      <span>Logs</span>
    </button>
    <button type="button" class="nav-item" data-view="tools-catalog">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
      <span>Tools</span>
    </button>
    <button type="button" class="nav-item" data-view="preview">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
      <span>Preview</span>
    </button>
    <button type="button" class="nav-item" data-view="settings">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      <span>Settings</span>
    </button>
    <button type="button" class="nav-item" data-view="setup-wizard">
      <svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
      <span>Setup</span>
    </button>
    <div class="nav-sep"></div>
    <div class="nav-label">AI Agents</div>
    <a class="nav-item" href="https://oaslananka.github.io/kicad-mcp-pro/agents/" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4M8 16h.01M16 16h.01"/></svg>
      <span>Agent Setup</span>
      <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" style="margin-left:auto;"><path d="M6 3h7v7M13 3 7 9"/></svg>
    </a>
    <a class="nav-item" href="https://oaslananka.github.io/kicad-mcp-pro/agents/prompts/" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span>Prompt Library</span>
      <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" style="margin-left:auto;"><path d="M6 3h7v7M13 3 7 9"/></svg>
    </a>
  </div>
  <div class="nav-support-group">
    <div class="nav-label">Support</div>
    <a class="nav-item nav-support github" href="https://github.com/sponsors/oaslananka" target="_blank" rel="noopener noreferrer" aria-label="Support KiCad MCP Pro through GitHub Sponsors">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
      <span>GitHub Sponsors</span>
      <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" style="margin-left:auto;"><path d="M6 3h7v7M13 3 7 9"/></svg>
    </a>
    <a class="nav-item nav-support coffee" href="https://www.buymeacoffee.com/oaslananka" target="_blank" rel="noopener noreferrer" aria-label="Support KiCad MCP Pro through Buy me a coffee">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 8h1a4 4 0 0 1 0 8h-1M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8zM6 1v3M10 1v3M14 1v3"/></svg>
      <span>Buy me a coffee</span>
      <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" style="margin-left:auto;"><path d="M6 3h7v7M13 3 7 9"/></svg>
    </a>
  </div>
</nav>

<!-- Main content -->
<main class="main" id="mainContent">
  <p class="msg warn" role="status" aria-live="polite" id="externalLinkMessage" style="display:none"></p>

  <!-- Dashboard -->
  <div class="view active" id="view-dashboard">
    <section class="local-workspace-intro" aria-label="Choose how to use KiCad MCP Pro">
      <div>
        <span class="local-workspace-kicker">YOUR KICAD WORKSPACE</span>
        <h2>Start with your project.</h2>
        <p>Work locally without an account. Connect Cloud only when you want authorized remote AI access.</p>
      </div>
      <div class="local-workspace-actions">
        <button type="button" class="btn btn-primary" onclick="window.location.hash='#setup-wizard'">Set up local AI</button>
        <a class="btn local-cloud-link" href="https://kicad-mcp-pro.oaslananka.dev/sign-in" target="_blank" rel="noopener noreferrer">Open Cloud sign-in</a>
      </div>
      <p class="local-workspace-safety">Cloud sign-in, device pairing and each project permission are independent. Signing in never shares local files.</p>
    </section>
    <h2>Local status</h2>
    <div class="grid" id="statusGrid">
      <div class="card">
        <h3>Server</h3>
        <div class="row"><span class="label">Profile</span><span class="value" id="s-profile">-</span></div>
        <div class="row"><span class="label">Mode</span><span class="value" id="s-mode">-</span></div>
        <div class="row"><span class="label">Transport</span><span class="value" id="s-transport">-</span></div>
        <div class="row"><span class="label">Host</span><span class="value" id="s-host">-</span></div>
        <div class="row"><span class="label">Port</span><span class="value" id="s-port">-</span></div>
        <div class="row"><span class="label">Uptime</span><span class="value" id="s-uptime">-</span></div>
      </div>
      <div class="card">
        <h3>KiCad</h3>
        <div class="row"><span class="label">CLI</span><span class="value" id="k-cli">-</span></div>
        <div class="row"><span class="label">Version</span><span class="value" id="k-version">-</span></div>
        <div class="row"><span class="label">IPC</span><span class="value" id="k-ipc">-</span></div>
      </div>
      <div class="card">
        <h3>Project</h3>
        <div class="row"><span class="label">Directory</span><span class="value" id="p-dir">-</span></div>
        <div class="row"><span class="label">PCB</span><span class="value" id="p-pcb">-</span></div>
        <div class="row"><span class="label">SCH</span><span class="value" id="p-sch">-</span></div>
      </div>
      <div class="card">
        <h3>Health</h3>
        <div id="health-checks"></div>
        <div class="row" style="margin-top:10px; padding-top:8px; border-top:1px solid var(--border);">
          <span class="label">Overall</span><span class="value" id="health-overall">-</span>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Quick Actions</h3>
      <div class="actions">
        <button type="button" class="btn btn-sm btn-primary" onclick="serverAction('start')">Start</button>
        <button type="button" class="btn btn-sm btn-danger" onclick="serverAction('stop')">Stop</button>
        <button type="button" class="btn btn-sm" onclick="serverAction('restart')">Restart</button>
        <button type="button" class="btn btn-sm" onclick="refreshStatus()">Refresh Status</button>
        <button type="button" class="btn btn-sm" onclick="window.open('/api/status','_blank')">Status JSON</button>
        <button type="button" class="btn btn-sm" onclick="window.open('/api/metrics','_blank')">Metrics JSON</button>
        <button type="button" class="btn btn-sm" onclick="window.open('/api/health','_blank')">Health JSON</button>
        <button type="button" class="btn btn-sm" onclick="window.location.hash='#/logs'">All Logs</button>
      </div>
      <div id="action-msg" role="status" aria-live="polite" style="margin-top:10px;font-size:13px;"></div>
    </div>
    <div class="card" style="margin-top:16px;">
      <h3>Recent Tool Calls</h3>
      <div class="recent-list" id="recent-calls">
        <div class="row"><span class="label">No tool calls yet.</span><span class="value">Live</span></div>
      </div>
    </div>
  </div>

  <!-- Log Viewer -->
  <div class="view" id="view-log-viewer">
    <h2>Log Viewer</h2>
    <div class="log-controls">
      <input type="text" id="logSearch" placeholder="Search logs or /regex/" aria-label="Search logs or regular expression" oninput="applyLogFilters()" style="max-width:240px;">
      <button type="button" class="active" data-level="all" onclick="setLogFilter('all',this)">All</button>
      <button type="button" data-level="debug" onclick="setLogFilter('debug',this)">Debug</button>
      <button type="button" data-level="info" onclick="setLogFilter('info',this)">Info</button>
      <button type="button" data-level="warning" onclick="setLogFilter('warning',this)">Warn</button>
      <button type="button" data-level="error" onclick="setLogFilter('error',this)">Error</button>
      <button type="button" onclick="downloadLogs()">Download</button>
      <button type="button" onclick="clearLog()">Clear</button>
      <button type="button" id="jumpBottom" onclick="jumpToBottom()" style="display:none;">Go Bottom</button>
      <span class="live-badge" id="live-badge" data-testid="live-badge" role="status" aria-live="polite">Connecting</span>
    </div>
    <div id="log-container" tabindex="0" aria-label="Live log stream"><div class="line" style="color:var(--text-muted)">Connecting to log stream...</div></div>
  </div>

  <!-- Tools Catalog -->
  <div class="view" id="view-tools-catalog">
    <h2>Tools Catalog</h2>
    <div class="tool-search form-row">
      <input type="text" id="toolSearch" placeholder="Search tools by name or keyword..." aria-label="Search MCP tools by name or keyword" oninput="filterTools()">
      <select id="toolCategory" aria-label="Filter tools by category" onchange="filterTools()" style="max-width:200px;">
        <option value="all">All categories</option>
      </select>
    </div>
    <div id="tools-loading" class="loading"><div class="spinner"></div> Loading tools...</div>
    <div id="tools-count" style="font-size:12px;color:var(--text-muted);margin-bottom:12px;font-weight:500;display:none;"></div>
    <div class="tool-layout">
      <div class="tool-grid" id="toolGrid"></div>
      <div class="card tool-detail" id="toolDetail">
        <h3>Tool Detail</h3>
        <div class="msg info">Select a tool to inspect its schema.</div>
      </div>
    </div>
  </div>

  <!-- Preview -->
  <div class="view" id="view-preview">
    <h2>Preview</h2>
    <div id="preview-loading" class="loading"><div class="spinner"></div> Loading previews...</div>
    <div id="preview-empty" class="msg info" style="display:none;">
      No schematic renders yet — run <code>sch_live_preview</code> to generate one.
    </div>
    <div id="previewGrid" class="tool-grid"></div>
  </div>

  <!-- Settings -->
  <div class="view" id="view-settings">
    <h2>Settings</h2>
    <div id="settings-msg" role="status" aria-live="polite"></div>
    <form id="settingsForm" onsubmit="saveSettings(event)">
      <div class="card" style="margin-bottom:16px;">
        <h3>KiCad &amp; Server Runtime</h3>
        <div class="form-row">
          <div class="form-group">
            <label for="cfg-kicad_path">KiCad Path</label>
            <input type="text" id="cfg-kicad_path" name="kicad_path" placeholder="auto-detect">
          </div>
          <div class="form-group">
            <label for="cfg-transport">Transport</label>
            <select id="cfg-transport" name="transport">
              <option value="streamable-http">streamable-http</option>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="cfg-host">Host</label>
            <input type="text" id="cfg-host" name="host" placeholder="127.0.0.1">
          </div>
          <div class="form-group">
            <label for="cfg-port">Port</label>
            <input type="number" id="cfg-port" name="port" placeholder="9090" min="1" max="65535">
          </div>
        </div>
      </div>
      <div class="card" style="margin-bottom:16px;">
        <h3>Profile &amp; Governance</h3>
        <div class="form-row">
          <div class="form-group">
            <label for="cfg-profile">Profile</label>
            <input type="text" id="cfg-profile" name="profile" placeholder="default">
          </div>
          <div class="form-group">
            <label for="cfg-log_level">Log Level</label>
            <select id="cfg-log_level" name="log_level">
              <option value="DEBUG">DEBUG</option>
              <option value="INFO" selected>INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="cfg-operating_mode">Operating Mode</label>
            <select id="cfg-operating_mode" name="operating_mode">
              <option value="readonly">readonly</option>
              <option value="write">write</option>
              <option value="manufacturing">manufacturing</option>
              <option value="experimental">experimental</option>
            </select>
            <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">Takes effect after server restart.</div>
          </div>
        </div>
      </div>
      <div class="actions">
        <button type="submit" class="btn btn-primary">Save Settings</button>
        <button type="button" class="btn" onclick="loadSettings()">Discard Changes</button>
      </div>
    </form>
    <div class="card" style="margin-top:20px;">
      <h3>Export Client Config</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
        <button type="button" class="btn btn-sm" onclick="exportClientConfig('claude')">Claude Desktop</button>
        <button type="button" class="btn btn-sm" onclick="exportClientConfig('cursor')">Cursor</button>
        <button type="button" class="btn btn-sm" onclick="exportClientConfig('vscode')">VS Code</button>
        <button type="button" class="btn btn-sm" onclick="exportClientConfig('windsurf')">Windsurf</button>
        <button type="button" class="btn btn-sm" onclick="exportClientConfig('zed')">Zed</button>
      </div>
      <pre id="export-result" style="display:none;margin-top:10px;background:var(--bg-canvas);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;font-size:12px;font-family:var(--font-mono);overflow-x:auto;"></pre>
    </div>
  </div>

  <!-- Setup Wizard -->
  <div class="view" id="view-setup-wizard">
    <h2>Setup Wizard</h2>
    <div class="wizard-steps" id="wizardSteps" role="tablist" aria-label="Setup steps">
      <div class="wizard-step active" data-step="0"><div class="step-num">1</div><span>KiCad Detection</span></div>
      <div class="wizard-step" data-step="1"><div class="step-num">2</div><span>Project</span></div>
      <div class="wizard-step" data-step="2"><div class="step-num">3</div><span>Transport</span></div>
      <div class="wizard-step" data-step="3"><div class="step-num">4</div><span>Client Config</span></div>
      <div class="wizard-step" data-step="4"><div class="step-num">5</div><span>Test &amp; Finish</span></div>
    </div>
    <div id="wizardMsg" role="status" aria-live="polite"></div>
    <div class="wizard-body" id="wizardBody"></div>
    <div class="wizard-nav" id="wizardNav"></div>
  </div>

</main>

<script>
(function() {
  const urlParams = new URLSearchParams(window.location.search);
  let token = urlParams.get('token');
  if (!token) {
    const hashQuery = window.location.hash.split('?')[1];
    if (hashQuery) {
      const hashParams = new URLSearchParams(hashQuery);
      token = hashParams.get('token');
    }
  }
  if (token) {
    sessionStorage.setItem('kicad_mcp_token', token);
  }
  const savedToken = sessionStorage.getItem('kicad_mcp_token');
  if (savedToken) {
    const originalFetch = window.fetch;
    window.fetch = function(input, init) {
      let url = typeof input === 'string' ? input : input.url;
      const separator = url.includes('?') ? '&' : '?';
      url = url + separator + 'token=' + encodeURIComponent(savedToken);
      init = init || {};
      init.headers = init.headers || {};
      if (init.headers instanceof Headers) {
        init.headers.set('Authorization', 'Bearer ' + savedToken);
      } else if (Array.isArray(init.headers)) {
        init.headers.push(['Authorization', 'Bearer ' + savedToken]);
      } else {
        init.headers['Authorization'] = 'Bearer ' + savedToken;
      }
      if (typeof input === 'string') {
        return originalFetch(url, init);
      } else {
        const newRequest = new Request(url, input);
        return originalFetch(newRequest, init);
      }
    };
    const originalEventSource = window.EventSource;
    window.EventSource = function(url, configuration) {
      const separator = url.includes('?') ? '&' : '?';
      const newUrl = url + separator + 'token=' + encodeURIComponent(savedToken);
      return new originalEventSource(newUrl, configuration);
    };
    window.EventSource.prototype = originalEventSource.prototype;
  }
})();

/* ── State ── */
const WEB_VERSION = '{{version}}';
let statusInterval = null;
let eventSource = null;
let logFilter = 'all';
let logEl = document.getElementById('log-container');
let wizardStep = 0;
let logBuffer = [];
let recentCalls = [];
let sseReconnectMs = 1000;
let autoScroll = true;
let selectedTool = null;

/* ── Router ── */
function navigate(view) {
  const aliases = {
    '': 'dashboard',
    '/': 'dashboard',
    'dashboard': 'dashboard',
    '/dashboard': 'dashboard',
    'logs': 'log-viewer',
    '/logs': 'log-viewer',
    'log-viewer': 'log-viewer',
    'tools': 'tools-catalog',
    '/tools': 'tools-catalog',
    'tools-catalog': 'tools-catalog',
    'preview': 'preview',
    '/preview': 'preview',
    'settings': 'settings',
    '/settings': 'settings',
    'setup': 'setup-wizard',
    '/setup': 'setup-wizard',
    'setup-wizard': 'setup-wizard',
  };
  const rawHash = view || window.location.hash.replace('#','') || 'dashboard';
  const hash = aliases[rawHash] || aliases[rawHash.replace(/^\/+/, '')] || 'dashboard';
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
  const targetView = document.getElementById('view-' + hash);
  const targetNav = document.querySelector('[data-view="' + hash + '"]');
  if (targetView) targetView.classList.add('active');
  if (targetNav) targetNav.classList.add('active');
  if (hash === 'tools-catalog' && !document.getElementById('toolGrid').children.length) {
    loadTools();
  }
  if (hash === 'preview') loadPreview();
  if (hash === 'settings') loadSettings();
  if (hash === 'setup-wizard') initWizard();
}

document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    const view = el.dataset.view;
    if (view) window.location.hash = view;
  });
});
window.addEventListener('hashchange', () => navigate());
window.addEventListener('DOMContentLoaded', () => navigate());
logEl.addEventListener('scroll', () => {
  autoScroll = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24;
  byId('jumpBottom').style.display = autoScroll ? 'none' : 'inline-block';
});

/* ── Status / Health ── */
function refreshStatus() {
  fetch('/api/status').then(r => r.json()).then(d => {
    const s = d.server || {}, kc = d.kicad || {}, pr = d.project || {}, hl = d.health || {};
    setText('s-profile', s.profile || '-');
    setText('s-mode', s.operating_mode || '-');
    setText('s-transport', s.transport || '-');
    setText('s-host', s.host || '-');
    setText('s-port', String(s.port ?? '-'));
    setText('k-cli', kc.cli_path || 'Not found');
    setText('k-version', kc.version || 'Unknown');
    const ipcEl = byId('k-ipc');
    ipcEl.textContent = kc.ipc_status || 'disconnected';
    ipcEl.className = 'value ' + (kc.ipc_status === 'connected' ? 'ok' : 'warn');
    setText('p-dir', pr.dir || 'Not set');
    setText('p-pcb', pr.pcb || '-');
    setText('p-sch', pr.sch || '-');

    // Uptime from metrics or fallback
    fetch('/api/metrics').then(r => r.json()).then(m => {
      setText('s-uptime', m.uptime_human || '-');
    }).catch(() => setText('s-uptime', '-'));

    // Health checks
    const hc = byId('health-checks');
    hc.innerHTML = '';
    if (hl.checks) {
      hl.checks.forEach(c => {
        const row = doc('div', 'row');
        const cls = c.status === 'ok' ? 'ok' : c.status === 'warn' ? 'warn' : 'err';
        row.innerHTML = '<span class="label">' + esc(c.name) + '</span><span class="value ' + cls + '">' + esc(c.message) + '</span>';
        hc.appendChild(row);
      });
    }
    const overall = byId('health-overall');
    overall.textContent = hl.status || '-';
    overall.className = 'value ' + (hl.ok ? 'ok' : hl.status === 'degraded' ? 'warn' : 'err');

    // Nav status
    const sd = byId('navStatusDot');
    sd.className = 'status-dot ' + (hl.ok ? 'ok' : hl.status === 'degraded' ? 'warn' : 'error');
    byId('navStatusText').textContent = hl.status || 'Unknown';
  }).catch(() => {
    byId('navStatusDot').className = 'status-dot error';
    byId('navStatusText').textContent = 'Disconnected';
  });
}

/* ── Log Viewer ── */
function setLogFilter(level, btn) {
  logFilter = level;
  document.querySelectorAll('.log-controls button[data-level]').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  applyLogFilters();
}

function clearLog() {
  logBuffer = [];
  logEl.innerHTML = '';
  renderRecentCalls();
}

function addLogLine(data) {
  try {
    const entry = JSON.parse(data);
    const level = (entry.level || 'INFO').toLowerCase();
    logBuffer.push(entry);
    if (logBuffer.length > 1000) logBuffer.shift();
    trackRecentCall(entry);
    const line = doc('div', 'line ' + level);
    line.dataset.level = level;
    line.dataset.search = JSON.stringify(entry).toLowerCase();
    const ts = (entry.timestamp || '').slice(11,19) || new Date().toTimeString().slice(0,8);
    line.innerHTML =
      '<span>[' + esc(ts) + '] [' + esc(level.toUpperCase()) + '] ' +
      esc(entry.event || entry.message || '') + '</span>' +
      '<div class="detail">' + esc(JSON.stringify(entry, null, 2)) + '</div>';
    line.addEventListener('click', () => line.classList.toggle('expanded'));
    logEl.appendChild(line);
    while (logEl.children.length > 1000) logEl.removeChild(logEl.firstElementChild);
    applyLogFilters();
    if (autoScroll) jumpToBottom();
  } catch(e) {}
}

function connectSSE() {
  if (eventSource) { eventSource.close(); }
  eventSource = new EventSource('/api/logs/stream');
  eventSource.onopen = function() {
    sseReconnectMs = 1000;
    const badge = byId('live-badge');
    badge.textContent = 'Live';
    badge.style.color = 'var(--success)';
  };
  eventSource.onmessage = function(e) { addLogLine(e.data); };
  eventSource.addEventListener('log', function(e) { addLogLine(e.data); });
  eventSource.onerror = function() {
    const badge = byId('live-badge');
    badge.textContent = 'Retrying in ' + Math.round(sseReconnectMs / 1000) + 's';
    badge.style.color = 'var(--warning)';
    setTimeout(connectSSE, sseReconnectMs);
    sseReconnectMs = Math.min(sseReconnectMs * 2, 30000);
  };
}

function applyLogFilters() {
  const raw = (byId('logSearch')?.value || '').trim();
  let matcher = null;
  if (raw) {
    try {
      matcher = raw.startsWith('/') && raw.endsWith('/')
        ? new RegExp(raw.slice(1, -1), 'i')
        : new RegExp(raw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    } catch(e) {
      matcher = null;
    }
  }
  document.querySelectorAll('#log-container .line').forEach(line => {
    const levelOk = logFilter === 'all' || line.dataset.level === logFilter;
    const searchOk = !matcher || matcher.test(line.dataset.search || line.textContent || '');
    line.classList.toggle('hidden', !(levelOk && searchOk));
  });
}

function jumpToBottom() {
  logEl.scrollTop = logEl.scrollHeight;
  autoScroll = true;
  byId('jumpBottom').style.display = 'none';
}

function downloadLogs() {
  const body = logBuffer.map(e => JSON.stringify(e)).join('\n');
  const url = URL.createObjectURL(new Blob([body], {type: 'text/plain'}));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'kicad-mcp-pro.log';
  a.click();
  URL.revokeObjectURL(url);
}

function trackRecentCall(entry) {
  const text = String(entry.event || entry.message || '');
  const tool = entry.tool || entry.tool_name || (text.match(/tool[_ ]call[^:]*:?\s*([a-z0-9_]+)/i) || [])[1];
  if (!tool) return;
  const status = entry.status || (String(entry.level || '').toLowerCase() === 'error' ? 'error' : 'ok');
  const latency = entry.latency_ms ? Math.round(entry.latency_ms) + 'ms' : '';
  recentCalls.unshift({time: (entry.timestamp || '').slice(11,19) || new Date().toTimeString().slice(0,8), tool, status, latency});
  recentCalls = recentCalls.slice(0, 10);
  renderRecentCalls();
}

function renderRecentCalls() {
  const el = byId('recent-calls');
  if (!el) return;
  if (!recentCalls.length) {
    el.innerHTML = '<div class="row"><span class="label">No tool calls yet.</span><span class="value">Live</span></div>';
    return;
  }
  el.innerHTML = recentCalls.map(c =>
    '<div class="recent-call"><span>' + esc(c.time) + '</span><span style="font-weight:600;">' +
    esc(c.tool) + '</span><span class="' + esc(c.status) + '">' +
    esc(c.status.toUpperCase()) + '</span><span style="text-align:right;color:var(--text-muted);">' + esc(c.latency || '') + '</span></div>'
  ).join('');
}

/* ── Tools Catalog ── */
function loadTools() {
  byId('tools-loading').style.display = 'block';
  byId('tools-count').style.display = 'none';
  byId('toolGrid').innerHTML = '';
  fetch('/api/tools').then(r => r.json()).then(d => {
    byId('tools-loading').style.display = 'none';
    const tools = d.tools || [];
    const countEl = byId('tools-count');
    countEl.textContent = tools.length + ' tools loaded';
    countEl.style.display = 'block';
    window._allTools = tools.map(t => ({...t, category: toolCategory(t)}));
    populateToolCategories(window._allTools);
    renderTools(window._allTools);
  }).catch(() => {
    byId('tools-loading').innerHTML = 'Failed to load tools.';
  });
}

function renderTools(tools) {
  const grid = byId('toolGrid');
  grid.innerHTML = '';
  if (!tools.length) {
    grid.innerHTML = '<div class="card" style="text-align:center;color:var(--text-muted)">No tools match your search.</div>';
    return;
  }
  tools.forEach(t => {
    const card = doc('div', 'tool-card');
    if (selectedTool && selectedTool.name === t.name) card.classList.add('selected');
    const params = t.inputSchema && t.inputSchema.properties ? t.inputSchema.properties : {};
    const paramKeys = Object.keys(params);
    card.innerHTML =
      '<h4>' + esc(t.name) + '</h4>' +
      '<div class="tool-desc">' + esc(t.description || 'No description') + '</div>' +
      '<div class="tool-meta">' +
        '<span class="tool-badge">' + esc(t.category || toolCategory(t)) + '</span>' +
        '<span>Params: ' + paramKeys.length + '</span>' +
        (t.annotations && t.annotations.length ? '<span>Tags: ' + esc(t.annotations.join(', ')) + '</span>' : '') +
      '</div>' +
      (paramKeys.length ? '<div class="tool-params"><strong>Parameters:</strong> ' +
        paramKeys.map(k => '<code>' + esc(k) + '</code>' + (params[k].description ? ': ' + esc(params[k].description) : '')).join(', ') +
      '</div>' : '');
    card.addEventListener('click', () => selectTool(t));
    grid.appendChild(card);
  });
  if (!selectedTool && tools.length) selectTool(tools[0]);
}

function filterTools() {
  const q = byId('toolSearch').value.toLowerCase();
  const category = byId('toolCategory').value;
  const all = window._allTools || [];
  const filtered = all.filter(t => {
    const matchesText = !q || t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q);
    const matchesCategory = category === 'all' || t.category === category;
    return matchesText && matchesCategory;
  });
  renderTools(filtered);
}

function populateToolCategories(tools) {
  const select = byId('toolCategory');
  const categories = Array.from(new Set(tools.map(t => t.category))).sort();
  select.innerHTML = '<option value="all">All categories</option>' +
    categories.map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join('');
}

function toolCategory(tool) {
  const name = String(tool.name || '');
  if (name.startsWith('sch_') || name.includes('schematic')) return 'Schematic';
  if (name.startsWith('pcb_') || name.includes('footprint') || name.includes('route')) return 'PCB';
  if (name.includes('drc') || name.includes('erc') || name.includes('validate')) return 'Validation';
  if (name.includes('bom')) return 'BOM';
  if (name.includes('export') || name.includes('gerber') || name.includes('drill')) return 'Export';
  if (name.includes('dfm') || name.includes('manufacturing')) return 'Manufacturing';
  return 'General';
}

function selectTool(tool) {
  selectedTool = tool;
  const params = tool.inputSchema && tool.inputSchema.properties ? tool.inputSchema.properties : {};
  const required = tool.inputSchema && tool.inputSchema.required ? tool.inputSchema.required : [];
  byId('toolDetail').innerHTML =
    '<h3>' + esc(tool.name) + '</h3>' +
    '<p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;line-height:1.5;">' + esc(tool.description || 'No description') + '</p>' +
    '<div class="row"><span class="label">Category</span><span class="value">' + esc(tool.category || toolCategory(tool)) + '</span></div>' +
    '<div class="row"><span class="label">Parameters</span><span class="value">' + Object.keys(params).length + '</span></div>' +
    '<pre style="margin-top:10px;">' + esc(JSON.stringify({required, properties: params}, null, 2)) + '</pre>' +
    '<div class="actions" style="margin-top:12px;"><button type="button" class="btn btn-sm btn-primary" onclick="testSelectedTool()">Test</button>' +
    '<button type="button" class="btn btn-sm" onclick="copySelectedSchema()">Copy Schema</button></div>' +
    '<div id="tool-test-result" style="margin-top:12px;"></div>';
  renderTools((window._allTools || []).filter(t => {
    const q = byId('toolSearch').value.toLowerCase();
    const category = byId('toolCategory').value;
    return (!q || t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q)) &&
      (category === 'all' || t.category === category);
  }));
}

function copySelectedSchema() {
  if (!selectedTool) return;
  navigator.clipboard.writeText(JSON.stringify(selectedTool.inputSchema || {}, null, 2)).then(() => {
    const res = byId('tool-test-result');
    if (res) res.innerHTML = '<div class="msg success">Schema copied to clipboard!</div>';
  });
}

function testSelectedTool() {
  if (!selectedTool) return;
  const result = byId('tool-test-result');
  result.innerHTML = '<div class="msg info">Testing schema...</div>';
  fetch('/api/tools/' + encodeURIComponent(selectedTool.name) + '/test', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({dry_run: true, arguments: {}}),
  }).then(r => r.json()).then(d => {
    result.innerHTML = '<pre>' + esc(JSON.stringify(d, null, 2)) + '</pre>';
  }).catch(() => {
    result.innerHTML = '<div class="msg error">Tool test failed.</div>';
  });
}

/* ── Preview ── */
function loadPreview() {
  byId('preview-loading').style.display = 'block';
  byId('preview-empty').style.display = 'none';
  byId('previewGrid').innerHTML = '';
  fetch('/api/artifacts/schematic').then(r => r.json()).then(d => {
    byId('preview-loading').style.display = 'none';
    const artifacts = d.artifacts || [];
    if (!artifacts.length) {
      byId('preview-empty').style.display = 'block';
      return;
    }
    const grid = byId('previewGrid');
    artifacts.forEach(a => {
      const imgPath = a.svg_path || a.png_path;
      if (!imgPath) return;
      const url = '/api/artifacts/file?path=' + encodeURIComponent(imgPath);
      const ts = a.timestamp ? new Date(a.timestamp * 1000).toLocaleString() : 'unknown time';
      const name = a.sheet_path || a.target_path || a.session_id;
      const card = doc('div', 'tool-card');
      card.innerHTML =
        '<div style="background:#fff;border-radius:var(--radius-sm);padding:8px;margin-bottom:10px;">' +
        '<img src="' + esc(url) + '" alt="Schematic preview" style="width:100%;display:block;border-radius:4px;">' +
        '</div>' +
        '<div style="font-size:13px;font-weight:600;margin-bottom:4px;word-break:break-all;">' + esc(name) + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);">' + esc(ts) + '</div>';
      grid.appendChild(card);
    });
  }).catch(() => {
    byId('preview-loading').innerHTML = 'Failed to load previews.';
  });
}

/* ── Settings ── */
function loadSettings() {
  byId('settings-msg').innerHTML = '';
  fetch('/api/config').then(r => r.json()).then(payload => {
    const cfg = payload.config || payload;
    setField('cfg-kicad_path', cfg.kicad_path || '');
    setField('cfg-transport', cfg.transport || 'streamable-http');
    setField('cfg-host', cfg.host || '127.0.0.1');
    setField('cfg-port', String(cfg.port || '3334'));
    setField('cfg-profile', cfg.profile || '');
    setField('cfg-log_level', cfg.log_level || 'INFO');
    setField('cfg-operating_mode', cfg.operating_mode || 'readonly');
  }).catch(() => {
    showMsg('settings-msg', 'Failed to load config', 'error');
  });
}

function saveSettings(e) {
  e.preventDefault();
  const form = byId('settingsForm');
  const data = {};
  new FormData(form).forEach((v, k) => { data[k.replace('cfg-','')] = v; });
  data.port = parseInt(data.port, 10) || 3334;
  byId('settings-msg').innerHTML = '';
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(data),
  }).then(r => r.json()).then(res => {
    showMsg('settings-msg', res.message || res.status || 'Settings saved. Some changes require a restart.', res.error ? 'error' : 'success');
  }).catch(() => {
    showMsg('settings-msg', 'Failed to save settings', 'error');
  });
}

function exportClientConfig(client) {
  fetch('/api/config/export/' + encodeURIComponent(client))
    .then(r => r.json()).then(d => {
      const el = byId('export-result');
      el.textContent = d.config || d.error || 'No config returned';
      el.style.display = 'block';
    }).catch(() => {
      byId('export-result').textContent = 'Error fetching config.';
      byId('export-result').style.display = 'block';
    });
}

/* ── Setup Wizard ── */
function initWizard() {
  wizardStep = 0;
  document.querySelectorAll('.wizard-step').forEach(s => {
    const i = parseInt(s.dataset.step, 10);
    s.className = 'wizard-step' + (i === 0 ? ' active' : '');
  });
  byId('wizardMsg').innerHTML = '';
  renderWizardStep(0);
}

function renderWizardStep(step) {
  const body = byId('wizardBody');
  const nav = byId('wizardNav');
  body.innerHTML = '';
  nav.innerHTML = '';

  switch(step) {
    case 0:
      body.innerHTML =
        '<div class="msg info">Detecting KiCad installation...</div>' +
        '<div class="loading"><div class="spinner"></div></div>';
      fetch('/api/status').then(r => r.json()).then(d => {
        const kc = d.kicad || {};
        body.innerHTML =
          (kc.cli_path ? '<div class="msg success">KiCad CLI found: ' + esc(kc.cli_path) + '</div>' :
            '<div class="msg warn">KiCad CLI not found. You can set it manually in Settings.</div>') +
          (kc.version ? '<div class="row"><span class="label">Version</span><span class="value">' + esc(kc.version) + '</span></div>' : '') +
          '<div class="row" style="margin-top:8px"><span class="label">IPC Status</span><span class="value ' + (kc.ipc_status === 'connected' ? 'ok' : 'warn') + '">' + esc(kc.ipc_status || 'disconnected') + '</span></div>';
      }).catch(() => {
        body.innerHTML = '<div class="msg error">Could not connect to server.</div>';
      });
      nav.innerHTML = '<button type="button" class="btn" onclick="cancelWizard()">Cancel</button><button type="button" class="btn btn-primary" onclick="wizardNext()">Next</button>';
      break;

    case 1:
      body.innerHTML =
        '<div class="form-group"><label for="wizProjectDir">Default KiCad Project Directory</label>' +
        '<div style="display:flex;gap:8px;">' +
        '<input type="text" id="wizProjectDir" value="" placeholder="Full local project folder path" style="flex:1;">' +
        '<button type="button" class="btn btn-sm" onclick="browseProjectDir()" style="white-space:nowrap;flex-shrink:0;">Browse</button>' +
        '</div></div>' +
        '<div class="msg info">PCB and schematic files in this directory can be offered to tools automatically.</div>';
      // Keep the already-selected local project, without asking the user to
      // retype it whenever the wizard is reopened.
      fetch('/api/config').then(r => r.json()).then(d => {
        const field = document.getElementById('wizProjectDir');
        if (field && !field.value && d.project_dir) field.value = d.project_dir;
      }).catch(() => {});
      nav.innerHTML = '<button type="button" class="btn" onclick="wizardPrev()">Back</button><button type="button" class="btn btn-primary" onclick="wizardNext()">Next</button>';
      break;

    case 2:
      body.innerHTML =
        '<div class="form-group"><label for="wizTransport">Transport Mode</label>' +
        '<select id="wizTransport"><option value="streamable-http" selected>streamable-http (recommended)</option><option value="stdio">stdio (stdin/stdout)</option></select></div>' +
        '<div class="form-group" id="wizPortGroup"><label for="wizPort">Port (HTTP only)</label><input type="number" id="wizPort" value="3334" min="1" max="65535"></div>' +
        '<div class="form-group"><label for="wizHost">Host (HTTP only)</label><input type="text" id="wizHost" value="127.0.0.1"></div>';
      document.getElementById('wizTransport').addEventListener('change', function() {
        document.getElementById('wizPortGroup').style.display = this.value !== 'stdio' ? 'block' : 'none';
      });
      nav.innerHTML = '<button type="button" class="btn" onclick="wizardPrev()">Back</button><button type="button" class="btn btn-primary" onclick="wizardNext()">Next</button>';
      break;

    case 3:
      body.innerHTML =
        '<div class="form-group"><label for="wizClient">Select MCP Client</label>' +
        '<select id="wizClient"><option value="claude-desktop">Claude Desktop</option><option value="cursor">Cursor</option><option value="vscode">VS Code</option><option value="windsurf">Windsurf</option><option value="zed">Zed</option></select></div>' +
        '<div id="wizConfigPreview" class="wizard-result" style="display:none;"></div>' +
        '<div class="actions" style="margin-top:12px;">' +
        '<button type="button" class="btn btn-sm" onclick="previewClientConfig()">Preview Config</button>' +
        '<button type="button" class="btn btn-sm" onclick="copyClientConfig()">Copy to Clipboard</button></div>';
      nav.innerHTML = '<button type="button" class="btn" onclick="wizardPrev()">Back</button><button type="button" class="btn btn-primary" onclick="wizardNext()">Next</button>';
      break;

    case 4:
      body.innerHTML =
        '<div class="msg info">Your KiCad MCP Pro is ready to use!</div>' +
        '<div id="testResult" class="wizard-result" style="display:none;"></div>' +
        '<div class="actions" style="margin-top:14px;">' +
        '<button type="button" class="btn btn-sm btn-primary" onclick="testConnection()">Test Connection</button></div>';
      nav.innerHTML = '<button type="button" class="btn" onclick="wizardPrev()">Back</button><button type="button" class="btn btn-success" onclick="finishWizard()">Finish</button>';
      break;
  }
}

function previewClientConfig() {
  const client = document.getElementById('wizClient').value;
  fetch('/api/config/export/' + encodeURIComponent(client))
    .then(r => r.json()).then(d => {
      const el = document.getElementById('wizConfigPreview');
      el.textContent = d.config || d.error || 'No config';
      el.style.display = 'block';
      el.className = 'wizard-result ' + (d.config ? 'success' : 'error');
    })
    .catch(() => {
      const el = document.getElementById('wizConfigPreview');
      el.textContent = 'Error fetching config';
      el.style.display = 'block';
      el.className = 'wizard-result error';
    });
}

function copyClientConfig() {
  const el = document.getElementById('wizConfigPreview');
  if (!el.textContent) { previewClientConfig(); return; }
  navigator.clipboard.writeText(el.textContent).then(() => {
    showMsg('wizardMsg', 'Config copied to clipboard!', 'success');
  }).catch(() => {
    showMsg('wizardMsg', 'Could not copy. Select text manually.', 'warn');
  });
}

function testConnection() {
  const el = document.getElementById('testResult');
  el.style.display = 'block';
  el.textContent = 'Testing...';
  el.className = 'wizard-result';
  fetch('/api/health').then(r => r.json()).then(d => {
    const serverState = d.ok ? 'online' : (d.status || 'offline');
    el.textContent = 'Server: ' + serverState + ' | Version: ' + (d.version || '?') + ' | Uptime: ' + (d.uptime || '?') + 's';
    el.className = 'wizard-result success';
  }).catch(() => {
    el.textContent = 'Connection failed. Check server is running.';
    el.className = 'wizard-result error';
  });
}

function browseProjectDir() {
  var input = document.getElementById('wizProjectDir');
  if (window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === 'function') {
    window.__TAURI_INTERNALS__.invoke('select_working_dir').then(function(path) {
      if (path) input.value = path;
    }).catch(function() { fallbackBrowseDir(input); });
  } else {
    fallbackBrowseDir(input);
  }
}
function fallbackBrowseDir(input) {
  // Standard browser folder pickers return a relative folder name, not a
  // usable absolute filesystem path. Never pretend that value is a path.
  input.focus();
  showMsg('wizardMsg',
    'Enter the full local folder path. For graphical folder selection, use the desktop app.',
    'warn');
}

function wizardAdvance() {
  const steps = document.querySelectorAll('.wizard-step');
  if (wizardStep < steps.length - 1) {
    steps[wizardStep].classList.remove('active');
    steps[wizardStep].classList.add('completed');
    wizardStep++;
    steps[wizardStep].classList.add('active');
    renderWizardStep(wizardStep);
  }
}

function wizardNext() {
  if (wizardStep !== 1) { wizardAdvance(); return; }
  const field = document.getElementById('wizProjectDir');
  const project = field ? field.value.trim() : '';
  if (!project) { wizardAdvance(); return; }

  // Explicitly save before exporting client configuration. Previously Next
  // discarded the typed folder, silently connecting the MCP host elsewhere.
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({project_dir: project})
  }).then(async response => {
    const result = await response.json();
    if (!response.ok || !Array.isArray(result.applied) ||
        !result.applied.includes('project_dir')) {
      throw new Error(result.error || 'Cannot select this project folder.');
    }
    wizardAdvance();
  }).catch(error => {
    showMsg('wizardMsg', error.message || 'Cannot select this project folder.', 'error');
  });
}

function wizardPrev() {
  const steps = document.querySelectorAll('.wizard-step');
  if (wizardStep > 0) {
    steps[wizardStep].classList.remove('active');
    steps[wizardStep - 1].classList.remove('completed');
    wizardStep--;
    steps[wizardStep].classList.remove('completed');
    steps[wizardStep].classList.add('active');
    renderWizardStep(wizardStep);
  }
}

function cancelWizard() { window.location.hash = '#dashboard'; }
function finishWizard() { window.location.hash = '#dashboard'; }

/* ── Server Control ── */
/* Use the host system browser for known links in a Tauri WebView. */
document.addEventListener('click', async (event) => {
  const link = event.target.closest?.('a[target="_blank"]');
  const invoke = window.__TAURI_INTERNALS__?.invoke;
  if (!link || typeof invoke !== 'function') return;
  const allowedLinks = new Set([
    'https://github.com/sponsors/oaslananka',
    'https://www.buymeacoffee.com/oaslananka',
    'https://oaslananka.github.io/kicad-mcp-pro/agents/',
    'https://oaslananka.github.io/kicad-mcp-pro/agents/prompts/',
    'https://kicad-mcp-pro.oaslananka.dev/sign-in'
  ]);
  if (!allowedLinks.has(link.href)) return;
  event.preventDefault();
  try {
    await invoke('open_external_link', {url: link.href});
  } catch (error) {
    const message = document.getElementById('externalLinkMessage');
    if (message) {
      message.style.display = 'block';
      message.textContent = 'Could not open the system browser. Please copy this address: ' + link.href;
    }
  }
});

function serverAction(action) {
  const dangerous = action === 'stop' || action === 'restart';
  if (dangerous && !confirm('Server action: ' + action + '. Continue?')) return;
  showMsg('action-msg', 'Sending ' + action + ' request...', 'info');
  fetch('/api/server/' + action, { method: 'POST' }).then(r => r.json()).then(d => {
    const msg = d.message || d.status || (action + ' requested');
    showMsg('action-msg', msg, d.error ? 'error' : 'info');
    setTimeout(refreshStatus, 1500);
  }).catch(err => {
    console.error('serverAction error:', err);
    showMsg('action-msg', 'Action failed: ' + err.message, 'error');
  });
}

function confirmRestart() {
  if (confirm('Are you sure you want to restart the server?')) {
    showMsg('action-msg', 'Restart initiated...', 'info');
    fetch('/api/server/restart', { method: 'POST' }).then(r => r.json()).then(d => {
      showMsg('action-msg', d.message || d.status || 'Restart initiated...', 'info');
      setTimeout(refreshStatus, 3000);
    }).catch(err => {
      console.error('confirmRestart error:', err);
      showMsg('action-msg', 'Restart failed: ' + err.message, 'error');
    });
  }
}

/* ── Helpers ── */
function byId(id) { return document.getElementById(id); }
function setText(id, val) { const e = byId(id); if (e) e.textContent = val; }
function setField(id, val) { const e = byId(id); if (e) e.value = val; }
function esc(s) {
  const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML;
}
function doc(tag, cls) {
  const e = document.createElement(tag); if (cls) e.className = cls; return e;
}
function showMsg(containerId, text, type) {
  const el = byId(containerId);
  if (!el) return;
  el.innerHTML = '<div class="msg ' + (type || 'info') + '" role="status" aria-live="polite">' + esc(text) + '</div>';
}

/* ── Init ── */
refreshStatus();
statusInterval = setInterval(refreshStatus, 5000);
connectSSE();
</script>
</body>
</html>"""

# Replace version template on import (derived from the package version, not hardcoded)
DASHBOARD_HTML = DASHBOARD_HTML.replace("{{version}}", __version__)
