"""Embedded SPA dashboard HTML for KiCad MCP Pro.

Single-file single-page application with hash-routed views:
- #dashboard - Server status, health, quick actions
- #log-viewer - SSE live log viewer with filter/clear
- #tools-catalog - MCP tools browser with search
- #settings - Config viewer/editor
- #setup-wizard - 4-step setup wizard
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
    --bg: #0d1117; --surface: #161b22; --surface-2: #1c2333;
    --border: #30363d; --text: #c9d1d9; --text-muted: #8b949e;
    --accent: #58a6ff; --success: #3fb950; --warning: #d29922;
    --error: #f85149; --info: #79c0ff; --sidebar-w: 200px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
    display: flex;
  }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* Sidebar */
  .sidebar {
    width: var(--sidebar-w); background: var(--surface);
    border-right: 1px solid var(--border); padding: 16px 0;
    display: flex; flex-direction: column; flex-shrink: 0;
  }
  .sidebar .brand {
    padding: 0 16px 16px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  }
  .sidebar .brand h1 { font-size: 15px; font-weight: 600; }
  .sidebar .brand .badge {
    font-size: 10px; padding: 1px 6px; border-radius: 10px;
    background: var(--accent); color: #fff; font-weight: 500;
  }
  .sidebar .status-row {
    padding: 8px 16px; font-size: 11px; color: var(--text-muted);
    display: flex; align-items: center; gap: 6px;
  }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%; display: inline-block;
  }
  .status-dot.ok { background: var(--success); }
  .status-dot.degraded { background: var(--warning); }
  .status-dot.error { background: var(--error); }
  .nav-item {
    padding: 10px 16px; font-size: 13px; cursor: pointer;
    color: var(--text-muted); transition: all 0.12s;
    border-left: 3px solid transparent;
  }
  .nav-item:hover { background: var(--surface-2); color: var(--text); }
  .nav-item.active {
    background: var(--surface-2); color: var(--accent);
    border-left-color: var(--accent); font-weight: 500;
  }
  a.nav-item { display: block; text-decoration: none; }
  .nav-sep { height: 1px; background: var(--surface-2); margin: 8px 14px; }
  .nav-label {
    padding: 6px 16px 2px; font-size: 10px; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--text-muted); opacity: 0.7;
  }
  .nav-support-group { margin-top: auto; padding-top: 10px; }
  .nav-support {
    margin: 4px 10px; padding: 8px 10px; border: 1px solid var(--border);
    border-radius: 7px; color: var(--text); font-weight: 600;
    display: flex; align-items: center; gap: 7px;
  }
  .nav-support:hover { text-decoration: none; transform: translateY(-1px); }
  .nav-support.github { border-color: #8f376f; color: #ff8ccf; background: #261727; }
  .nav-support.coffee { border-color: #d1b700; color: #171717; background: #ffdd00; }

  /* Main content */
  .main { flex: 1; padding: 24px; overflow-y: auto; max-height: 100vh; }
  .view { display: none; }
  .view.active { display: block; }
  .view h2 {
    font-size: 16px; font-weight: 600; margin-bottom: 16px;
  }

  /* Cards */
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 14px; margin-bottom: 20px;
  }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px;
  }
  .card h3 {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    color: var(--text-muted); margin-bottom: 10px; letter-spacing: 0.4px;
  }
  .card .row {
    display: flex; justify-content: space-between; padding: 3px 0;
    font-size: 13px;
  }
  .card .row .label { color: var(--text-muted); }
  .card .row .value { font-weight: 500; }
  .card .row .value.ok { color: var(--success); }
  .card .row .value.warn { color: var(--warning); }
  .card .row .value.err { color: var(--error); }

  /* Buttons */
  .btn {
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 6px 14px; border-radius: 6px;
    cursor: pointer; font-size: 13px; transition: all 0.12s;
  }
  .btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn-primary:hover { background: #4a91e0; }
  .btn-danger { background: transparent; border-color: var(--error); color: var(--error); }
  .btn-danger:hover { background: var(--error); color: #fff; }
  .btn-sm { padding: 3px 10px; font-size: 12px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }

  /* Forms */
  label { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
  input, textarea, select {
    width: 100%; padding: 7px 10px; background: var(--bg);
    border: 1px solid var(--border); border-radius: 5px;
    color: var(--text); font-size: 13px; font-family: inherit;
  }
  input:focus, textarea:focus, select:focus {
    outline: none; border-color: var(--accent);
  }
  textarea { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px; }
  .form-group { margin-bottom: 12px; }
  .form-row { display: flex; gap: 12px; }
  .form-row .form-group { flex: 1; }

  /* Log viewer */
  .log-section { margin-top: 10px; }
  .log-controls { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; align-items: center; }
  .log-controls button {
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
    padding: 3px 10px; border-radius: 4px; cursor: pointer; font-size: 12px;
  }
  .log-controls button:hover { background: var(--border); }
  .log-controls button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .live-badge { color: var(--success); font-size: 12px; margin-left: auto; }
  .recent-list { display: grid; gap: 6px; }
  .recent-call {
    display: grid; grid-template-columns: 78px 1fr 70px 70px; gap: 8px;
    align-items: center; font-size: 12px; padding: 6px 0; border-bottom: 1px solid var(--border);
  }
  .recent-call:last-child { border-bottom: 0; }
  .recent-call .ok { color: var(--success); }
  .recent-call .error { color: var(--error); }
  #log-container {
    background: #000; border: 1px solid var(--border); border-radius: 6px;
    height: 400px; overflow-y: auto; font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px; padding: 10px;
  }
  #log-container .line { padding: 3px 0; white-space: pre-wrap; word-break: break-all; cursor: pointer; }
  #log-container .line.hidden { display: none; }
  #log-container .line .detail { display: none; color: var(--text-muted); padding: 4px 0 4px 18px; }
  #log-container .line.expanded .detail { display: block; }
  #log-container .line.debug { color: var(--text-muted); }
  #log-container .line.info { color: var(--info); }
  #log-container .line.warning { color: var(--warning); }
  #log-container .line.error { color: var(--error); }
  #log-container .line.critical { color: var(--error); font-weight: bold; }

  /* Tools catalog */
  .tool-search { margin-bottom: 12px; }
  .tool-layout {
    display: grid; grid-template-columns: minmax(280px, 1fr) minmax(300px, 0.9fr);
    gap: 12px; align-items: start;
  }
  .tool-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 10px;
  }
  .tool-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 12px;
  }
  .tool-card h4 { font-size: 13px; margin-bottom: 4px; }
  .tool-card.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
  .tool-card .tool-desc { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
  .tool-card .tool-meta { font-size: 11px; color: var(--text-muted); }
  .tool-card .tool-meta span { margin-right: 12px; }
  .tool-card .tool-params {
    margin-top: 8px; font-size: 11px; background: var(--bg);
    padding: 6px 8px; border-radius: 4px; max-height: 120px; overflow-y: auto;
  }
  .tool-card .tool-params code {
    color: var(--info); font-family: 'JetBrains Mono', monospace;
  }
  .tool-detail { position: sticky; top: 16px; }
  .tool-detail pre {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 10px; font-size: 11px; overflow: auto; max-height: 260px;
  }
  @media (max-width: 900px) {
    .tool-layout { grid-template-columns: 1fr; }
    .tool-detail { position: static; }
  }

  /* Setup wizard */
  .wizard-steps {
    display: flex; gap: 0; margin-bottom: 24px;
    border-bottom: 1px solid var(--border); padding-bottom: 12px;
  }
  .wizard-step {
    flex: 1; text-align: center; font-size: 12px; color: var(--text-muted);
    padding: 8px; position: relative;
  }
  .wizard-step .step-num {
    display: inline-flex; width: 22px; height: 22px; border-radius: 50%;
    background: var(--border); color: var(--text-muted); align-items: center;
    justify-content: center; font-size: 11px; font-weight: 600; margin-bottom: 4px;
  }
  .wizard-step.active .step-num { background: var(--accent); color: #fff; }
  .wizard-step.completed .step-num { background: var(--success); color: #fff; }
  .wizard-step.active { color: var(--text); font-weight: 500; }
  .wizard-step.completed { color: var(--success); }
  .wizard-body { min-height: 200px; }
  .wizard-nav { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
  .wizard-result {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 12px; margin-top: 12px;
    font-size: 13px; white-space: pre-wrap; max-height: 200px; overflow-y: auto;
    font-family: 'JetBrains Mono', monospace;
  }
  .wizard-result.success { border-color: var(--success); }
  .wizard-result.error { border-color: var(--error); }

  /* Messages */
  .msg {
    padding: 8px 12px; border-radius: 6px; margin-bottom: 10px;
    font-size: 13px;
  }
  .msg.info { background: rgba(88,166,255,0.12); border: 1px solid var(--accent); color: var(--info); }
  .msg.success { background: rgba(63,185,80,0.12); border: 1px solid var(--success); color: var(--success); }
  .msg.warn { background: rgba(210,153,34,0.12); border: 1px solid var(--warning); color: var(--warning); }
  .msg.error { background: rgba(248,81,73,0.12); border: 1px solid var(--error); color: var(--error); }

  /* Spinner */
  .spinner {
    display: inline-block; width: 16px; height: 16px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { text-align: center; padding: 40px; color: var(--text-muted); }

  /* Responsive */
  @media (max-width: 700px) {
    body { flex-direction: column; }
    .sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; padding: 8px 12px;
      border-right: none; border-bottom: 1px solid var(--border); }
    .sidebar .brand { border-bottom: none; margin-bottom: 0; padding: 0; }
    .sidebar .status-row { display: none; }
    .nav-item { padding: 6px 10px; border-left: none; border-bottom: 2px solid transparent; }
    .nav-item.active { border-left-color: transparent; border-bottom-color: var(--accent); }
    .nav-support-group { display: flex; width: 100%; gap: 6px; padding-top: 4px; margin-top: 0; }
    .nav-support-group .nav-label { display: none; }
    .nav-support { margin: 0; padding: 6px 9px; border-bottom-width: 1px; }
    .main { padding: 16px; max-height: none; }
  }
</style>
</head>
<body>

<!-- Sidebar -->
<nav class="sidebar">
  <div class="brand">
    <span class="status-dot ok" id="navStatusDot"></span>
    <h1>KiCad MCP Pro</h1>
    <span class="badge" id="navVersion">v{{version}}</span>
  </div>
  <div class="status-row" id="navStatusText">Checking...</div>
  <div class="nav-item active" data-view="dashboard">&#9664; Dashboard</div>
  <div class="nav-item" data-view="log-viewer">&#9776; Logs</div>
  <div class="nav-item" data-view="tools-catalog">&#9881; Tools</div>
  <div class="nav-item" data-view="preview">&#128444; Preview</div>
  <div class="nav-item" data-view="settings">&#9878; Settings</div>
  <div class="nav-item" data-view="setup-wizard">&#9889; Setup</div>
  <div class="nav-sep"></div>
  <div class="nav-label">AI Agents</div>
  <a class="nav-item" href="https://oaslananka.github.io/kicad-mcp-pro/agents/" target="_blank" rel="noopener noreferrer">&#129302; Agent Setup &#8599;</a>
  <a class="nav-item" href="https://oaslananka.github.io/kicad-mcp-pro/agents/prompts/" target="_blank" rel="noopener noreferrer">&#128172; Prompt Library &#8599;</a>
  <div class="nav-support-group">
    <div class="nav-label">Support</div>
    <a class="nav-item nav-support github" href="https://github.com/sponsors/oaslananka" target="_blank" rel="noopener noreferrer" aria-label="Support KiCad MCP Pro through GitHub Sponsors">&#9829; GitHub Sponsors &#8599;</a>
    <a class="nav-item nav-support coffee" href="https://www.buymeacoffee.com/oaslananka" target="_blank" rel="noopener noreferrer" aria-label="Support KiCad MCP Pro through Buy me a coffee">&#9749; Buy me a coffee &#8599;</a>
  </div>
</nav>

<!-- Main content -->
<div class="main" id="mainContent">

  <!-- Dashboard -->
  <div class="view active" id="view-dashboard">
    <h2>Dashboard</h2>
    <div class="grid" id="statusGrid">
      <div class="card"><h3>Server</h3>
        <div class="row"><span class="label">Profile</span><span class="value" id="s-profile">-</span></div>
        <div class="row"><span class="label">Mode</span><span class="value" id="s-mode">-</span></div>
        <div class="row"><span class="label">Transport</span><span class="value" id="s-transport">-</span></div>
        <div class="row"><span class="label">Host</span><span class="value" id="s-host">-</span></div>
        <div class="row"><span class="label">Port</span><span class="value" id="s-port">-</span></div>
        <div class="row"><span class="label">Uptime</span><span class="value" id="s-uptime">-</span></div>
      </div>
      <div class="card"><h3>KiCad</h3>
        <div class="row"><span class="label">CLI</span><span class="value" id="k-cli">-</span></div>
        <div class="row"><span class="label">Version</span><span class="value" id="k-version">-</span></div>
        <div class="row"><span class="label">IPC</span><span class="value" id="k-ipc">-</span></div>
      </div>
      <div class="card"><h3>Project</h3>
        <div class="row"><span class="label">Directory</span><span class="value" id="p-dir">-</span></div>
        <div class="row"><span class="label">PCB</span><span class="value" id="p-pcb">-</span></div>
        <div class="row"><span class="label">SCH</span><span class="value" id="p-sch">-</span></div>
      </div>
      <div class="card"><h3>Health</h3>
        <div id="health-checks"></div>
        <div class="row" style="margin-top:8px; padding-top:6px; border-top:1px solid var(--border);">
          <span class="label">Overall</span><span class="value" id="health-overall">-</span>
        </div>
      </div>
    </div>
    <div class="card"><h3>Quick Actions</h3>
      <div class="actions">
        <button class="btn btn-sm btn-primary" onclick="serverAction('start')">Start</button>
        <button class="btn btn-sm" onclick="serverAction('stop')">Stop</button>
        <button class="btn btn-sm" onclick="serverAction('restart')">Restart</button>
        <button class="btn btn-sm" onclick="refreshStatus()">Refresh Status</button>
        <button class="btn btn-sm" onclick="window.open('/api/status','_blank')">Status JSON</button>
        <button class="btn btn-sm" onclick="window.open('/api/metrics','_blank')">Metrics JSON</button>
        <button class="btn btn-sm" onclick="window.open('/api/health','_blank')">Health JSON</button>
        <button class="btn btn-sm" onclick="window.location.hash='#/logs'">All Logs</button>
      </div>
      <div id="action-msg" style="margin-top:8px;font-size:13px;"></div>
    </div>
    <div class="card" style="margin-top:14px;"><h3>Recent Tool Calls</h3>
      <div class="recent-list" id="recent-calls">
        <div class="row"><span class="label">No tool calls yet.</span><span class="value">Live</span></div>
      </div>
    </div>
  </div>

  <!-- Log Viewer -->
  <div class="view" id="view-log-viewer">
    <h2>Log Viewer</h2>
    <div class="log-controls">
      <input type="text" id="logSearch" placeholder="Search logs or /regex/" oninput="applyLogFilters()" style="max-width:220px;">
      <button class="active" data-level="all" onclick="setLogFilter('all',this)">All</button>
      <button data-level="debug" onclick="setLogFilter('debug',this)">Debug</button>
      <button data-level="info" onclick="setLogFilter('info',this)">Info</button>
      <button data-level="warning" onclick="setLogFilter('warning',this)">Warn</button>
      <button data-level="error" onclick="setLogFilter('error',this)">Error</button>
      <button onclick="downloadLogs()">Download</button>
      <button onclick="clearLog()">Clear</button>
      <button id="jumpBottom" onclick="jumpToBottom()" style="display:none;">Go Bottom</button>
      <span class="live-badge" id="live-badge" data-testid="live-badge">Connecting</span>
    </div>
    <div id="log-container"><div class="line" style="color:var(--text-muted)">Connecting to log stream...</div></div>
  </div>

  <!-- Tools Catalog -->
  <div class="view" id="view-tools-catalog">
    <h2>Tools Catalog</h2>
    <div class="tool-search form-row">
      <input type="text" id="toolSearch" placeholder="Search tools by name or keyword..." oninput="filterTools()">
      <select id="toolCategory" onchange="filterTools()" style="max-width:180px;">
        <option value="all">All categories</option>
      </select>
    </div>
    <div id="tools-loading" class="loading"><div class="spinner"></div> Loading tools...</div>
    <div id="tools-count" style="font-size:12px;color:var(--text-muted);margin-bottom:8px;display:none;"></div>
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
    <div id="settings-msg"></div>
    <form id="settingsForm" onsubmit="saveSettings(event)">
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
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">Takes effect after restart.</div>
        </div>
      </div>
      <div class="actions">
        <button type="submit" class="btn btn-primary">Save Settings</button>
        <button type="button" class="btn" onclick="loadSettings()">Discard Changes</button>
      </div>
    </form>
    <div style="margin-top:20px;">
      <h3 style="font-size:13px;font-weight:600;margin-bottom:8px;">Export Client Config</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-sm" onclick="exportClientConfig('claude')">Claude Desktop</button>
        <button class="btn btn-sm" onclick="exportClientConfig('cursor')">Cursor</button>
        <button class="btn btn-sm" onclick="exportClientConfig('vscode')">VS Code</button>
        <button class="btn btn-sm" onclick="exportClientConfig('windsurf')">Windsurf</button>
        <button class="btn btn-sm" onclick="exportClientConfig('zed')">Zed</button>
      </div>
      <pre id="export-result" style="display:none;margin-top:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px;font-size:12px;overflow-x:auto;"></pre>
    </div>
  </div>

  <!-- Setup Wizard -->
  <div class="view" id="view-setup-wizard">
    <h2>Setup Wizard</h2>
    <div class="wizard-steps" id="wizardSteps">
      <div class="wizard-step active" data-step="0"><div class="step-num">1</div>KiCad Detection</div>
      <div class="wizard-step" data-step="1"><div class="step-num">2</div>Project</div>
      <div class="wizard-step" data-step="2"><div class="step-num">3</div>Transport</div>
      <div class="wizard-step" data-step="3"><div class="step-num">4</div>Client Config</div>
      <div class="wizard-step" data-step="4"><div class="step-num">5</div>Test &amp; Finish</div>
    </div>
    <div id="wizardMsg"></div>
    <div class="wizard-body" id="wizardBody"></div>
    <div class="wizard-nav" id="wizardNav"></div>
  </div>

</div>

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
    sd.className = 'status-dot ' + (hl.ok ? 'ok' : 'degraded');
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
    byId('live-badge').textContent = 'Live';
  };
  eventSource.onmessage = function(e) { addLogLine(e.data); };
  eventSource.addEventListener('log', function(e) { addLogLine(e.data); });
  eventSource.onerror = function() {
    byId('live-badge').textContent = 'Retrying in ' + Math.round(sseReconnectMs / 1000) + 's';
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
    '<div class="recent-call"><span>' + esc(c.time) + '</span><span>' +
    esc(c.tool) + '</span><span class="' + esc(c.status) + '">' +
    esc(c.status) + '</span><span>' + esc(c.latency || '') + '</span></div>'
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
        '<span>' + esc(t.category || toolCategory(t)) + '</span>' +
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
    '<p style="font-size:13px;color:var(--text-muted);margin-bottom:10px;">' + esc(tool.description || 'No description') + '</p>' +
    '<div class="row"><span class="label">Category</span><span class="value">' + esc(tool.category || toolCategory(tool)) + '</span></div>' +
    '<div class="row"><span class="label">Parameters</span><span class="value">' + Object.keys(params).length + '</span></div>' +
    '<pre>' + esc(JSON.stringify({required, properties: params}, null, 2)) + '</pre>' +
    '<div class="actions"><button class="btn btn-sm btn-primary" onclick="testSelectedTool()">Test</button>' +
    '<button class="btn btn-sm" onclick="copySelectedSchema()">Copy Schema</button></div>' +
    '<div id="tool-test-result" style="margin-top:10px;"></div>';
  renderTools((window._allTools || []).filter(t => {
    const q = byId('toolSearch').value.toLowerCase();
    const category = byId('toolCategory').value;
    return (!q || t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q)) &&
      (category === 'all' || t.category === category);
  }));
}

function copySelectedSchema() {
  if (!selectedTool) return;
  navigator.clipboard.writeText(JSON.stringify(selectedTool.inputSchema || {}, null, 2));
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
        '<div style="background:#fff;border-radius:4px;padding:6px;margin-bottom:8px;">' +
        '<img src="' + esc(url) + '" alt="Schematic preview" style="width:100%;display:block;">' +
        '</div>' +
        '<div style="font-size:12px;font-weight:600;">' + esc(name) + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted);">' + esc(ts) + '</div>';
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
      nav.innerHTML = '<button class="btn" onclick="cancelWizard()">Cancel</button><button class="btn btn-primary" onclick="wizardNext()">Next: Project &raquo;</button>';
      break;

    case 1:
      body.innerHTML =
        '<div class="form-group"><label>Default KiCad Project Directory</label>' +
        '<div style="display:flex;gap:6px;">' +
        '<input type="text" id="wizProjectDir" value="" placeholder="~/KiCad" style="flex:1;">' +
        '<button class="btn btn-sm" onclick="browseProjectDir()" style="white-space:nowrap;flex-shrink:0;">Browse</button>' +
        '</div></div>' +
        '<div class="msg info">PCB and schematic files in this directory can be offered to tools automatically.</div>';
      nav.innerHTML = '<button class="btn" onclick="wizardPrev()">&laquo; Back</button><button class="btn btn-primary" onclick="wizardNext()">Next: Transport &raquo;</button>';
      break;

    case 2:
      body.innerHTML =
        '<div class="form-group"><label>Transport Mode</label>' +
        '<select id="wizTransport"><option value="streamable-http" selected>streamable-http (recommended)</option><option value="stdio">stdio (stdin/stdout)</option></select></div>' +
        '<div class="form-group" id="wizPortGroup"><label>Port (HTTP only)</label><input type="number" id="wizPort" value="3334" min="1" max="65535"></div>' +
        '<div class="form-group"><label>Host (HTTP only)</label><input type="text" id="wizHost" value="127.0.0.1"></div>';
      document.getElementById('wizTransport').addEventListener('change', function() {
        document.getElementById('wizPortGroup').style.display = this.value !== 'stdio' ? 'block' : 'none';
      });
      nav.innerHTML = '<button class="btn" onclick="wizardPrev()">&laquo; Back</button><button class="btn btn-primary" onclick="wizardNext()">Next: Client Config &raquo;</button>';
      break;

    case 3:
      body.innerHTML =
        '<div class="form-group"><label>Select MCP Client</label>' +
        '<select id="wizClient"><option value="claude-desktop">Claude Desktop</option><option value="cursor">Cursor</option><option value="vscode">VS Code</option><option value="windsurf">Windsurf</option><option value="zed">Zed</option></select></div>' +
        '<div id="wizConfigPreview" class="wizard-result" style="display:none;"></div>' +
        '<div class="actions" style="margin-top:8px;">' +
        '<button class="btn btn-sm" onclick="previewClientConfig()">Preview Config</button>' +
        '<button class="btn btn-sm" onclick="copyClientConfig()">Copy to Clipboard</button></div>';
      nav.innerHTML = '<button class="btn" onclick="wizardPrev()">&laquo; Back</button><button class="btn btn-primary" onclick="wizardNext()">Next: Test &amp; Finish &raquo;</button>';
      break;

    case 4:
      body.innerHTML =
        '<div class="msg info">Your KiCad MCP Pro is ready to use!</div>' +
        '<div id="testResult" class="wizard-result" style="display:none;"></div>' +
        '<div class="actions" style="margin-top:12px;">' +
        '<button class="btn btn-sm btn-primary" onclick="testConnection()">Test Connection</button></div>';
      nav.innerHTML = '<button class="btn" onclick="wizardPrev()">&laquo; Back</button><button class="btn btn-success" onclick="finishWizard()">Finish</button>';
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
  // Try Tauri IPC (available when running inside Tauri webview)
  if (window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === 'function') {
    window.__TAURI_INTERNALS__.invoke('select_working_dir').then(function(path) {
      if (path) input.value = path;
    }).catch(function() { fallbackBrowseDir(input); });
  } else {
    fallbackBrowseDir(input);
  }
}
function fallbackBrowseDir(input) {
  var picker = document.createElement('input');
  picker.type = 'file';
  picker.setAttribute('webkitdirectory', '');
  picker.style.display = 'none';
  picker.addEventListener('change', function() {
    if (this.files && this.files.length > 0) {
      // Extract directory path from the first selected file
      var p = this.files[0].path || this.files[0].webkitRelativePath;
      if (p) {
        // webkitRelativePath is like "folder/sub/file", take first component
        var idx = p.indexOf('/');
        if (idx > 0) p = p.substring(0, idx);
        // full path includes the parent folder name from path property
        if (this.files[0].path) {
          var lastSlash = this.files[0].path.lastIndexOf('\\');
          if (lastSlash > 0) p = this.files[0].path.substring(0, lastSlash);
          else p = this.files[0].path;
        }
        input.value = p;
      }
    }
  });
  document.body.appendChild(picker);
  picker.click();
  setTimeout(function() { document.body.removeChild(picker); }, 200);
}

function wizardNext() {
  const steps = document.querySelectorAll('.wizard-step');
  if (wizardStep < steps.length - 1) {
    steps[wizardStep].classList.remove('active');
    steps[wizardStep].classList.add('completed');
    wizardStep++;
    steps[wizardStep].classList.add('active');
    renderWizardStep(wizardStep);
  }
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
  el.innerHTML = '<div class="msg ' + (type || 'info') + '">' + esc(text) + '</div>';
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
