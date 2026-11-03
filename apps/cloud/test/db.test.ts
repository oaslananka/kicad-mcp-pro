import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import pg from "pg";
import { PgGrantManagement } from "../src/grants.js";

const url = process.env.TEST_DATABASE_URL;
test("postgres enforces ownership, disabled projects and opaque-only records", {skip:!url}, async()=>{
  const admin = new pg.Pool({connectionString:url});
  const schema = await readFile(new URL("../db/001_inventory.pgsql",import.meta.url),"utf8");
  const grantsSchema = await readFile(new URL("../db/002_client_grants.pgsql",import.meta.url),"utf8");
  const revokeSchema=await readFile(new URL("../db/004_client_revocation.pgsql",import.meta.url),"utf8");
  const cutoffSchema=await readFile(new URL("../db/005_token_cutoff.pgsql",import.meta.url),"utf8");
  const deviceA = "2e850e45-e34b-4f14-a042-ed7449bf42de";
  const deviceB = "bb4de070-a6f1-45ab-9ad6-62983605d6be";
  const projectA = "6abdd0d3-4665-4db4-bc58-a8aca819a123";
  const projectDisabled = "d0531d7a-dc6f-4472-8886-7e98885670c4";
  const projectB = "94017537-b93b-47fa-96b9-0e4b1872df51";
  const inventory = new PgGrantManagement(url!);
  try {
    await admin.query(schema);
    await admin.query(grantsSchema);
    await admin.query(revokeSchema);
    await admin.query(cutoffSchema);
    await admin.query("INSERT INTO devices (id,owner_sub,alias,enabled) VALUES ($1,'owner-a','A',true),($2,'owner-b','B',true)",[deviceA,deviceB]);
    await admin.query("INSERT INTO projects (id,device_id,owner_sub,alias,enabled) VALUES ($1,$2,'owner-a','USB-C',true),($3,$2,'owner-a','Disabled',false),($4,$5,'owner-b','Other',true)",[projectA,deviceA,projectDisabled,projectB,deviceB]);
    assert.equal((await inventory.listProjects("owner-a","client-a")).length,0);
    await admin.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled) VALUES ($1,'owner-a','client-a',true)",[projectA]);
    const projects = await inventory.listProjects("owner-a","client-a");
    assert.deepEqual(projects.map(p=>p.alias),["USB-C"]);
    assert.equal(projects[0].available,false);
    assert.equal(await inventory.getProject("owner-b","client-a",projectA),null);
    assert.equal(await inventory.getProject("owner-a","client-a",projectDisabled),null);
    assert.equal((await inventory.listDevices("owner-a","client-a")).length,1);
    assert.equal((await inventory.listDevices("owner-a","client-b")).length,0);
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,0);
    await assert.rejects(admin.query("INSERT INTO project_client_grants(project_id,owner_sub,client_id,enabled) VALUES ($1,'owner-b','client-b',true)",[projectA]));
    assert.equal(await inventory.setGrant("owner-b","portal",projectA,{clientId:"client-b",enabled:true,maxMode:"readonly"}),false);
    await assert.rejects(inventory.setGrant("owner-a","portal",projectA,{clientId:"client-a",enabled:true,maxMode:"write"}),/POLICY_EXCEEDS_PROJECT/);
    assert.equal(await inventory.setGrant("owner-a","portal",projectA,{clientId:"client-b",enabled:true,maxMode:"readonly"}),true);
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,1);
    assert.equal(await inventory.setGrant("owner-a","portal",projectA,{clientId:"client-b",enabled:false,maxMode:"readonly"}),true);
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,0);
    const audit=await admin.query("SELECT operation FROM client_grant_audit WHERE owner_sub='owner-a' AND project_id=$1",[projectA]);
    assert.equal(audit.rows.length,2);
    await inventory.setGrant("owner-a","portal",projectA,{clientId:"client-b",enabled:true,maxMode:"readonly"});
    assert.equal(await inventory.revokeClient("owner-b","client-b"),0);
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,1);
    const issuedBefore=Math.floor(Date.now()/1000)-60;
    assert.equal(await inventory.revokeClient("owner-a","client-b"),1);
    assert.equal(await inventory.isAccessTokenAllowed("owner-a","client-b",issuedBefore),false);
    assert.equal(await inventory.isAccessTokenAllowed("owner-b","client-b",issuedBefore),false);
    assert.equal(await inventory.isAccessTokenAllowed("owner-b","unrevoked-client",issuedBefore),true);
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,0);
    assert.equal((await inventory.listDevices("owner-a","client-b")).length,0);
    assert.equal(await inventory.revokeClient("owner-a","client-b"),0);
    await inventory.setGrant("owner-a","portal",projectA,{clientId:"client-b",enabled:true,maxMode:"readonly"});
    assert.equal((await inventory.listProjects("owner-a","client-b")).length,1);
    assert.equal(await inventory.isAccessTokenAllowed("owner-a","client-b",issuedBefore),false);
    assert.equal(await inventory.isAccessTokenAllowed("owner-a","client-b",Math.floor(Date.now()/1000)+10),true);
    const revokes=await admin.query("SELECT operation FROM client_grant_audit WHERE owner_sub='owner-a' AND project_id=$1 AND operation='client.revoke'",[projectA]);
    assert.equal(revokes.rows.length,1);
    await assert.rejects(admin.query("INSERT INTO projects(id,device_id,owner_sub,alias) VALUES ('1961d3a0-5e7b-44a5-b903-3c4efb2531a7',$1,'owner-a','Injected')",[deviceB]));
  } finally {
    try{await admin.query("DELETE FROM client_grant_audit WHERE project_id=$1",[projectA]);}catch{}
    try{await admin.query("DELETE FROM projects WHERE id = ANY($1::uuid[])",[[projectA,projectDisabled,projectB]]);}catch{}
    try{await admin.query("DELETE FROM devices WHERE id = ANY($1::uuid[])",[[deviceA,deviceB]]);}catch{}
    await inventory.close();
    await admin.end();
  }
});
