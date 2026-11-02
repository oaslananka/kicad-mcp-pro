import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,sign} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import pg from "pg";
import {PgPairingChallenges} from "../src/pairing-store.js";
import {redemptionProof} from "../src/device-pairing.js";

const connectionString=process.env.TEST_DATABASE_URL;

test("atomic enrollment, owner-scoped revocation and grant disablement",
  {skip:!connectionString},async()=>{
  const root=new pg.Pool({connectionString});
  const schema="enrollment_"+randomBytes(7).toString("hex");
  let db:pg.Pool|undefined;
  try{
    await root.query('CREATE SCHEMA "'+schema+'"');
    const scoped=new URL(connectionString!);
    scoped.searchParams.set("options","-c search_path="+schema);
    db=new pg.Pool({connectionString:scoped.toString(),max:6});
    for(const file of ["001_inventory.pgsql","002_client_grants.pgsql",
      "007_device_pairing.pgsql","008_device_credentials.pgsql", "009_device_handshake.pgsql","010_connector_sessions.pgsql"]){
      await db.query(await readFile(new URL("../db/"+file,import.meta.url),"utf8"));
    }
    const keys=generateKeyPairSync("ed25519");
    const publicDer=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
    const owner="owner-1";
    const store=new PgPairingChallenges(db,randomBytes(32));
    const challenge=await store.issue("KiCad Device",publicDer);
    const proof=sign(null,redemptionProof(challenge.id,challenge.deviceCode),keys.privateKey);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,proof)).kind,"unavailable");
    assert.equal(await store.review(challenge.id,owner,challenge.userCode,"approve"),"approved");

    // Valid proof is required even after browser approval.
    const attacker=generateKeyPairSync("ed25519");
    const forged=sign(null,redemptionProof(challenge.id,challenge.deviceCode),attacker.privateKey);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,forged)).kind,"unavailable");
    assert.equal((await store.enroll(challenge.id,"wrong",proof)).kind,"unavailable");

    const contenders=await Promise.all([
      store.enroll(challenge.id,challenge.deviceCode,proof),
      store.enroll(challenge.id,challenge.deviceCode,proof)
    ]);
    assert.deepEqual(contenders.map(r=>r.kind).sort(),["enrolled","unavailable"]);
    const success=contenders.find((r):r is Extract<typeof r,{kind:"enrolled"}>=>r.kind==="enrolled");
    assert.ok(success);
    assert.equal(success.ownerSub,owner);
    assert.equal((await store.enroll(challenge.id,challenge.deviceCode,proof)).kind,"unavailable");
    const records=await db.query(
      "SELECT d.enabled,d.owner_sub,c.key_fingerprint,c.pairing_challenge_id,c.revoked_at "+
      "FROM devices d JOIN device_credentials c ON c.device_id=d.id WHERE d.id=$1",
      [success.deviceId]);
    assert.equal(records.rows.length,1);
    assert.equal(records.rows[0].owner_sub,owner);
    assert.equal(records.rows[0].enabled,false);
    assert.equal(records.rows[0].revoked_at,null);
    assert.equal(records.rows[0].pairing_challenge_id,challenge.id);
    assert.equal(await store.activeDevicePublicKey(owner,success.deviceId),null);

    // Test-only simulation of a future verified owner enable action.
    await db.query("UPDATE devices SET enabled=true WHERE id=$1 AND owner_sub=$2",
      [success.deviceId,owner]);
    assert.deepEqual(await store.activeDevicePublicKey(owner,success.deviceId),publicDer);
    assert.equal(await store.activeDevicePublicKey("other-owner",success.deviceId),null);
    assert.equal(await store.activeDevicePublicKey(owner,"invalid"),null);

    const project="a39a9f88-d390-4431-8cd4-2c4430aad321";
    await db.query(
      "INSERT INTO projects(id,owner_sub,device_id,alias,enabled) VALUES($1,$2,$3,'Demo',true)",
      [project,owner,success.deviceId]);
    await db.query(
      "INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled) "+
      "VALUES($1,$2,'client-1',true)",[project,owner]);
    assert.equal(await store.revokeDevice("other-owner",success.deviceId),false);
    assert.deepEqual(await store.activeDevicePublicKey(owner,success.deviceId),publicDer);

    const revoked=await Promise.all([
      store.revokeDevice(owner,success.deviceId),
      store.revokeDevice(owner,success.deviceId)
    ]);
    assert.deepEqual(revoked,[true,true]);
    assert.equal(await store.activeDevicePublicKey(owner,success.deviceId),null);
    // Even if a separate caller erroneously re-enables the device flag,
    // the irrevocable key cutoff must still deny authentication.
    await db.query("UPDATE devices SET enabled=true WHERE id=$1",[success.deviceId]);
    assert.equal(await store.activeDevicePublicKey(owner,success.deviceId),null);
    await db.query("UPDATE devices SET enabled=false WHERE id=$1",[success.deviceId]);
    const disabled=await db.query(
      "SELECT d.enabled,p.enabled AS project_enabled,g.enabled AS grant_enabled,"+
      "c.revoked_at FROM devices d "+
      "JOIN projects p ON p.device_id=d.id "+
      "JOIN project_client_grants g ON g.project_id=p.id "+
      "JOIN device_credentials c ON c.device_id=d.id WHERE d.id=$1",
      [success.deviceId]);
    assert.equal(disabled.rows.length,1);
    assert.equal(disabled.rows[0].enabled,false);
    assert.equal(disabled.rows[0].project_enabled,false);
    assert.equal(disabled.rows[0].grant_enabled,false);
    assert.ok(disabled.rows[0].revoked_at instanceof Date);
    assert.equal(await store.revokeDevice(owner,"invalid"),false);

    // Same public key cannot get a second credential. The failed INSERT
    // must rollback challenge consumption and the attempted device row.
    const duplicate=await store.issue("Duplicate",publicDer);
    assert.equal(await store.review(duplicate.id,owner,duplicate.userCode,"approve"),"approved");
    const duplicateProof=sign(null,redemptionProof(duplicate.id,duplicate.deviceCode),keys.privateKey);
    await assert.rejects(store.enroll(duplicate.id,duplicate.deviceCode,duplicateProof),
      (err:unknown)=>(err as {code?:string}).code==="23505");
    const rolledBack=await db.query(
      "SELECT state FROM pairing_challenges WHERE id=$1",[duplicate.id]);
    assert.equal(rolledBack.rows[0].state,"approved");
    assert.equal((await db.query("SELECT count(*)::integer AS total FROM devices")).rows[0].total,1);
    assert.equal((await db.query("SELECT count(*)::integer AS total FROM device_credentials")).rows[0].total,1);
  }finally{
    await db?.end();
    await root.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await root.end();
  }
});
