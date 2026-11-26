import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import {test} from "node:test";
import {readFile} from "node:fs/promises";
import pg from "pg";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {issuePairing,reviewPairing,redemptionProof} from "../src/device-pairing.js";

for(const scenario of ["missing","revoked","healthy","disabled","foreign","no-credential","wrong-account","tampered"]){
  test("replacement enrollment: "+scenario,async()=>{
    const owner="owner-1", old=randomUUID();
    const key=generateKeyPairSync("ed25519"), secret=randomBytes(32), now=Date.now();
    const issued=issuePairing(secret,now,"Replacement",key.publicKey.export({type:"spki",format:"der"}));
    const approved=reviewPairing(issued.record,secret,now,owner,issued.userCode,"approve").record;
    const recovery={deviceId:old,ownerSub:scenario==="wrong-account"?"owner-2":owner};
    const proof=sign(null,redemptionProof(approved.id,issued.deviceCode,recovery),key.privateKey);
    const statements:string[]=[];
    const db={
      async query(sql:string){
        statements.push(sql);
        if(sql.includes("FROM pairing_challenges")){
          return {rows:[{
            id:approved.id,device_alias:approved.deviceAlias,device_public_key_der:approved.devicePublicKeyDer,
            device_fingerprint:approved.deviceFingerprint,user_code_mac:approved.userCodeMac,
            device_code_mac:approved.deviceCodeMac,expires_at:new Date(approved.expiresAtMs),
            state:approved.state,attempts:approved.attempts,owner_sub:approved.ownerSub
          }]};
        }
        if(sql.includes("clock_timestamp()"))return {rows:[{ms:String(now)}]};
        if(sql.includes("FROM devices")){
          return {rows:scenario==="missing"?[]:[{owner_sub:scenario==="foreign"?"owner-2":owner}]};
        }
        if(sql.includes("FROM device_credentials")){
          return {rows:scenario==="no-credential"?[]:[{
            revoked:scenario==="revoked",owner_sub:owner
          }]};
        }
        return {rows:[],rowCount:1};
      },release(){}
    };
    const store=new PgPairingChallenges({connect:async()=>db} as never,secret);
    const result=await store.enroll(approved.id,issued.deviceCode,proof,true,
      scenario==="tampered"?{...recovery,deviceId:randomUUID()}:recovery);
    const allowed=scenario==="missing"||scenario==="revoked";
    assert.equal(result.kind,allowed?"enrolled":scenario==="tampered"?"unavailable":"recovery_denied");
    assert.equal(statements.some(s=>s.startsWith("INSERT INTO devices")),allowed);
    assert.equal(statements.some(s=>s.startsWith("INSERT INTO projects")),false);
  });
}

