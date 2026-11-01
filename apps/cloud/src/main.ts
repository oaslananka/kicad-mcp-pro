import { loadConfig } from "./config.js";
import {Pool} from "pg";
import {PgDeviceHandshakes} from "./device-handshake.js";
import {PgConnectorSessions} from "./connector-session.js";
import {PgConnectorReadGate} from "./connector-read-gate.js";
import {BoundConnectorConnections} from "./connector-transport-binding.js";
import {attachConnectorWebSocket} from "./connector-ws.js";
import {openOwnerConsentRuntime} from "./owner-read-consumer-runtime.js";
import {openConfiguredOwnerIntentDelivery} from "./owner-read-intent-runtime.js";
import {PgDeviceManagement} from "./device-management.js";
import {PgPairingReview} from "./pairing-review.js";
import {PgPairingDeviceAPI} from "./pairing-device-api.js";
import {configuredDeviceSource} from "./trusted-ingress.js";
import { createVerifier } from "./auth.js";
import { createHttpServer } from "./http.js";
import { PgGrantManagement } from "./grants.js";
import { configuredIdentity } from "./identity.js";

const config = loadConfig();
const identity = configuredIdentity(config);
const inventory = new PgGrantManagement(config.databaseUrl,Boolean(identity));
// Deliberately disabled until trusted WSS ingress, device onboarding and
// real local connector acceptance have been verified.
const wsEnabled=process.env.CONNECTOR_WS_ENABLED==="true";
if(wsEnabled&&!config.publicOrigin.startsWith("https://")){
  throw new Error("Connector WebSocket requires externally terminated HTTPS");
}
const connectorPool=(wsEnabled||Boolean(identity))?new Pool({connectionString:config.databaseUrl}):null;
// Explicitly independent PostgreSQL role; never issue owner approvals here.
// With the default flag OFF, reads remain disabled even if WSS is enabled.
const ownerConsentRuntime=await openOwnerConsentRuntime(
  process.env,config.publicOrigin,wsEnabled,connectorPool);
const ownerIntentDelivery=await openConfiguredOwnerIntentDelivery(
  process.env,config.publicOrigin,{
    wsEnabled,ownerConsentEnabled:Boolean(ownerConsentRuntime),
    identityEnabled:Boolean(identity)
  });
const deviceManagement=identity&&connectorPool?new PgDeviceManagement(connectorPool):undefined;
const pairingReview=identity&&connectorPool?
  new PgPairingReview(connectorPool,process.env.BETTER_AUTH_SECRET??""):undefined;
const pairingDeviceEnabled=process.env.PAIRING_DEVICE_API_ENABLED==="true";
// No additional issuer, OAuth App or domain for the optional presence-only
// pilot. It is deliberately OFF unless the owner explicitly opts in.
// Local user presence is weaker than independent WebAuthn. It must never
// authorize file contents, writes or arbitrary commands. Native DRC counts
// require a separate explicit one-shot flag and remain a limited pilot.
const operatorLocalOnce=process.env.CONNECTOR_OPERATOR_ONESHOT_ENABLED==="true";
// Separate owner-operated native DRC **count-only** pilot, OFF by default.
const operatorNativeDrc=process.env.CONNECTOR_OPERATOR_NATIVE_DRC_ENABLED==="true";
const operatorInspection=process.env.CONNECTOR_OPERATOR_INSPECTION_ENABLED==="true";
const operatorBoardCounts=process.env.CONNECTOR_OPERATOR_BOARD_COUNTS_ENABLED==="true";
if(operatorNativeDrc&&!operatorLocalOnce)
  throw Error("Native DRC requires the manually operated one-shot pilot");
if(operatorInspection&&!operatorLocalOnce)
  throw Error("Project inspection requires the manually operated one-shot pilot");
if(operatorBoardCounts&&!operatorLocalOnce)
  throw Error("PCB counts require the manually operated one-shot pilot");
if(operatorLocalOnce&&(!wsEnabled||!pairingDeviceEnabled||!identity||
    ownerConsentRuntime||process.env.OWNER_READ_CONSUMER_ENABLED==="true")){
  throw Error("Local one-shot pilot needs built-in identity, pairing and WS only");
}
if(pairingDeviceEnabled&&(!identity||!config.publicOrigin.startsWith("https://"))){
  throw new Error("Device pairing API requires built-in identity and trusted HTTPS ingress");
}
const pairingDevice=pairingDeviceEnabled&&connectorPool?
  new PgPairingDeviceAPI(connectorPool,process.env.BETTER_AUTH_SECRET??""):undefined;
// Enabling either public device surface requires an explicit, fixed
// cloudflared TCP peer allowlist; no trust-all or unverified header fallback.
// Device source trust is explicit and mutually exclusive; only an accepted,
// private owner SSH forward may use the private mode. The default stays the
// existing fail-closed Cloudflare source policy.
const deviceSource=(wsEnabled||pairingDeviceEnabled)?
  configuredDeviceSource(process.env):undefined;
// Lazy binding keeps all read surfaces absent when connector WS is disabled.
let connectorRelay:ReturnType<typeof attachConnectorWebSocket>|null=null;
const server=createHttpServer(config, inventory, createVerifier(config), {grants:inventory, identity:identity, devices:deviceManagement, pairings:pairingReview, pairingDevice:pairingDevice, deviceSource:deviceSource,
  mcpProjectPresenceEnabled:operatorLocalOnce,
  mcpProjectNativeDrcEnabled:operatorNativeDrc,
  mcpProjectInspectionEnabled:operatorInspection,
  mcpProjectBoardCountsEnabled:operatorBoardCounts,summaryRelay:()=>connectorRelay,
  ...(ownerIntentDelivery?{ownerIntentDelivery}:{})});
const connectorWs=wsEnabled&&connectorPool?attachConnectorWebSocket(server,{
  publicOrigin:config.publicOrigin,
  sourceOf:deviceSource!,
  proofs:new PgDeviceHandshakes(connectorPool),
  ...(ownerConsentRuntime?{ownerConsent:ownerConsentRuntime.consent}:{}),
  operatorLocalOnce,operatorNativeDrcOnce:operatorNativeDrc,
  operatorInspectionOnce:operatorInspection,
  operatorBoardCountsOnce:operatorBoardCounts,
  connections:new BoundConnectorConnections(
    new PgConnectorSessions(connectorPool),
    new PgConnectorReadGate(connectorPool))
}):null;
connectorRelay=connectorWs;
server.listen(config.port, config.host, () => {
  // Never log credential-bearing URLs, project data or request bodies.
  process.stdout.write("Cloud MCP server listening on configured interface\n");
});
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => {
    void (async()=>{
      await connectorWs?.close();
      await ownerConsentRuntime?.close();
      await new Promise<void>(resolve=>server.close(()=>resolve()));
      await connectorPool?.end();
      await inventory.close();
      process.exit(0);
    })().catch(()=>process.exit(1));
  });
}
