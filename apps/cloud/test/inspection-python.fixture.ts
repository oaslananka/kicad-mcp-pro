/**
 * Locally launched cross-language integration peer; never a production server.
 * Uses the genuine Node Cloud WSS code, a disposable PostgreSQL schema and
 * a test-only HTTPS certificate. No public listener, OAuth issuance or deploy.
 */
import {createPrivateKey,createPublicKey,randomBytes,sign} from "node:crypto";
import {readFileSync} from "node:fs";
import {createServer} from "node:https";
import {createLocalJWKSet,exportJWK,generateKeyPair,SignJWT} from "jose";
import {createHttpServer} from "../src/http.js";
import {createVerifier} from "../src/auth.js";
import {PgInventory} from "../src/store.js";
import type {Config} from "../src/config.js";
import type {AddressInfo} from "node:net";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgDeviceHandshakes} from "../src/device-handshake.js";
import {PgConnectorSessions} from "../src/connector-session.js";
import {PgConnectorReadGate} from "../src/connector-read-gate.js";
import {BoundConnectorConnections} from "../src/connector-transport-binding.js";
import {attachConnectorWebSocket} from "../src/connector-ws.js";
import {inIsolatedDatabase} from "./isolated-db.js";

const names=[
  "001_inventory.pgsql","002_client_grants.pgsql","005_token_cutoff.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql",
  "009_device_handshake.pgsql","010_connector_sessions.pgsql"
];
const [cert,key,signerFile]=process.argv.slice(2);
const url=process.env.TEST_DATABASE_URL;
if(!url||!cert||!key||!signerFile)throw Error("TEST_FIXTURE_ARGS_MISSING");
// Fail before any SQL or network operation if a non-local database URL leaks
// into the test environment. Only a disposable loopback database is valid.
const database=new URL(url);
if(!["postgresql:","postgres:"].includes(database.protocol)||
   !["localhost","127.0.0.1","[::1]"].includes(database.hostname))
  throw Error("TEST_FIXTURE_LOCAL_DB_ONLY");
const privateKey=createPrivateKey(readFileSync(signerFile));
const publicDer=createPublicKey(privateKey).export({format:"der",type:"spki"}) as Buffer;
const owner="local-fixture-owner",clientId="local-fixture-client";
const project="77777777-7777-4777-8777-777777777777";
const mode=process.env.TEST_CONNECTOR_OPERATION==="schematic_counts"?
  "schematic_counts":process.env.TEST_CONNECTOR_OPERATION==="board_counts"?
  "board_counts":"inspection";

