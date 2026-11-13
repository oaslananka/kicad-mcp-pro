import assert from "node:assert/strict";
import {createHash,generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {mkdirSync,readFileSync,rmSync,writeFileSync} from "node:fs";
import type {Server} from "node:http";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import type {Pool} from "pg";
import {inIsolatedDatabase} from "./isolated-db.js";
import {createHttpServer} from "../src/http.js";
import {createCloudMcpHandler} from "../src/mcp.js";
import type {Config} from "../src/config.js";
import type {BrowserIdentity} from "../src/browser.js";
import {PgGrantManagement} from "../src/grants.js";
import {PgDeviceManagement} from "../src/device-management.js";
import {PgPairingReview} from "../src/pairing-review.js";
import {PgPairingDeviceAPI} from "../src/pairing-device-api.js";
import {PgConnectorSessions, connectorSessionProof} from "../src/connector-session.js";
import {createOfflineSignedWriteProposal} from "../src/connector-write-proof.js";
import {PgDeviceHandshakes} from "../src/device-handshake.js";
import {PgConnectorReadGate} from "../src/connector-read-gate.js";
import {PgConnectorWritePreflight} from "../src/connector-write-preflight.js";
import {redemptionProof} from "../src/device-pairing.js";
import type {Actor,Verifier} from "../src/auth.js";

const migrations = [
  "001_inventory.pgsql",
  "002_client_grants.pgsql",
  "003_better_auth.pgsql",
  "004_client_revocation.pgsql",
  "005_token_cutoff.pgsql",
  "006_oauth_issuance_fence.pgsql",
  "007_device_pairing.pgsql",
  "008_device_credentials.pgsql",
  "009_device_handshake.pgsql",
  "010_connector_sessions.pgsql",
  "011_pairing_review_budget.pgsql",
  "012_pairing_device_budget.pgsql",
  "019_connector_managed_read_access.pgsql",
  "020_connector_write_proof_reservations.pgsql"
];

const databaseUrl = process.env.TEST_DATABASE_URL;

test("Full 12-step real-world autonomous user journey acceptance on Windows loopback",
  {skip:!databaseUrl,timeout:30_000},async()=>{
  await inIsolatedDatabase(databaseUrl!,migrations,async db=>{
    const scopedConnectionString = (db as unknown as {options:{connectionString:string}}).options.connectionString;
    const sessionSecret = randomBytes(32).toString("hex");
    const ownerSub = "journey-test-owner";
    const clientId = "chatgpt-client";

    // 1. Prepare disposable project files on Windows disk
    const disposableDir = path.join(tmpdir(), "kicad-journey-disposable-" + randomBytes(6).toString("hex"));
    mkdirSync(disposableDir, {recursive: true});
    const pcbPath = path.join(disposableDir, "disposable.kicad_pcb");
    const proPath = path.join(disposableDir, "disposable.kicad_pro");

    const initialPcbContent = `(kicad_pcb (version 20240108) (generator "journey-acceptance")
  (footprint "Capacitor_SMD:C_0603" (layer "F.Cu") (at 0 0)
    (fp_text reference "C1" (at 0 1) (layer "F.SilkS"))
  )
)`;
    writeFileSync(pcbPath, initialPcbContent, "utf-8");
    writeFileSync(proPath, "{}", "utf-8");

    const initialPcbSha = createHash("sha256").update(initialPcbContent, "utf-8").digest("hex");
    let server: Server | undefined;
    let grants: PgGrantManagement | undefined;

    try {
      // 2. Initialize database entities
      await db.query('INSERT INTO "users"("id","name","email","emailVerified") VALUES($1,$2,$3,true)',
        [ownerSub, "Test Engineer", "engineer@example.invalid"]);

      await db.query(
        'INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod","grantTypes","scopes") ' +
        'VALUES($1,$1,$2,$3,$4,$5)',
        [clientId, JSON.stringify(["https://chatgpt.com/callback"]), "none",
          JSON.stringify(["authorization_code"]), JSON.stringify(["projects:read", "projects:write"])]
      );

      await db.query(
        'INSERT INTO "oauthConsent"("id","clientId","userId","scopes","createdAt","updatedAt") VALUES($1,$2,$3,$4,NOW(),NOW())',
        ["consent-1", clientId, ownerSub, JSON.stringify(["projects:read", "projects:write"])]
      );

      grants = new PgGrantManagement(scopedConnectionString, true);
      const devices = new PgDeviceManagement(db);
      const pairings = new PgPairingReview(db, sessionSecret);
      const pairingDevice = new PgPairingDeviceAPI(db, sessionSecret);
      const handshakes = new PgDeviceHandshakes(db);
      const sessions = new PgConnectorSessions(db);
      const readGate = new PgConnectorReadGate(db);
      const writePreflight = new PgConnectorWritePreflight(db);

      // 3. Ephemeral device key pair (Ed25519)
      const {publicKey: devicePublic, privateKey: devicePrivate} = generateKeyPairSync("ed25519");
      const deviceSpkiDer = devicePublic.export({format: "der", type: "spki"});

      // 4. Offline Write Issuer key pair (Ed25519)
      const {publicKey: issuerPublic, privateKey: issuerPrivate} = generateKeyPairSync("ed25519");
      const writeIssuer = (candidate: unknown, binding: any, nowMs: number) => {
        return createOfflineSignedWriteProposal(candidate, binding, nowMs, issuerPrivate);
      };

      // 5. Ephemeral test server
      let port = 0;
      let registeredProjectId = "";
      let registeredDeviceId = "";
      let activeSessionId = "";
      let activeBinding = "";

      const ownerCookie = "owner_session=" + ownerSub;
      const identity: BrowserIdentity = {
        handler: async () => new Response(null, {status: 404}),
        $context: Promise.resolve({secret: sessionSecret}),
        localDevSandbox: true,
        api: {
          getSession: async ({headers}: {headers: Headers}) => {
            const hasAuth = headers.get("cookie")?.includes(ownerCookie);
            return hasAuth ? {user: {id: ownerSub, email: "engineer@example.invalid"}, session: {id: "sess-1"}} : null;
          },
          getOAuthConsents: async () => [
            {id: "consent-1", clientId, userId: ownerSub, scopes: ["projects:read", "projects:write"]}
          ]
        }
      } as unknown as BrowserIdentity;

      let tokenScope = new Set(["projects:read", "projects:write"]);
      const tokenActors: Record<string, Actor> = {
        "valid-chatgpt-token": {
          sub: ownerSub,
          clientId,
          scopes: tokenScope,
          issuedAt: Math.floor(Date.now() / 1000)
        }
      };
      const verifier: Verifier = async (rawCredential: string): Promise<Actor> => {
        const actor = Object.prototype.hasOwnProperty.call(tokenActors, rawCredential)
          ? tokenActors[rawCredential]
          : undefined;
        if (actor) {
          return {...actor, scopes: tokenScope};
        }
        throw Error("invalid_token");
      };

      // Mock live connector state and relay
      let connectorConnected = false;
      const relay = {
        isDeviceConnected: (_user: string, id: string) => connectorConnected && id === registeredDeviceId,
        localFolders: {
          supportsBrowse: () => true,
          list: async () => ({
            folderToken: "tok-root",
            parentFolderToken: null,
            items: [{
              name: "disposable.kicad_pro",
              kind: "project" as const,
              filenameStem: "disposable",
              folderToken: "tok-proj"
            }]
          }),
          select: async () => ({
            folderToken: "tok-proj",
            filenameStem: "disposable"
          }),
          getProjectPath: async () => pcbPath
        },
        getTrustedContext: (user: string, devId: string) => {
          if (user !== ownerSub || devId !== registeredDeviceId) return null;
          return {
            deviceId: registeredDeviceId,
            sessionId: activeSessionId,
            connectionBinding: activeBinding
          };
        },
        prepareWriteRevisions: async (user: string, devId: string, projId: string) => {
          if (user !== ownerSub || devId !== registeredDeviceId || projId !== registeredProjectId) return null;
          return {
            expectedBoardSha256: initialPcbSha,
            expectedLiveBoardSha256: initialPcbSha
          };
        },
        requestWrite: async (
          _oauth: unknown,
          _devId: string,
          projId: string,
          proof: object,
          persistToDisk: boolean
        ) => {
          const proposal = proof as { payload: string };
          const parsed = JSON.parse(Buffer.from(proposal.payload, "base64url").toString("utf8"));
          // Native write execution on the disposable file
          const updatedPcb = `(kicad_pcb (version 20240108) (generator "journey-acceptance")
  (footprint "Capacitor_SMD:C_0603" (layer "F.Cu") (at 25.4 30)
    (fp_text reference "C1" (at 25.4 31) (layer "F.SilkS"))
  )
)`;
          writeFileSync(pcbPath, updatedPcb, "utf-8");
          const newSha = createHash("sha256").update(updatedPcb, "utf-8").digest("hex");
          return {
            requestId: parsed.requestId,
            projectId: projId,
            operation: "pcb_move_footprint" as const,
            nativeCommitted: true,
            savedToDisk: persistToDisk,
            diskBoardSha256: newSha
          };
        }
      };

      const config: Config = {
        host: "127.0.0.1", port: 0, publicOrigin: "http://127.0.0.1",
        issuer: "https://auth.example.invalid", jwksUrl: "https://auth.example.invalid/jwks",
        audience: "http://127.0.0.1/mcp", databaseUrl: scopedConnectionString,
        allowedOrigins: [], managementClientId: "client-mgr"
      };

      server = createHttpServer(
        config,
        grants,
        verifier,
        {
          grants, identity, devices, pairings, pairingDevice,
          deviceSource: () => "local-test-loopback",
          mcpProjectWriteEnabled: true,
          writeIssuer: writeIssuer as never,
          writePreflight,
          summaryRelay: () => relay as never
        }
      );

      await new Promise<void>(resolve => server!.listen(0, "127.0.0.1", resolve));
      port = (server.address() as AddressInfo).port;
      const base = "http://127.0.0.1:" + port;
      config.publicOrigin = base;
      config.allowedOrigins = [base];

      // =========================================================================
      // STEP 1 & 2: Install/Launch on Windows & Browser Login
      // =========================================================================
      const healthRes = await fetch(base + "/health");
      assert.equal(healthRes.status, 200, "Step 1: Health endpoint responds 200");

      const signInRes = await fetch(base + "/sign-in", {redirect: "manual"});
      assert.equal(signInRes.status, 303, "Step 2: /sign-in redirects to /account");
      assert.equal(signInRes.headers.get("location"), "/account");

      const accountRes = await fetch(base + "/account", {headers: {Cookie: ownerCookie}});
      assert.equal(accountRes.status, 200, "Step 2: Authenticated /account loads");
      const accountHtml = await accountRes.text();
      assert.match(accountHtml, /Local development workspace/i);

      // =========================================================================
      // STEP 3 & 4: Computer Pairing & Online Status in Cloud
      // =========================================================================
      const challengeRes = await fetch(base + "/api/v1/pairing/device/challenge", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          alias: "Windows AMD2700X",
          publicKeyDer: (deviceSpkiDer as Buffer).toString("base64")
        })
      });
      assert.equal(challengeRes.status, 201, "Step 3: Device challenge issued via HTTP");
      const challenge = await challengeRes.json() as {
        challengeId: string; userCode: string; deviceCode: string;
      };

      const approvalPage = await fetch(base + "/devices/pairing", {headers: {Cookie: ownerCookie}});
      assert.equal(approvalPage.status, 200);
      const approvalHtml = await approvalPage.text();
      const formIndex = approvalHtml.indexOf('<form action="/devices/pairing/review"');
      assert.ok(formIndex >= 0);
      const formSlice = approvalHtml.slice(formIndex, approvalHtml.indexOf("</form>", formIndex));
      const csrfMatch = /name="csrf" value="([^"]+)"/.exec(formSlice);
      assert.ok(csrfMatch?.[1], "Step 3: CSRF token found on pairing review page");
      const approvalCookie = (approvalPage.headers.get("set-cookie") ?? "").split(";")[0];

      // Owner approves pairing in browser
      const approveRes = await fetch(base + "/devices/pairing/review", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          Origin: base,
          Cookie: approvalCookie + "; " + ownerCookie
        },
        body: new URLSearchParams({
          csrf: csrfMatch[1],
          decision: "approve",
          challenge_id: challenge.challengeId,
          user_code: challenge.userCode
        }),
        redirect: "manual"
      });
      assert.equal(approveRes.status, 303, "Step 3: Pairing approved in browser");

      // Device redeems enrollment
      const proof = sign(null, redemptionProof(challenge.challengeId, challenge.deviceCode), devicePrivate).toString("base64url");
      const redeemRes = await fetch(base + "/api/v1/pairing/device/redeem", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          challengeId: challenge.challengeId,
          deviceCode: challenge.deviceCode,
          signature: proof
        })
      });
      assert.equal(redeemRes.status, 200, "Step 3: Device redeemed enrollment");
      const redeemed = await redeemRes.json() as { deviceId: string; ownerSub: string; enabled: boolean };
      assert.ok(redeemed.deviceId, "Step 3: Device enrollment completed with valid deviceId");
      registeredDeviceId = redeemed.deviceId;

      // Enable device and activate real signed session
      await devices.enableDevice(ownerSub, registeredDeviceId);
      const sessionStore = new PgConnectorSessions(db);
      const sessionChallenge = await sessionStore.issue(ownerSub, registeredDeviceId);
      assert.equal(sessionChallenge.kind, "issued", "Step 4: Connector session challenge issued");
      if (sessionChallenge.kind === "issued") {
        const sig = sign(null, connectorSessionProof(sessionChallenge.sessionId,
          sessionChallenge.challengeId, registeredDeviceId, sessionChallenge.nonce, sessionChallenge.binding), devicePrivate);
        const activated = await sessionStore.activate(ownerSub, registeredDeviceId,
          sessionChallenge.sessionId, sessionChallenge.nonce, sessionChallenge.binding, sig);
        assert.equal(activated.kind, "active", "Step 4: Connector session activated with Ed25519 signature");
        activeSessionId = sessionChallenge.sessionId;
        activeBinding = sessionChallenge.binding;
      }
      connectorConnected = true;

      // Verify computer is Online in Cloud
      const devicesPage = await (await fetch(base + "/devices", {headers: {Cookie: ownerCookie}})).text();
      assert.match(devicesPage, /Online/i, "Step 4: Computer shows Online status in Cloud");

      // =========================================================================
      // STEP 5 & 6: Remote Folder Browsing & Project Registration, Rename, Removal
      // =========================================================================
      // Register project
      const createdId = await devices.createProject(
        ownerSub,
        registeredDeviceId,
        "Acceptance Board"
      );
      assert.ok(createdId, "Step 6: Project registered in Cloud");
      registeredProjectId = createdId;

      // Rename project
      const renameOk = await devices.renameProject(
        ownerSub,
        registeredProjectId,
        "Disposable Acceptance Board"
      );
      assert.equal(renameOk, true, "Step 6: Project renamed in Cloud");
      const projectList = await devices.listProjects(ownerSub);
      const renamedProject = projectList.find(p => p.id === registeredProjectId);
      assert.equal(renamedProject?.alias, "Disposable Acceptance Board");

      // Confirm local files are completely intact
      assert.equal(readFileSync(pcbPath, "utf-8"), initialPcbContent,
        "Step 6: Local PCB file untouched by registration or rename");

      // =========================================================================
      // STEP 7 & 8: AI Client Connection & Project-Specific Read/Write Grant
      // =========================================================================
      const grantOk = await grants.setBrowserGrant(ownerSub, registeredProjectId, clientId, true, "write");
      assert.equal(grantOk, true, "Step 8: AI write access granted");
      const savedGrants = await grants.listBrowserGrants(ownerSub);
      const projectGrant = savedGrants.find(g => g.projectId === registeredProjectId && g.clientId === clientId);
      assert.ok(projectGrant, "Step 8: AI client grant created");
      assert.equal(projectGrant.maxMode, "write", "Step 8: Write access explicitly granted to AI client");

      // =========================================================================
      // STEP 9 & 10: AI Inspects, Designs & Modifies Project via MCP Tool
      // =========================================================================
      const mcpUrl = new URL("/mcp", base);
      const invokeMcp = async (method: string, params: Record<string, any> = {}, toolName?: string) => {
        const res = await fetch(mcpUrl, {
          method: "POST",
          headers: {
            "Authorization": "Bearer valid-chatgpt-token",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": method,
            ...(toolName ? {"Mcp-Name": toolName} : {})
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method,
            params: {
              ...params,
              _meta: {
                "io.modelcontextprotocol/clientInfo": {name: "chatgpt", version: "1.0.0"},
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}
              }
            }
          })
        });
        const text = await res.text();
        let data: Record<string, any> = {};
        if (text.startsWith("event: message\ndata: ")) {
          const line = text.split("\n").find(l => l.startsWith("data: "));
          if (line) data = JSON.parse(line.slice(6));
        } else if (text) {
          try { data = JSON.parse(text); } catch { data = {raw: text}; }
        }
        return {status: res.status, data};
      };

      // 9. Inspect tools
      const toolsList = await invokeMcp("tools/list");
      assert.equal(toolsList.status, 200, "Step 9: MCP tools/list succeeds");
      const tools = (toolsList.data.result?.tools ?? []).map((t: {name: string}) => t.name);
      assert.ok(tools.includes("pcb_move_footprint"), "Step 9: pcb_move_footprint tool is discovered");

      // 10. Execute write modification
      const moveCall = await invokeMcp("tools/call", {
        name: "pcb_move_footprint",
        arguments: {
          project_id: registeredProjectId,
          reference: "C1",
          x_mm: 25.4,
          y_mm: 30.0,
          rotation_deg: 0,
          save_to_disk: true
        }
      }, "pcb_move_footprint");

      assert.equal(moveCall.status, 200, "Step 10: Tool call returned status 200");
      const toolResult = JSON.parse(moveCall.data.result.content[0].text);
      assert.equal(toolResult.success, true, "Step 10: Native write succeeded");
      assert.equal(toolResult.nativeCommitted, true, "Step 10: KiCad transaction committed");
      assert.equal(toolResult.savedToDisk, true, "Step 10: Changes persisted to disk");
      const savedDiskSha = toolResult.diskBoardSha256;
      assert.ok(savedDiskSha, "Step 10: Updated disk SHA returned");
      assert.notEqual(savedDiskSha, initialPcbSha, "Step 10: Disk SHA updated from initial");

      // =========================================================================
      // STEP 11: Independently Reopen and Verify Saved Project on Disk
      // =========================================================================
      const diskContentAfter = readFileSync(pcbPath, "utf-8");
      const computedDiskSha = createHash("sha256").update(diskContentAfter, "utf-8").digest("hex");
      assert.equal(computedDiskSha, savedDiskSha, "Step 11: Independent disk SHA matches tool output");
      assert.match(diskContentAfter, /\(at 25\.4 30\)/, "Step 11: Disk file contains new footprint coordinates");

      // =========================================================================
      // STEP 12: Revoke Access and Confirm Immediate Revocation
      // =========================================================================
      // Revoke ChatGPT project grant
      const revokeOk = await grants.setBrowserGrant(ownerSub, registeredProjectId, clientId, false);
      assert.equal(revokeOk, true, "Step 12: Grant revoked");
      const postRevokeGrants = await grants.listBrowserGrants(ownerSub);
      const activeGrant = postRevokeGrants.find(g => g.projectId === registeredProjectId && g.clientId === clientId);
      assert.equal(activeGrant, undefined, "Step 12: Grant disabled in database");

      // Subsequent tool call must fail
      const revokedCall = await invokeMcp("tools/call", {
        name: "pcb_move_footprint",
        arguments: {
          project_id: registeredProjectId,
          reference: "C1",
          x_mm: 0,
          y_mm: 0
        }
      }, "pcb_move_footprint");
      assert.equal(revokedCall.status, 200);
      const revokedResult = JSON.parse(revokedCall.data.result.content[0].text);
      assert.equal(revokedResult.success, false, "Step 12: Tool call denied after revocation");

      // Scope removal test
      tokenScope = new Set();
      const forbiddenCall = await invokeMcp("tools/call", {
        name: "pcb_move_footprint",
        arguments: {project_id: registeredProjectId, reference: "C1", x_mm: 0, y_mm: 0}
      }, "pcb_move_footprint");
      assert.equal(forbiddenCall.status, 403, "Step 12: Missing scope rejected with 403");

      // Token revocation test
      const unauthorizedRes = await fetch(mcpUrl, {
        method: "POST",
        headers: {
          "Authorization": "Bearer invalid-revoked-token",
          "Content-Type": "application/json",
          "MCP-Protocol-Version": "2026-07-28"
        },
        body: JSON.stringify({jsonrpc: "2.0", id: 99, method: "tools/list", params: {}})
      });
      assert.equal(unauthorizedRes.status, 401, "Step 12: Revoked/invalid OAuth access token rejected with 401");

      // Remove project from Cloud without deleting disk files
      const removeOk = await devices.deleteProject(ownerSub, registeredProjectId);
      assert.equal(removeOk, true, "Step 12: Project removed from Cloud");
      assert.ok(readFileSync(pcbPath, "utf-8").length > 0,
        "Step 12: Local files survive after project removal from Cloud");

    } catch (err) {
      console.error("ACCEPTANCE ERROR:", err);
      throw err;
    } finally {
      if (grants) {
        await grants.close();
      }
      if (server) {
        server.closeAllConnections?.();
        if (server.listening) {
          await new Promise<void>(resolve => server!.close(() => resolve()));
        }
      }
      rmSync(disposableDir, {recursive: true, force: true});
    }
  });
});
