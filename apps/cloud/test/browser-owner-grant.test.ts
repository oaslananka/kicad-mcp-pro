import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {test} from "node:test";
import {inIsolatedDatabase} from "./isolated-db.js";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";
import {PgDeviceManagement} from "../src/device-management.js";
import {PgGrantManagement} from "../src/grants.js";

const url=process.env.TEST_DATABASE_URL;
const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql","003_better_auth.pgsql",
  "004_client_revocation.pgsql","005_token_cutoff.pgsql","006_oauth_issuance_fence.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql","009_device_handshake.pgsql",
  "010_connector_sessions.pgsql","011_pairing_review_budget.pgsql",
  "012_pairing_device_budget.pgsql"
];
test("browser owner grants require current OAuth consent and cannot revive revoked consent",
  {skip:!url},async()=>{
  await inIsolatedDatabase(url!,migrations,async db=>{
    const scoped=(db as unknown as {options:{connectionString:string}}).options.connectionString;
    const grants=new PgGrantManagement(scoped,true);
    try{
      const owner="owner-browser-fixture",client="oauth-client-fixture";
      await db.query(
        'INSERT INTO "users"("id","name","email","emailVerified") VALUES($1,$2,$3,true)',
        [owner,"Fixture owner","fixture@sample.invalid"]);
      await db.query(
        'INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod",'+
        '"grantTypes","scopes") VALUES($1,$1,$2,$3,$4,$5)',
        [client,JSON.stringify(["https://client.invalid/callback"]),"none",
          JSON.stringify(["authorization_code"]),JSON.stringify(["projects:read"])]);
      const key=generateKeyPairSync("ed25519");
      const pairing=new PgPairingChallenges(db,randomBytes(32));
      const pending=await pairing.issue("Browser test",
        key.publicKey.export({format:"der",type:"spki"}) as Buffer);
      assert.equal(await pairing.review(pending.id,owner,pending.userCode,"approve"),"approved");
      const enrolled=await pairing.enroll(pending.id,pending.deviceCode,
        sign(null,redemptionProof(pending.id,pending.deviceCode),key.privateKey));
      assert.equal(enrolled.kind,"enrolled");
      if(enrolled.kind!=="enrolled")return;
      const devices=new PgDeviceManagement(db);
      assert.equal(await devices.enableDevice(owner,enrolled.deviceId),true);
      const project=await devices.createProject(owner,enrolled.deviceId,"Read-only PCB");
      assert.ok(project);
      assert.equal(await grants.setBrowserGrant(owner,project!,client,true),false);
      await db.query(
        'INSERT INTO "oauthConsent"("id","clientId","userId","scopes","createdAt","updatedAt") '+
        'VALUES($1,$2,$3,$4,clock_timestamp(),clock_timestamp())',
        ["consent-1",client,owner,JSON.stringify(["openid","projects:read"])]);
      assert.equal(await grants.setBrowserGrant("other-owner",project!,client,true),false);
      assert.equal(await grants.setBrowserGrant(owner,project!,"unconsented",true),false);
      assert.equal(await grants.setBrowserGrant(owner,project!,client,true),true);
      const enabled=await db.query("SELECT enabled,max_mode FROM project_client_grants "+
        "WHERE project_id=$1 AND client_id=$2",[project,client]);
      assert.equal(enabled.rows[0].enabled,true);
      assert.equal(enabled.rows[0].max_mode,"readonly");
      await grants.revokeClient(owner,client);
      assert.equal(await grants.setBrowserGrant(owner,project!,client,true),false,
        "Old OAuth consent must not re-enable a revoked client");
      assert.equal(await grants.setBrowserGrant(owner,project!,client,false),true);
      await db.query("SELECT pg_sleep(0.01)");
      await db.query(
        'INSERT INTO "oauthConsent"("id","clientId","userId","scopes","createdAt","updatedAt") '+
        'VALUES($1,$2,$3,$4,clock_timestamp(),clock_timestamp())',
        ["consent-2",client,owner,JSON.stringify(["projects:read"])]);
      assert.equal(await grants.setBrowserGrant(owner,project!,client,true),true);
      await devices.revokeDevice(owner,enrolled.deviceId);
      assert.equal(await grants.setBrowserGrant(owner,project!,client,true),false);
    }finally{await grants.close();}
  });
});
