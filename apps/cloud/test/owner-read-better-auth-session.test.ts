import assert from "node:assert/strict";
import {createHmac,randomBytes,randomUUID} from "node:crypto";
import {test} from "node:test";
import type {IncomingMessage} from "node:http";
import {inIsolatedDatabase} from "./isolated-db.js";
import {createIdentity} from "../src/identity.js";
import {createIndependentOwnerSessionVerifier}
  from "../src/owner-read-better-auth-session.js";

const databaseUrl=process.env.TEST_DATABASE_URL;
const authority="https://owner.example.test";
const owner="sole-owner-test";
const key=randomBytes(48);
const secret=randomBytes(48).toString("hex");
const incoming=(cookie?:string,extra:Record<string,string>={})=>
  ({headers:{
    host:new URL(authority).host,
    ...(cookie?{cookie}:{}),...extra
  }}) as unknown as IncomingMessage;
const cookie=(token:string)=>
  "__Secure-better-auth.session_token="+encodeURIComponent(token+"."+
    createHmac("sha256",secret).update(token).digest("base64"));

test("independent Better Auth owner verifier rejects forged, expired, revoked and unrelated sessions",
  {skip:!databaseUrl,timeout:30_000},async()=>{
  await inIsolatedDatabase(databaseUrl!,["003_better_auth.pgsql"],async db=>{
    const identity=createIdentity({
      publicOrigin:authority,audience:authority+"/mcp",databaseUrl:databaseUrl!
    },{secret,googleId:"",googleSecret:"",
      githubId:"synthetic-local-client",githubSecret:"synthetic-local-provider"},db);
    const verifier=createIndependentOwnerSessionVerifier(
      identity,authority,owner,key);
    assert.throws(()=>createIndependentOwnerSessionVerifier(
      identity,"https://other.example.test",owner,key),/exact HTTPS/);
    assert.throws(()=>createIndependentOwnerSessionVerifier(
      identity,authority,owner,randomBytes(16)),/key required/);

    const now=new Date();
    const future=new Date(now.getTime()+60*60*1000);
    const token=randomBytes(32).toString("base64url");
    const sessionId=randomUUID();
    await db.query('INSERT INTO "users"("id","name","email","emailVerified")'+
      ' VALUES($1,$2,$3,true)',[owner,"Independent owner",
        "owner@local.invalid"]);
    await db.query('INSERT INTO "session"'+
      '("id","expiresAt","token","updatedAt","userId")'+
      ' VALUES($1,$2,$3,$4,$5)',[sessionId,future,token,now,owner]);

    const issued=await verifier(incoming(cookie(token)));
    assert.ok(issued,"Actual Better Auth signed session is accepted");
    assert.equal(issued.ownerSub,owner);
    assert.match(issued.csrf,/^[A-Za-z0-9_-]{43}$/);
    assert.deepEqual(await verifier(incoming(cookie(token))),issued,
      "CSRF proof is stable within a single authenticated session");
    assert.equal(await verifier(incoming()),null);
    assert.equal(await verifier(incoming("__Secure-better-auth.session_token="+token)),null,
      "Unsigned browser token cannot authenticate");
    assert.equal(await verifier(incoming(cookie("attacker-token"))),null);
    assert.equal(await verifier(incoming(cookie(token),{
      host:"attacker.example.test"})),null);
    assert.equal(await verifier(incoming(cookie(token),{
      "x-forwarded-host":authority})),null);
    assert.equal(await verifier(incoming(cookie(token),{
      authorization:"Bearer attacker"})),null);

    const otherOwner=randomUUID();
    const otherToken=randomBytes(32).toString("base64url");
    await db.query('INSERT INTO "users"("id","name","email","emailVerified")'+
      ' VALUES($1,$2,$3,true)',[otherOwner,"Other owner",
        "untrusted@local.invalid"]);
    await db.query('INSERT INTO "session"'+
      '("id","expiresAt","token","updatedAt","userId")'+
      ' VALUES($1,$2,$3,$4,$5)',[randomUUID(),future,otherToken,now,otherOwner]);
    assert.equal(await verifier(incoming(cookie(otherToken))),null,
      "An authenticated but non-owner user is not an approval authority");

    await db.query('UPDATE "users" SET "emailVerified"=false WHERE "id"=$1',
      [owner]);
    assert.equal(await verifier(incoming(cookie(token))),null,
      "Unverified owner account is rejected");
    await db.query('UPDATE "users" SET "emailVerified"=true WHERE "id"=$1',
      [owner]);
    await db.query('UPDATE "session" SET "expiresAt"=$2 WHERE "id"=$1',
      [sessionId,new Date(now.getTime()-60_000)]);
    assert.equal(await verifier(incoming(cookie(token))),null,
      "An expired Better Auth session is rejected");
    const renewedToken=randomBytes(32).toString("base64url");
    const renewedSessionId=randomUUID();
    await db.query('INSERT INTO "session"'+
      '("id","expiresAt","token","updatedAt","userId")'+
      ' VALUES($1,$2,$3,$4,$5)',
      [renewedSessionId,future,renewedToken,now,owner]);
    const fresh=await verifier(incoming(cookie(renewedToken)));
    assert.ok(fresh);
    assert.notEqual(fresh.csrf,issued.csrf);
    await db.query('DELETE FROM "session" WHERE "id"=$1',[renewedSessionId]);
    assert.equal(await verifier(incoming(cookie(renewedToken))),null);
  });
});
