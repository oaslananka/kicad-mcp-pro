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
    for(const name of ["001_inventory","007_device_pairing","008_device_credentials","023_device_recovery","024_initial_enrollment_receipts"]){
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
    // The refusal response may be lost after the transaction commits.
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
    const loser=winner===revoked?competing:revoked;
    assert.equal((await store.enroll(loser.challenge.id,loser.challenge.deviceCode,
      loser.signature,true,recovery)).kind,"recovery_denied");
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
    const historical={...winningResult,kind:"recovery_receipt"};
    assert.deepEqual(await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery),historical);
    assert.equal((await pool.query("SELECT enabled FROM devices WHERE id=$1",[winningResult.deviceId])).rows[0].enabled,false);
    await pool.query("UPDATE device_credentials SET revoked_at=clock_timestamp() WHERE device_id=$1",[winningResult.deviceId]);
    assert.deepEqual(await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery),historical);
    assert.ok((await pool.query("SELECT revoked_at FROM device_credentials WHERE device_id=$1",[winningResult.deviceId])).rows[0].revoked_at);
    await pool.query("UPDATE device_credentials SET revoked_at=NULL WHERE device_id=$1",[winningResult.deviceId]);
    await pool.query("UPDATE devices SET enabled=true WHERE id=$1",[winningResult.deviceId]);
    await pool.query("UPDATE pairing_challenges SET created_at=clock_timestamp()-interval '6 minutes',expires_at=clock_timestamp()-interval '2 minutes' WHERE id=$1",[winner.challenge.id]);
    // Expiry prevents new enrollment, not read-only reconciliation of an
    // already committed binding by its exact original device proof.
    assert.deepEqual(await store.enroll(winner.challenge.id,winner.challenge.deviceCode,
      winner.signature,true,recovery),winningResult);
    const expiredIdentity={deviceId:randomUUID(),ownerSub:owner};
    const expired=await attempt(expiredIdentity);
    await pool.query("UPDATE pairing_challenges SET created_at=clock_timestamp()-interval '6 minutes',expires_at=clock_timestamp()-interval '2 minutes' WHERE id=$1",[expired.challenge.id]);
    assert.equal((await store.enroll(expired.challenge.id,expired.challenge.deviceCode,
      expired.signature,true,expiredIdentity)).kind,"recovery_denied");
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
    const missingWinner=missingResults[0]?.kind==="enrolled"?missing:concurrentMissing;
    assert.deepEqual(await store.enroll(missingWinner.challenge.id,missingWinner.challenge.deviceCode,
      missingWinner.signature,true,missingIdentity),{...replacement,kind:"recovery_receipt"});
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices WHERE id=$1",[replacement.deviceId])).rows[0].n,0);
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

