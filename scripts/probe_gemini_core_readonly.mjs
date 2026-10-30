#!/usr/bin/env node
/**
 * Model-free, deliberately narrow probe through the installed Gemini CLI core.
 * Not an interactive Gemini CLI session or a full native-host acceptance.
 */
import { createHash } from 'node:crypto';
import { constants as fsConstants } from 'node:fs';
import {
  lstat, mkdtemp, open, readdir, realpath, rm,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const SOURCE = path.resolve(import.meta.dirname, '..');
const EVIDENCE_SCHEMA = 'gemini-core-readonly-diagnostic.v1';
const HOST_VERSION = '0.60.0';
const PINNED_CORE_SHA256 = '82bbf0bd5c3c0040b6b454d7977a0c03c4fee6ae7b8891f282c7e7c896567ab5';
const TOOL = 'kicad_get_server_info';
const MAX_DISCOVERY = 256;
const MAX_FILE_BYTES = 64 * 1024 * 1024;
const REQUIRED_ARGS = [
  '--from', 'kicad-mcp-pro==4.4.0', 'kicad-mcp-pro', '--transport', 'stdio',
];

function fail(message) {
  throw new Error(message);
}

// Preserve the historical JS default sort order for the source-bound JSON
// evidence, but provide an explicit comparator as required by Sonar S2871.
function compareToolNames(a, b) {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

/**
 * Read one bounded, regular file using a handle opened without following the
 * final symlink. The additional lstat is necessary on platforms without
 * O_NOFOLLOW, and verifies the intended file before the handle is opened.
 * User-controlled paths are never concatenated as child filenames.
 */
async function readVerifiedFile(filename) {
  const before = await lstat(filename);
  if (before.isSymbolicLink() || !before.isFile() || before.size > MAX_FILE_BYTES) {
    fail('Refusing symlink, nonregular or oversized Gemini file');
  }
  const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0);
  const handle = await open(filename, flags);
  try {
    const after = await handle.stat();
    if (!after.isFile() || after.size > MAX_FILE_BYTES ||
        after.dev !== before.dev || after.ino !== before.ino) {
      fail('Gemini file identity changed while opening');
    }
    return await handle.readFile();
  } finally {
    await handle.close();
  }
}

async function exists(filename) {
  try {
    await lstat(filename);
    return true;
  } catch (err) {
    if (err?.code === 'ENOENT') return false;
    throw err;
  }
}

async function getEntry(args) {
  if (args.length !== 2 || args[0] !== '--gemini-entry' || !path.isAbsolute(args[1])) {
    fail('Usage: node scripts/probe_gemini_core_readonly.mjs --gemini-entry /absolute/trusted/gemini.js');
  }
  // The caller explicitly selects a local installed CLI; resolve the
  // entrypoint and only accept the official package identity/version.
  const entry = await realpath(args[1]);
  if (path.basename(entry) !== 'gemini.js' || path.basename(path.dirname(entry)) !== 'bundle') {
    fail('Gemini entry must resolve to a trusted @google/gemini-cli/bundle/gemini.js');
  }
  const pkgFile = path.resolve(path.dirname(entry), '..', 'package.json');
  const pkg = JSON.parse((await readVerifiedFile(pkgFile)).toString('utf8'));
  if (pkg.name !== '@google/gemini-cli' || pkg.version !== HOST_VERSION) {
    fail('Installed Gemini CLI identity/version mismatch');
  }
  return entry;
}

async function verifyManifest() {
  // A fixed repository-relative manifest: not a user-supplied path.
  const manifestPath = path.join(
    SOURCE, 'integrations/gemini-cli/kicad-mcp-pro/gemini-extension.json'
  );
  const manifest = JSON.parse((await readVerifiedFile(manifestPath)).toString('utf8'));
  const server = manifest.mcpServers?.kicad;
  const pkg = JSON.parse((await readVerifiedFile(path.join(SOURCE, 'package.json'))).toString('utf8'));
  const currentVersion = pkg.version;
  const currentArgs = [
    '--from', `kicad-mcp-pro==${currentVersion}`, 'kicad-mcp-pro', '--transport', 'stdio',
  ];
  // The probe keeps its historical 4.4.0 runtime pin; only the checked-in
  // extension metadata advances when preparing a new release candidate.
  if (typeof currentVersion !== 'string' ||
      !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(currentVersion) ||
      manifest.version !== currentVersion || server?.command !== 'uvx' ||
      JSON.stringify(server.args) !== JSON.stringify(currentArgs) ||
      server.env?.KICAD_MCP_PROFILE !== 'default' ||
      server.env?.KICAD_MCP_OPERATING_MODE !== 'readonly' ||
      server.trust === true) {
    fail('Source Gemini extension readonly/pinned config drift');
  }
}

function isAllowedPlatformBootstrap(key) {
  // Replacement-env Node subprocesses still receive CoreFoundation's text
  // encoding marker on macOS. Require its bounded numeric OS format.
  if (process.platform === 'darwin' && key === '__CF_USER_TEXT_ENCODING') {
    return /^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$/.test(process.env[key]);
  }
  // Windows Node/V8 startup requires SystemRoot even when the caller sets a
  // minimal environment. This is an OS directory, never a provider credential.
  if (process.platform === 'win32' && key.toLowerCase() === 'systemroot') {
    return path.win32.isAbsolute(process.env[key] ?? '');
  }
  return false;
}

function validateMinimalEnvironment() {
  // Gemini's stdio transport may forward inherited environment variables.
  // Refuse all unexpected keys rather than relying on token redaction.
  const allowedEnvironment = new Set([
    'HOME', 'USER', 'LOGNAME', 'PATH', 'UV_PYTHON', 'LANG', 'LC_ALL',
    'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'TMPDIR',
  ]);
  const inherited = Object.keys(process.env).filter(
    (key) => !allowedEnvironment.has(key) && !isAllowedPlatformBootstrap(key)
  );
  if (inherited.length) fail('Refusing inherited provider credential or project environment');
}

async function loadPinnedGeminiCore(entry) {
  const bundle = path.dirname(entry);
  // A matching class name is insufficient: inspect regular files using
  // symlink-resistant handles and pin the Gemini core SHA before any import.
  const modules = (await readdir(bundle)).filter(
    (v) => /^core-[A-Za-z0-9_-]+\.js$/.test(v)
  );
  if (modules.length < 1 || modules.length > 6) fail('Unexpected bundled Gemini core layout');
  // Max six strict-basename candidates; bounded regular-file reads and hashes
  // can be performed concurrently without serial await-in-loop, while never
  // importing any candidate before the exact digest is confirmed.
  const scanned = await Promise.all(modules.map(async (filename) => {
    const corePath = path.join(bundle, filename);
    const bytes = await readVerifiedFile(corePath);
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    return {corePath, sha256};
  }));
  const eligible = scanned.filter(({sha256}) => sha256 === PINNED_CORE_SHA256);
  if (eligible.length !== 1) fail('Installed Gemini core exact SHA-256 mismatch');
  const {corePath, sha256} = eligible[0];
  // Unverified sibling core files are never imported; transitive imports
  // remain outside this independent process-attestation boundary.
  const core = await import(pathToFileURL(corePath));
  if (typeof core.McpClient !== 'function') fail('Verified Gemini core does not export McpClient');
  return {core, sha256};
}

async function probe(entry) {
  await verifyManifest();
  validateMinimalEnvironment();
  const temp = await mkdtemp(path.join(os.tmpdir(), 'gemini-core-readonly-'));
  const oldLog = console.log;
  let mcp;
  let result;
  try {
    console.log = () => {};
    const {core, sha256} = await loadPinnedGeminiCore(entry);
    const workspace = {
      getDirectories: () => [temp],
      onDirectoriesChanged: () => () => {},
    };
    const cliConfig = {
      // Only the freshly created workspace is trusted to start stdio.
      // Gemini MCP tool trust stays FALSE, as in the reviewed extension.
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
    // This is an explicit operator-approved, no-argument Gemini core tool
    // invocation, NOT an interactive Gemini UI/model-selected agent turn.
    const invocation = diagnostic[0].createInvocation({}, undefined);
    const response = await invocation.execute({ abortSignal: new AbortController().signal });
    if (response?.error || !response?.returnDisplay) fail('Gemini core diagnostic failed');
    if (await exists(env.KICAD_API_SOCKET)) fail('Unexpected attachment to a KiCad IPC socket');
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
      discoveredTools: [...names].sort(compareToolNames),
      missingReadOnlyAnnotations: tools
        .filter((t) => t.toolAnnotations?.readOnlyHint !== true)
        .map((t) => t.serverToolName).sort(compareToolNames),
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
      await rm(temp, { recursive: true, force: true });
      console.log = oldLog;
    }
  }
  result.temporaryEnvironmentRemoved = !(await exists(temp));
  if (!result.temporaryEnvironmentRemoved) fail('Temporary workspace cleanup failed');
  return result;
}

try {
  const result = await probe(await getEntry(process.argv.slice(2)));
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
} catch (error) {
  process.stderr.write('Gemini core readonly probe failed: ' +
    (error instanceof Error ? error.message : 'unknown error') + '\n');
  process.exitCode = 1;
}
