import assert from "node:assert/strict";
import {createHash,randomBytes} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import type {Server} from "node:http";
import type {AddressInfo} from "node:net";
import pg from "pg";
import {createIdentity} from "../src/identity.js";
import {PgGrantManagement} from "../src/grants.js";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";

const databaseUrl=process.env.TEST_DATABASE_URL;
const origin="http://127.0.0.1:8787";

test("real OAuth refresh grant: rotation, revoked predecessor/successor, other owners", {skip:!databaseUrl},async()=>{
  const admin=new pg.Pool({connectionString:databaseUrl});
  const schema="refresh_"+randomBytes(6).toString("hex");
  let db:pg.Pool|undefined;
  let grantStore:PgGrantManagement|undefined;
  let httpServer:Server|undefined;
  try {
    await admin.query('CREATE SCHEMA "'+schema+'"');
    const uri=new URL(databaseUrl!);
    uri.searchParams.set("options","-c search_path="+schema);
    const scoped=uri.toString();
    db=new pg.Pool({connectionString:scoped});
    for(const name of ["001_inventory.pgsql","002_client_grants.pgsql","003_better_auth.pgsql","004_client_revocation.pgsql","005_token_cutoff.pgsql","006_oauth_issuance_fence.pgsql"]){
      await db.query(await readFile(new URL("../db/"+name,import.meta.url),"utf8"));
    }
    grantStore=new PgGrantManagement(scoped,true);
    const identity=createIdentity({publicOrigin:origin,audience:origin+"/mcp",databaseUrl:scoped},{
      secret:randomBytes(40).toString("hex"),
      googleId:"fixture-google-id",googleSecret:"fixture-google-secret",
      githubId:"fixture-github-id",githubSecret:"fixture-github-secret"
    },db);
    const now=new Date(),expiry=new Date(now.getTime()+3600000);
    for(const owner of ["owner-a","owner-b"]){
      await db.query('INSERT INTO "users"("id","name","email","emailVerified","createdAt","updatedAt") VALUES ($1,$1,$2,true,$3,$3)',
        [owner,owner+"@unit.example",now]);
    }
    for(const id of ["client-a","client-b"]){
      await db.query('INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod","grantTypes","scopes") VALUES($1,$1,$2,$3,$4,$5)',
        [id,JSON.stringify(["http://127.0.0.1:8888/callback"]),"none",JSON.stringify(["authorization_code","refresh_token"]),JSON.stringify(["offline_access","projects:read"])]);
    }
    const tokens=new Map<string,string>();
    for(const [owner,client] of [["owner-a","client-a"],["owner-b","client-a"],["owner-a","client-b"]]){
      const id=owner+"-"+client,raw="fixture-"+randomBytes(24).toString("base64url");
      tokens.set(id,raw);
      const digest=createHash("sha256").update(raw).digest("base64url");
      await db.query('INSERT INTO "oauthRefreshToken"("id","token","clientId","userId","scopes","createdAt","expiresAt","authorizationCodeId") VALUES($1,$2,$3,$4,$5,$6,$7,$8)',
        [id,digest,client,owner,JSON.stringify(["offline_access","projects:read"]),now,expiry,"old-authorization-"+id]);
    }
    const config:Config={
      host:"127.0.0.1",port:0,publicOrigin:origin,
      issuer:origin+"/api/auth",jwksUrl:origin+"/api/auth/jwks",
      audience:origin+"/mcp",databaseUrl:scoped,
      allowedOrigins:[],managementClientId:"portal-client"
    };
    httpServer=createHttpServer(config, grantStore, async()=>{throw new Error("unexpected auth")}, {grants:grantStore, identity:identity});
    await new Promise<void>(resolve=>httpServer!.listen(0,"127.0.0.1",resolve));
    const httpEndpoint="http://127.0.0.1:"+(httpServer.address() as AddressInfo).port;
    const refresh=async (token:string,client:string) => {
      const response=await fetch(httpEndpoint+"/api/auth/oauth2/token",{
        method:"POST",
        headers:{"Content-Type":"application/x-www-form-urlencoded"},
        body:new URLSearchParams({grant_type:"refresh_token",refresh_token:token,client_id:client})
      });
      const content=await response.text();
      const body=content ? JSON.parse(content) as Record<string,unknown> : {} as Record<string,unknown>;
      return {status:response.status,body};
    };
    const wrong=await refresh(tokens.get("owner-a-client-a")!,"client-b");
    assert.notEqual(wrong.status,200);
    const before=await refresh(tokens.get("owner-a-client-a")!,"client-a");
    assert.equal(before.status,200,JSON.stringify(before.body));
    assert.equal(typeof before.body.refresh_token,"string");
    const rotated=before.body.refresh_token as string;
    const retry=await refresh(tokens.get("owner-a-client-a")!,"client-a");
    assert.equal(retry.status,200,JSON.stringify(retry.body));
    assert.equal(retry.body.refresh_token,rotated);
    await grantStore.revokeClient("owner-a","client-a");
    for(const token of [rotated,tokens.get("owner-a-client-a")!]){
      const rejected=await refresh(token,"client-a");
      assert.equal(rejected.body.error,"invalid_grant",JSON.stringify(rejected.body));
    }
    const otherOwner=await refresh(tokens.get("owner-b-client-a")!,"client-a");
    assert.equal(otherOwner.status,200,JSON.stringify(otherOwner.body));
    const otherClient=await refresh(tokens.get("owner-a-client-b")!,"client-b");
    assert.equal(otherClient.status,200,JSON.stringify(otherClient.body));
    const otherClientRotated=otherClient.body.refresh_token as string;
    assert.equal(typeof otherClientRotated,"string");
    // Pause the successor INSERT after Better Auth's predecessor CAS.
    await db.query(
      "CREATE FUNCTION aa_test_pause_issuance() RETURNS trigger LANGUAGE plpgsql AS $$ "+
      "BEGIN PERFORM pg_advisory_xact_lock(9854742); RETURN NEW; END $$; "+
      'CREATE TRIGGER aa_test_pause_issuance BEFORE INSERT ON "oauthRefreshToken" '+
      "FOR EACH ROW EXECUTE FUNCTION aa_test_pause_issuance()"
    );
    const barrier=await db.connect();
    try {
      await barrier.query("SELECT pg_advisory_lock(9854742)");
      const concurrent=refresh(otherClientRotated,"client-b");
      let paused=false;
      const rotatedDigest=createHash("sha256").update(otherClientRotated).digest("base64url");
      for(let index=0;index<125;index++){
        const state=await db.query<{revoked:boolean}>(
          'SELECT "revoked" IS NOT NULL AS revoked FROM "oauthRefreshToken" WHERE "userId"=$1 AND "clientId"=$2 AND "token"=$3',
          ["owner-a","client-b",rotatedDigest]
        );
        if(state.rows[0]?.revoked===true){paused=true;break;}
        await new Promise(resolve=>setTimeout(resolve,20));
      }
      assert.equal(paused,true,"Refresh must reach its pending successor insert");
      await grantStore.revokeClient("owner-a","client-b");
      // Even if a new, separately confirmed consent is recorded before the
      // delayed old refresh completes, the old code lineage cannot revive.
      await db.query(
        'INSERT INTO "oauthConsent"("id","clientId","userId","scopes","createdAt","updatedAt") VALUES($1,$2,$3,$4,clock_timestamp(),clock_timestamp())',
        ["fresh-consent","client-b","owner-a",JSON.stringify(["offline_access","projects:read"])]
      );
      await barrier.query("SELECT pg_advisory_unlock(9854742)");
      const result=await concurrent;
      assert.equal(result.status,400,"Late refresh must map to OAuth invalid_grant");
      assert.equal(result.body.error,"invalid_grant");
      const late=await db.query(
        'SELECT count(*)::integer AS count FROM "oauthRefreshToken" WHERE "userId"=$1 AND "clientId"=$2 AND "revoked" IS NULL',
        ["owner-a","client-b"]
      );
      assert.equal(late.rows[0]?.count,0,"No live successor refresh token may survive");
      // Reauthorization is allowed only with a fresh authorization-code
      // lineage; merely adding a new consent never revives the old lineage.
      await assert.rejects(db.query(
        'INSERT INTO "oauthRefreshToken"("id","token","clientId","userId","scopes","createdAt","expiresAt","authorizationCodeId") VALUES($1,$2,$3,$4,$5,clock_timestamp(),now()+interval \'1 hour\',$6)',
        ["old-attempt","old-attempt-hash","client-b","owner-a",JSON.stringify(["projects:read"]),"old-authorization-owner-a-client-b"]
      ));
      await db.query(
        'INSERT INTO "oauthRefreshToken"("id","token","clientId","userId","scopes","createdAt","expiresAt","authorizationCodeId") VALUES($1,$2,$3,$4,$5,clock_timestamp(),now()+interval \'1 hour\',$6)',
        ["new-authorization-token","new-authorization-hash","client-b","owner-a",JSON.stringify(["projects:read"]),"fresh-new-code"]
      );
      // A late replay-cache UPDATE must also be fenced after revocation.
      await assert.rejects(
        db.query('UPDATE "oauthRefreshToken" SET "rotationReplayResponse"=$1 WHERE "id"=$2',
          ["stale-cached-response","owner-a-client-b"]),
        /oauth_client_revoked/
      );
      const replay=await db.query<{rotationReplayResponse:string|null}>(
        'SELECT "rotationReplayResponse" FROM "oauthRefreshToken" WHERE "id"=$1',
        ["owner-a-client-b"]
      );
      assert.equal(replay.rows[0]?.rotationReplayResponse,null);
      await db.query(
        'UPDATE "oauthRefreshToken" SET "rotationReplayResponse"=$1 WHERE "id"=$2',
        ["new-consent-replay","new-authorization-token"]
      );
      const freshReplay=await db.query<{rotationReplayResponse:string|null}>(
        'SELECT "rotationReplayResponse" FROM "oauthRefreshToken" WHERE "id"=$1',
        ["new-authorization-token"]
      );
      assert.equal(freshReplay.rows[0]?.rotationReplayResponse,"new-consent-replay");
    } finally {
      await barrier.query("SELECT pg_advisory_unlock(9854742)");
      barrier.release();
    }
  }finally{
    if(httpServer) await new Promise<void>(resolve=>httpServer!.close(()=>resolve()));
    await grantStore?.close();
    await db?.end();
    await admin.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await admin.end();
  }
});