async function main():Promise<void>{
  await inIsolatedDatabase(url!,names,async db=>{
    const pairing=new PgPairingChallenges(db,randomBytes(32));
    const challenge=await pairing.issue("Ephemeral local fixture",publicDer);
    if(await pairing.review(challenge.id,owner,challenge.userCode,"approve")!=="approved")
      throw Error("TEST_PAIRING_DENIED");
    const enrolled=await pairing.enroll(challenge.id,challenge.deviceCode,
      sign(null,redemptionProof(challenge.id,challenge.deviceCode),privateKey));
    if(enrolled.kind!=="enrolled")throw Error("TEST_ENROLLMENT_DENIED");
    const device=enrolled.deviceId;
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[device]);
    await db.query("INSERT INTO projects(id,owner_sub,device_id,alias,enabled,max_mode) "+
      "VALUES($1,$2,$3,'Local board',true,'readonly')",[project,owner,device]);
    await db.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled,max_mode) "+
      "VALUES($1,$2,$3,true,'readonly')",[project,owner,clientId]);
    // Real Cloud HTTP MCP and WSS share the same ephemeral HTTPS listener.
    // No public listener and no production OAuth provider is involved.
    let cloudHttp:ReturnType<typeof createHttpServer>|null=null;
    const server=createServer({
      cert:readFileSync(cert),key:readFileSync(key)
    },(req,res)=>{
      if(cloudHttp)cloudHttp.emit("request",req,res);
      else {res.writeHead(503);res.end();}
    });
    await new Promise<void>(resolve=>server.listen(0,"localhost",resolve));
    const origin="https://localhost:"+(server.address() as AddressInfo).port;
    const {publicKey:tokenPublic,privateKey:tokenPrivate}=await generateKeyPair("RS256");
    const jwk=await exportJWK(tokenPublic);
    const jwks=createLocalJWKSet({keys:[{...jwk,kid:"fixture-jwt",alg:"RS256",use:"sig"}]});
    const jwt=await new SignJWT({
      iss:origin, aud:origin+"/mcp", sub:owner,
      scope:"projects:read",client_id:clientId
    }).setProtectedHeader({alg:"RS256",kid:"fixture-jwt"})
      .setIssuedAt().setExpirationTime("3m").sign(tokenPrivate);
    const foreignJwt=await new SignJWT({
      iss:origin,aud:origin+"/mcp",sub:"unrelated-owner",
      scope:"projects:read",client_id:clientId
    }).setProtectedHeader({alg:"RS256",kid:"fixture-jwt"})
      .setIssuedAt().setExpirationTime("3m").sign(tokenPrivate);
    const config:Config={
      host:"localhost",port:0,publicOrigin:origin,
      issuer:origin,jwksUrl:origin+"/jwks",audience:origin+"/mcp",
      databaseUrl:url!,allowedOrigins:[],managementClientId:"fixture-portal"
    };
    // Reuse the actual PostgreSQL inventory implementation against the
    // current test's isolated schema, not a synthetic grant lookup.
    const scopedUrl=db.options.connectionString;
    if(!scopedUrl)throw Error("TEST_SCHEMA_URL_MISSING");
    const inventory=new PgInventory(scopedUrl);
    const connector=attachConnectorWebSocket(server,{
      publicOrigin:origin,sourceOf:()=>"127.0.0.1",
      operatorLocalOnce:true,operatorInspectionOnce:true,
      operatorBoardCountsOnce:true,
      operatorSchematicCountsOnce:true,
      proofs:new PgDeviceHandshakes(db),
      connections:new BoundConnectorConnections(
        new PgConnectorSessions(db),new PgConnectorReadGate(db))
    });
    cloudHttp=createHttpServer(config,inventory,createVerifier(config,jwks),{
      summaryRelay:()=>connector,
      mcpProjectInspectionEnabled:true,
      mcpProjectBoardCountsEnabled:true,
      mcpProjectSchematicCountsEnabled:true
    });
    try{
      process.stdout.write(JSON.stringify({origin,device,project,owner,jwt,foreignJwt,mode})+"\n");
      // Session database activation is a read-only readiness signal:
      // never reserve the owner intent before the real SDK tool call.
      let active=false;
      for(let i=0;i<130&&!active;i++){
        const state=await db.query<{state:string}>(
          "SELECT state FROM connector_sessions WHERE device_id=$1 "+
          "ORDER BY created_at DESC LIMIT 1",[device]);
        active=state.rows[0]?.state==="active";
        if(!active)await new Promise(resolve=>setTimeout(resolve,100));
      }
      if(!active)throw Error("TEST_CONNECTOR_SESSION_NOT_READY");
      process.stdout.write(JSON.stringify({connectorReady:true})+"\n");
      // Test process confirms the real SDK call completed via stdin. No
      // fixture-made MCP tool call or extra public test route.
      await new Promise<void>((resolve,reject)=>{
        const watchdog=setTimeout(()=>reject(Error("TEST_SDK_CALL_NOT_COMPLETED")),35_000);
        process.stdin.once("data",data=>{
          clearTimeout(watchdog);
          // A flowing PIPE can otherwise keep the Node fixture alive even
          // after HTTPS, WSS and PostgreSQL have all closed successfully.
          process.stdin.pause();
          if(data.toString("utf8").trim()==="done")resolve();
          else reject(Error("TEST_SDK_COMPLETION_INVALID"));
        });
      });
    }finally{
      await connector.close();
      await inventory.close();
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
}
await main().then(()=>{
  // Fixture-only process: main() has already closed the HTTPS/WSS listener,
  // database inventory, and isolated PostgreSQL schema. MCP SDK timers
  // must not keep this one-shot child alive after accepted completion.
  process.exit(0);
}).catch(error=>{
  process.stderr.write("FIXTURE_FAILED:"+String(error)+"\n");
  process.exit(1);
});
