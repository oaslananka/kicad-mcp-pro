import assert from "node:assert/strict";
import {randomBytes} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import pg from "pg";
import {PgGrantManagement} from "../src/grants.js";

const databaseUrl=process.env.TEST_DATABASE_URL;
test("revocation atomically disables grants, invalidates refresh family replay and enforces JWT cutoff",
  {skip:!databaseUrl}, async()=>{
    const control=new pg.Pool({connectionString:databaseUrl});
    const schema="token_"+randomBytes(8).toString("hex");
    let inventory:PgGrantManagement|undefined;
    let db:pg.Pool|undefined;
    try {
      await control.query('CREATE SCHEMA "'+schema+'"');
      const uri=new URL(databaseUrl!);
      uri.searchParams.set("options","-c search_path="+schema);
      const scoped=uri.toString();
      db=new pg.Pool({connectionString:scoped});
      for(const file of [
        "001_inventory.pgsql","002_client_grants.pgsql","003_better_auth.pgsql",
        "004_client_revocation.pgsql","005_token_cutoff.pgsql","006_oauth_issuance_fence.pgsql"
      ]) {
        await db.query(await readFile(new URL("../db/"+file,import.meta.url),"utf8"));
      }
      inventory=new PgGrantManagement(scoped,true);
      const dev="51a665e8-9dd6-4490-8ed5-c5bb4b41c1be";
      const project="69c44c36-b452-47a0-851a-5f8d0f3de95e";
      await db.query('INSERT INTO devices(id,owner_sub,alias,enabled) VALUES ($1,$2,$3,true)',[dev,"owner-a","Workstation"]);
      await db.query('INSERT INTO projects(id,owner_sub,device_id,alias,enabled) VALUES ($1,$2,$3,$4,true)',[project,"owner-a",dev,"USB-C"]);
      await db.query('INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled) VALUES($1,$2,$3,true)',[project,"owner-a","chatgpt"]);
      const now=new Date();
      const expires=new Date(now.getTime()+3600_000);
      for(const owner of ["owner-a","owner-b"]) {
        await db.query(
          'INSERT INTO "users"("id","name","email","emailVerified","createdAt","updatedAt") VALUES($1,$2,$3,true,$4,$4)',
          [owner,owner,owner+"@example.test",now]
        );
      }
      for(const client of ["chatgpt","claude"]) {
        await db.query('INSERT INTO "oauthClient"("id","clientId","redirectUris") VALUES($1,$2,$3)',[client+"-row",client,JSON.stringify([])]);
      }
      for(const [id,owner,client] of [
        ["refresh-a","owner-a","chatgpt"],["refresh-b","owner-b","chatgpt"],["refresh-c","owner-a","claude"]
      ]) {
        await db.query(
          'INSERT INTO "oauthRefreshToken"("id","token","clientId","userId","scopes","createdAt","expiresAt","rotationReplayResponse","rotationReplayExpiresAt") VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)',
          [id,"test-only-"+id,client,owner,JSON.stringify(["offline_access","projects:read"]),now,expires,"encrypted-cached-response",expires]
        );
        await db.query(
          'INSERT INTO "oauthAccessToken"("id","token","clientId","userId","scopes","createdAt","expiresAt") VALUES($1,$2,$3,$4,$5,$6,$7)',
          [id,"test-only-access-"+id,client,owner,JSON.stringify(["projects:read"]),now,expires]
        );
      }
      const oldIat=Math.floor(Date.now()/1000)-120;
      assert.equal(await inventory.isAccessTokenAllowed("owner-a","chatgpt",oldIat),true);
      assert.equal(await inventory.revokeClient("owner-a","chatgpt"),1);
      assert.equal(await inventory.isAccessTokenAllowed("owner-a","chatgpt",oldIat),false);
      assert.equal(await inventory.isAccessTokenAllowed("owner-b","chatgpt",oldIat),true);
      assert.equal(await inventory.isAccessTokenAllowed("owner-a","claude",oldIat),true);
      const tokens=await db.query<{id:string;revoked:Date|null;rotationReplayResponse:string|null}>(
        'SELECT "id","revoked","rotationReplayResponse" FROM "oauthRefreshToken" ORDER BY "id"'
      );
      assert.equal(tokens.rows.find(t=>t.id==="refresh-a")?.revoked instanceof Date,true);
      assert.equal(tokens.rows.find(t=>t.id==="refresh-a")?.rotationReplayResponse,null);
      assert.equal(tokens.rows.find(t=>t.id==="refresh-b")?.revoked,null);
      assert.equal(tokens.rows.find(t=>t.id==="refresh-c")?.revoked,null);
      const access=await db.query<{id:string;revoked:Date|null}>('SELECT "id","revoked" FROM "oauthAccessToken" ORDER BY "id"');
      assert.equal(access.rows.find(t=>t.id==="refresh-a")?.revoked instanceof Date,true);
      assert.equal(access.rows.find(t=>t.id==="refresh-b")?.revoked,null);
      assert.equal((await inventory.listProjects("owner-a","chatgpt")).length,0);
      await inventory.setGrant("owner-a","portal",project,{clientId:"chatgpt",enabled:true,maxMode:"readonly"});
      assert.equal((await inventory.listProjects("owner-a","chatgpt")).length,1);
      // Even if the owner explicitly regrants project access, an old signed
      // token is still cut off by its issuance timestamp.
      assert.equal(await inventory.isAccessTokenAllowed("owner-a","chatgpt",oldIat),false);
      const after=Math.floor(Date.now()/1000)+10;
      assert.equal(await inventory.isAccessTokenAllowed("owner-a","chatgpt",after),true);
    } finally {
      if(inventory) await inventory.close();
      if(db) await db.end();
      await control.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
      await control.end();
    }
  });
