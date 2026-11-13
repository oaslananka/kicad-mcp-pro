import assert from "node:assert/strict";
import {test} from "node:test";
import {ownerApiResponse} from "../src/owner-api.js";
import type {PgOwnerApiAccess} from "../src/owner-api.js";
import type {GrantManagement} from "../src/grants.js";

const origin="https://cloud.example.test";
const projectId="22222222-2222-4222-8222-222222222222";
const clientId="https://chatgpt.com/oauth/client.json";

test("owner management API explicitly stores readonly or write, never inferring edit permission",async()=>{
  const calls:Array<{owner:string;project:string;client:string;enabled:boolean;
    mode?:string}>=[];
  const ownerApi={
    verifyToken:async(token:string)=>token==="owner-token"?"owner-fixture":null
  } as PgOwnerApiAccess;
  const grants={
    setBrowserGrant:async(owner:string,project:string,client:string,enabled:boolean,
      mode?:"readonly"|"write")=>{
      calls.push({owner,project,client,enabled,mode});
      return mode!=="write"||client===clientId;
    }
  } as GrantManagement;
  async function post(body:Record<string,unknown>,token="owner-token"){
    return ownerApiResponse(new Request(origin+"/api/owner/v1/access/set",{
      method:"POST",headers:{
        "Content-Type":"application/json","Authorization":"Bearer "+token
      },body:JSON.stringify(body)
    }),origin,{ownerApi,grants});
  }
  const base={projectId,clientId,enabled:true};
  const readonly=await post(base);
  assert.equal(readonly?.status,200);
  assert.deepEqual(await readonly?.json(),{
    updated:true,maxMode:"readonly",remoteEditingAvailable:false
  });
  const writable=await post({...base,maxMode:"write"});
  assert.equal(writable?.status,200);
  assert.deepEqual(await writable?.json(),{
    updated:true,maxMode:"write",remoteEditingAvailable:false
  });
  const disabled=await post({...base,enabled:false,maxMode:"write"});
  assert.equal(disabled?.status,200);
  assert.deepEqual(await disabled?.json(),{
    updated:true,maxMode:"readonly",remoteEditingAvailable:false
  });
  assert.equal(calls.length,3);
  assert.deepEqual(calls[0],{owner:"owner-fixture",project:projectId,
    client:clientId,enabled:true,mode:"readonly"});
  assert.deepEqual(calls[1],{owner:"owner-fixture",project:projectId,
    client:clientId,enabled:true,mode:"write"});
  assert.equal((await post({...base,maxMode:"manufacturing"}))?.status,400);
  assert.equal((await post({...base,maxMode:"admin"}))?.status,400);
  assert.equal((await post({...base,arbitrary:"field"}))?.status,400);
  assert.equal((await post({...base,maxMode:"write"},"bad-token"))?.status,401);
  assert.equal(calls.length,3,"invalid/unauthorized inputs must not call the grant store");
});