const url=process.env.TEST_DATABASE_URL;
test("PostgreSQL replacement keeps active devices and never creates a project",{skip:!url},async()=>{
  const admin=new pg.Pool({connectionString:url});
  const schema="recovery_"+randomBytes(8).toString("hex");
  let pool:pg.Pool|undefined;
  try{
    await admin.query('CREATE SCHEMA "'+schema+'"');
    const scoped=new URL(url!);
    scoped.searchParams.set("options","-c search_path="+schema);
    pool=new pg.Pool({connectionString:scoped.toString(),max:4});
    for(const name of ["001_inventory","007_device_pairing","008_device_credentials","023_device_recovery"]){
      await pool.query(await readFile(new URL("../db/"+name+".pgsql",import.meta.url),"utf8"));
    }
    const store=new PgPairingChallenges(pool,randomBytes(32));
    const owner="test-owner";
    async function approved(){
      const key=generateKeyPairSync("ed25519");
      const challenge=await store.issue("Test PC",key.publicKey.export({type:"spki",format:"der"}));
      assert.equal(await store.review(challenge.id,owner,challenge.userCode,"approve"),"approved");
      return {key,challenge};
    }
    const first=await approved();
    const original=await store.enroll(first.challenge.id,first.challenge.deviceCode,
      sign(null,redemptionProof(first.challenge.id,first.challenge.deviceCode),first.key.privateKey),true);
    assert.equal(original.kind,"enrolled");
    if(original.kind!=="enrolled")throw Error("test enrollment failed");
    const recovery={deviceId:original.deviceId,ownerSub:owner};
    async function attempt(identity=recovery){
      const {key,challenge}=await approved();
      const signature=sign(null,redemptionProof(challenge.id,challenge.deviceCode,identity),key.privateKey);
      return {challenge,signature};
    }
    const healthy=await attempt();
    assert.equal((await store.enroll(healthy.challenge.id,healthy.challenge.deviceCode,
      healthy.signature,true,recovery)).kind,"recovery_denied");
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices")).rows[0].n,1);
    await pool.query("UPDATE devices SET enabled=false WHERE id=$1",[original.deviceId]);
    const disabled=await attempt();
    assert.equal((await store.enroll(disabled.challenge.id,disabled.challenge.deviceCode,
      disabled.signature,true,recovery)).kind,"recovery_denied");
    await pool.query("UPDATE device_credentials SET revoked_at=clock_timestamp() WHERE device_id=$1",[original.deviceId]);
    const revoked=await attempt();
    const competing=await attempt();
    const results=await Promise.all([revoked,competing].map(item=>store.enroll(
      item.challenge.id,item.challenge.deviceCode,item.signature,true,recovery)));
    assert.deepEqual(results.map(r=>r.kind).sort(),["enrolled","recovery_denied"]);
    const winner=results[0]?.kind==="enrolled"?revoked:competing;
    const winningResult=results.find(r=>r.kind==="enrolled");
    assert.ok(winningResult&&winningResult.kind==="enrolled");
    // A lost response may be recovered only with the very same signed challenge.
    assert.deepEqual(await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery),winningResult);
    assert.equal((await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      Buffer.alloc(64),true,recovery)).kind,"unavailable");
    assert.equal((await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,{...recovery,deviceId:randomUUID()})).kind,"unavailable");
    await pool.query("UPDATE devices SET enabled=false WHERE id=$1",[winningResult.deviceId]);
    assert.equal((await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery)).kind,"unavailable");
    await pool.query("UPDATE devices SET enabled=true WHERE id=$1",[winningResult.deviceId]);
    await pool.query("UPDATE pairing_challenges SET created_at=clock_timestamp()-interval '6 minutes',expires_at=clock_timestamp()-interval '2 minutes' WHERE id=$1",[winner.challenge.id]);
    assert.equal((await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery)).kind,"unavailable");
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices")).rows[0].n,2);
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM projects")).rows[0].n,0);
    const missingIdentity={deviceId:randomUUID(),ownerSub:owner};
    const missing=await attempt(missingIdentity);
    const concurrentMissing=await attempt(missingIdentity);
    const missingResults=await Promise.all([missing,concurrentMissing].map(item=>store.enroll(
      item.challenge.id,item.challenge.deviceCode,item.signature,true,missingIdentity)));
    assert.deepEqual(missingResults.map(r=>r.kind).sort(),["enrolled","recovery_denied"]);
    const replacement=missingResults.find(r=>r.kind==="enrolled");
    assert.ok(replacement&&replacement.kind==="enrolled");
    const durable=await pool.query("SELECT count(*)::int AS n FROM device_replacements");
    assert.equal(durable.rows[0].n,2);
    await pool.query("DELETE FROM devices WHERE id=$1",[replacement.deviceId]);
    const stale=await attempt(missingIdentity);
    assert.equal((await store.enroll(stale.challenge.id,stale.challenge.deviceCode,
      stale.signature,true,missingIdentity)).kind,"recovery_denied");
    const nextIdentity={deviceId:replacement.deviceId,ownerSub:owner};
    const next=await attempt(nextIdentity);
    assert.equal((await store.enroll(next.challenge.id,next.challenge.deviceCode,
      next.signature,true,nextIdentity)).kind,"enrolled");
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM projects")).rows[0].n,0);
  }finally{
    await pool?.end();
    await admin.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await admin.end();
  }
});