test("initial enrollment retries only its opted-in signed operation",{skip:!url},async()=>{
  const admin=new pg.Pool({connectionString:url});
  const schema="initial_"+randomBytes(8).toString("hex");
  let pool:pg.Pool|undefined;
  try{
    await admin.query('CREATE SCHEMA "'+schema+'"');
    const scoped=new URL(url!);
    scoped.searchParams.set("options","-c search_path="+schema);
    pool=new pg.Pool({connectionString:scoped.toString(),max:4});
    for(const name of ["001_inventory","007_device_pairing","008_device_credentials","023_device_recovery","024_initial_enrollment_receipts"]){
      await pool.query(await readFile(new URL("../db/"+name+".pgsql",import.meta.url),"utf8"));
    }
    const store=new PgPairingChallenges(pool,randomBytes(32));
    const key=generateKeyPairSync("ed25519");
    const challenge=await store.issue("Initial PC",key.publicKey.export({type:"spki",format:"der"}));
    const signature=sign(null,Buffer.from("kicad-cloud-pairing-initial-v1\0"+challenge.id+"\0"+challenge.deviceCode),key.privateKey);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true)).kind,"unavailable");
    assert.equal(await store.review(challenge.id,"owner",challenge.userCode,"approve"),"approved");
    const legacy=sign(null,redemptionProof(challenge.id,challenge.deviceCode),key.privateKey);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,legacy,true,undefined,true)).kind,"unavailable");
    const results=await Promise.all([1,2].map(()=>store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true)));
    assert.equal(results[0]?.kind,"enrolled");
    assert.deepEqual(results[0],results[1]);
    const result=results[0];
    if(result?.kind!=="enrolled")throw Error("initial enrollment failed");
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,signature,true)).kind,"unavailable");
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,legacy,true)).kind,"unavailable");
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,Buffer.alloc(64),true,undefined,true)).kind,"unavailable");
    await pool.query("UPDATE pairing_challenges SET created_at=clock_timestamp()-interval '6 minutes',expires_at=clock_timestamp()-interval '2 minutes' WHERE id=$1",[challenge.id]);
    assert.deepEqual(await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true),result);
    await pool.query("UPDATE devices SET enabled=false WHERE id=$1",[result.deviceId]);
    assert.deepEqual(await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true),{...result,kind:"initial_receipt"});
    await pool.query("UPDATE device_credentials SET revoked_at=clock_timestamp() WHERE device_id=$1",[result.deviceId]);
    assert.deepEqual(await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true),{...result,kind:"initial_receipt"});
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices")).rows[0].n,1);
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM projects")).rows[0].n,0);
    await pool.query("DELETE FROM devices WHERE id=$1",[result.deviceId]);
    assert.deepEqual(await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true),{...result,kind:"initial_receipt"});
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices")).rows[0].n,0);
    // The normal one-use enrollment is not retroactively opted into replay.
    const legacyKey=generateKeyPairSync("ed25519");
    const legacyChallenge=await store.issue("Legacy",legacyKey.publicKey.export({type:"spki",format:"der"}));
    await store.review(legacyChallenge.id,"owner",legacyChallenge.userCode,"approve");
    const legacyResult=await store.enroll(legacyChallenge.id,legacyChallenge.deviceCode,
      sign(null,redemptionProof(legacyChallenge.id,legacyChallenge.deviceCode),legacyKey.privateKey),true);
    assert.equal(legacyResult.kind,"enrolled");
    const newProof=sign(null,redemptionProof(legacyChallenge.id,legacyChallenge.deviceCode,undefined,true),legacyKey.privateKey);
    assert.equal((await store.enroll(legacyChallenge.id,legacyChallenge.deviceCode,newProof,true,undefined,true)).kind,"unavailable");
    // Expiry and browser refusal are authenticated terminal outcomes.
    for(const outcome of ["expired","denied"]){
      const candidateKey=generateKeyPairSync("ed25519");
      const candidate=await store.issue("Candidate",candidateKey.publicKey.export({type:"spki",format:"der"}));
      await store.review(candidate.id,"owner",candidate.userCode,outcome==="denied"?"deny":"approve");
      if(outcome==="expired")await pool.query("UPDATE pairing_challenges SET created_at=clock_timestamp()-interval '6 minutes',expires_at=clock_timestamp()-interval '2 minutes' WHERE id=$1",[candidate.id]);
      const proof=sign(null,redemptionProof(candidate.id,candidate.deviceCode,undefined,true),candidateKey.privateKey);
      assert.equal((await store.enroll(candidate.id,candidate.deviceCode,proof,true,undefined,true)).kind,"initial_denied");
      assert.equal((await store.enroll(candidate.id,candidate.deviceCode,Buffer.alloc(64),true,undefined,true)).kind,"unavailable");
      assert.equal((await store.enroll(candidate.id,candidate.deviceCode,proof,true,{deviceId:randomUUID(),ownerSub:"owner"},true)).kind,"unavailable");
    }
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM devices")).rows[0].n,1);
    // Existing challenge pruning removes the historical receipt too, without
    // introducing an indefinite retention obligation.
    await pool.query("DELETE FROM pairing_challenges WHERE id=$1",[challenge.id]);
    assert.equal((await pool.query("SELECT count(*)::int AS n FROM device_initial_enrollments")).rows[0].n,0);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,signature,true,undefined,true)).kind,"unavailable");
  }finally{
    await pool?.end();
    await admin.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await admin.end();
  }
});
