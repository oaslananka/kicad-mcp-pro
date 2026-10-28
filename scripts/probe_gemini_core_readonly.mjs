#!/usr/bin/env node
/**
 * Model-free, deliberately narrow probe through the *installed Gemini CLI core*.
 * This is not an interactive Gemini CLI session or a full native-host acceptance.
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const SOURCE = path.resolve(import.meta.dirname, '..');
const EVIDENCE_SCHEMA = 'gemini-core-readonly-diagnostic.v1';
const HOST_VERSION = '0.60.0';
const PINNED_CORE_SHA256 = '82bbf0bd5c3c0040b6b454d7977a0c03c4fee6ae7b8891f282c7e7c896567ab5';
const TOOL = 'kicad_get_server_info';
const MAX_DISCOVERY = 256;
const REQUIRED_ARGS = [
  '--from', 'kicad-mcp-pro==4.4.0', 'kicad-mcp-pro', '--transport', 'stdio',
];

function fail(message) {
  throw new Error(message);
}

function getEntry(args) {
  if (args.length !== 2 || args[0] !== '--gemini-entry' || !path.isAbsolute(args[1])) {
    fail('Usage: node scripts/probe_gemini_core_readonly.mjs --gemini-entry /absolute/trusted/gemini.js');
  }
  // Security review: absolute, operator-supplied installed CLI path;
  // the resolved filename, package identity and an immutable bundled core SHA are checked.
  const entry = fs.realpathSync(args[1]); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
  if (path.basename(entry) !== 'gemini.js' || path.basename(path.dirname(entry)) !== 'bundle') {
    fail('Gemini entry must resolve to a trusted @google/gemini-cli/bundle/gemini.js');
  }
  const pkgFile = path.join(path.dirname(entry), '..', 'package.json');
  if (fs.lstatSync(pkgFile).isSymbolicLink()) fail('Symlinked Gemini package metadata refused'); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
  // Security review: derives from verified resolved bundle entry,
  // with package metadata symlink rejected and installed identity/version checked.
  const pkg = JSON.parse(fs.readFileSync(pkgFile, 'utf8')); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
  if (pkg.name !== '@google/gemini-cli' || pkg.version !== HOST_VERSION) {
    fail('Installed Gemini CLI identity/version mismatch');
  }
  return entry;
}

function verifyManifest() {
  const manifestPath = path.join(SOURCE, 'integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json');
  // Security review: fixed reviewed repository-relative manifest.
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
  const server = manifest.mcpServers?.kicad;
  if (manifest.version !== '4.4.0' || server?.command !== 'uvx' ||
      JSON.stringify(server.args) !== JSON.stringify(REQUIRED_ARGS) ||
      server.env?.KICAD_MCP_PROFILE !== 'default' ||
      server.env?.KICAD_MCP_OPERATING_MODE !== 'readonly' ||
      server.trust === true) {
    fail('Source Gemini extension readonly/pinned config drift');
  }
}

async function probe(entry) {
  verifyManifest();
  // The Gemini stdio transport forwards inherited environment variables to
  // its child. Reject any ambient user-project, credential or arbitrary env
  // rather than relying on Gemini's own redactor for a trust-boundary test.
  const allowedEnvironment = new Set([
    'HOME', 'USER', 'LOGNAME', 'PATH', 'UV_PYTHON', 'LANG', 'LC_ALL',
    'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'TMPDIR',
  ]);
  const inherited = Object.keys(process.env).filter((key) => !allowedEnvironment.has(key));
  if (inherited.length) fail('Refusing inherited provider credential or project environment');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'gemini-core-readonly-'));
  const oldLog = console.log;
  let mcp;
  let result;
  try {
    const bundle = path.dirname(entry);
    // A module with the expected class name is NOT enough: check immutable
    // upstream module bytes before executing ANY imported Gemini core code.
    // Refuse symlinks, unknown/hijacked bundle modules and digest drift.
    // Security review: bundle comes from an explicitly
    // nominated installed entry and is never combined with untrusted tool names.
    const modules = fs.readdirSync(bundle).filter((v) => /^core-[A-Za-z0-9_-]+\.js$/.test(v)); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
    if (modules.length < 1 || modules.length > 6) fail('Unexpected bundled Gemini core layout');
    const eligible = [];
    for (const filename of modules) {
      const corePath = path.join(bundle, filename);
      if (fs.lstatSync(corePath).isSymbolicLink()) fail('Symlinked Gemini core module refused'); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
      // Security review: basename allowlisted above;
      // no module is executed until its bytes equal the pinned trusted digest.
      const sha256 = createHash('sha256').update(fs.readFileSync(corePath)).digest('hex'); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
      if (sha256 === PINNED_CORE_SHA256) eligible.push({corePath, sha256});
    }
    if (eligible.length !== 1) fail('Installed Gemini core exact SHA-256 mismatch');
    const {corePath, sha256} = eligible[0];
    // Avoid importing any untrusted, unverified sibling core-*.js files.
    console.log = () => {};
    const core = await import(pathToFileURL(corePath));
    if (typeof core.McpClient !== 'function') fail('Verified Gemini core does not export McpClient');
    const workspace = {
      getDirectories: () => [temp],
      onDirectoriesChanged: () => () => {},
    };
    const cliConfig = {
      // Only the freshly created temporary directory is treated as trusted to
      // start stdio. Tool trust remains FALSE (as in the reviewed extension).
      isTrustedFolder: () => true,
      sanitizationConfig: {},
      emitMcpDiagnostic: (level) => { if (level === 'error') fail('Gemini core MCP diagnostic error'); },
      setUserInteractedWithMcp: () => {},
    };
    const env = {
      KICAD_MCP_PROFILE: 'default',
      KICAD_MCP_OPERATING_MODE: 'readonly',
      KICAD_API_SOCKET: path.join(temp, 'unbound-kicad-ipc.sock'),
      UV_CACHE_DIR: path.join(temp, 'uv-cache'),
      UV_PYTHON_DOWNLOADS: 'never',
      UV_INDEX_URL: 'https://pypi.org/simple',
    };
    // Do not pass a user's Gemini config, project, API token or KiCad socket.
    mcp = new core.McpClient('kicad', {
      command: 'uvx', args: REQUIRED_ARGS, env, timeout: 30_000, trust: false,
      cwd: temp,
    }, workspace, cliConfig, false, HOST_VERSION);
    await mcp.connect();
    if (mcp.getStatus() !== 'connected') fail('Native Gemini core MCP connection failed');
    const tools = await mcp.discoverTools(cliConfig, undefined);
    if (!tools.length || tools.length > MAX_DISCOVERY) fail('Unexpected discovered tool count');
    const names = tools.map((t) => t.serverToolName);
    if (new Set(names).size !== names.length || names.some((n) => typeof n !== 'string')) {
      fail('Duplicate/invalid discovered native tool');
    }
    const diagnostic = tools.filter((t) => t.serverToolName === TOOL);
    if (diagnostic.length !== 1) fail('Missing/duplicate expected readonly diagnostic tool');
    // Invoking exactly the reviewed, no-argument diagnostic through Gemini's
    // DiscoveredMCPToolInvocation, not a generic MCP SDK client. This is an
    // explicit operator-approved probe; no agent/model turn or Gemini UI consent.
    const invocation = diagnostic[0].createInvocation({}, undefined);
    const response = await invocation.execute({ abortSignal: new AbortController().signal });
    if (response?.error || !response?.returnDisplay) fail('Gemini core diagnostic failed');
    // Security review: internally constructed under unique temp.
    if (fs.existsSync(env.KICAD_API_SOCKET)) fail('Unexpected attachment to a KiCad IPC socket'); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
    result = {
      schemaVersion: EVIDENCE_SCHEMA,
      hostPackage: '@google/gemini-cli',
      hostVersion: HOST_VERSION,
      hostCoreSha256: sha256,
      actualInvocationPath: 'McpClient.discoverTools/DiscoveredMCPToolInvocation.execute',
      launchArgs: REQUIRED_ARGS,
      transport: 'stdio',
      operatingMode: 'readonly',
      profile: 'default',
      connected: true,
      discoveredTools: [...names].sort(),
      missingReadOnlyAnnotations: tools
        .filter((t) => t.toolAnnotations?.readOnlyHint !== true)
        .map((t) => t.serverToolName).sort(),
      calledOnly: TOOL,
      responseError: false,
      responsePresent: true,
      rawResponseRetained: false,
      modelTurnStarted: false,
      hostCliInteractiveSession: false,
      independentProcessAttestation: false,
      fullHostAcceptance: false,
      kiCadIpcSocketCreated: false,
    };
  } finally {
    try { await mcp?.disconnect(); } finally {
      fs.rmSync(temp, { recursive: true, force: true });
      console.log = oldLog;
    }
  }
  // Security review: checked temp was generated by mkdtempSync.
  result.temporaryEnvironmentRemoved = !fs.existsSync(temp); // nosemgrep: javascript.pathtraversal.rule-non-literal-fs-filename
  if (!result.temporaryEnvironmentRemoved) fail('Temporary workspace cleanup failed');
  return result;
}

try {
  const result = await probe(getEntry(process.argv.slice(2)));
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
} catch (error) {
  process.stderr.write('Gemini core readonly probe failed: ' +
    (error instanceof Error ? error.message : 'unknown error') + '\n');
  process.exitCode = 1;
}
