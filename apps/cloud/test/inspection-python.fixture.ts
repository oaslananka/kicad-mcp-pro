/**
 * Locally launched cross-language integration peer; never a production server.
 * Uses the genuine Node Cloud WSS code, a disposable PostgreSQL schema and
 * a test-only HTTPS certificate. No public listener, OAuth issuance or deploy.
 */
import {createPrivateKey,createPublicKey,randomBytes,sign} from "node:crypto";
import {readFileSync} from "node:fs";
import {createServer} from "node:https";
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
    const server=createServer({
      cert:readFileSync(cert),key:readFileSync(key)
    },(_req,res)=>{res.writeHead(404);res.end();});
    await new Promise<void>(resolve=>server.listen(0,"localhost",resolve));
    const origin="https://localhost:"+(server.address() as AddressInfo).port;
    const connector=attachConnectorWebSocket(server,{
      publicOrigin:origin,sourceOf:()=>"127.0.0.1",
      operatorLocalOnce:true,operatorInspectionOnce:true,
      proofs:new PgDeviceHandshakes(db),
      connections:new BoundConnectorConnections(
        new PgConnectorSessions(db),new PgConnectorReadGate(db))
    });
    try{
      process.stdout.write(JSON.stringify({origin,device,project,owner})+"\n");
      const oauth={ownerSub:owner,clientId,
        accessTokenIssuedAtSeconds:Math.floor(Date.now()/1000)};
      let intent:ReturnType<typeof connector.prepareOwnerInspection>=null;
      for(let i=0;i<130&&!intent;i++){
        intent=connector.prepareOwnerInspection(oauth,device,project);
        if(!intent)await new Promise(resolve=>setTimeout(resolve,100));
      }
      if(!intent)throw Error("TEST_CONNECTOR_SESSION_NOT_READY");
      const result=await connector.requestInspection(oauth,device,project,intent);
      if(!result)throw Error("TEST_INSPECTION_NOT_DELIVERED");
      process.stdout.write(JSON.stringify({result})+"\n");
    }finally{
      await connector.close();
      await new Promise<void>(resolve=>server.close(()=>resolve()));
    }
  });
}
await main().catch(error=>{
  process.stderr.write("FIXTURE_FAILED:"+String(error)+"\n");
  process.exitCode=1;
});
