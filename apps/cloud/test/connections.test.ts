import assert from "node:assert/strict";
import {test} from "node:test";
import {connectionsResponse} from "../src/connections.js";
import type {BrowserIdentity} from "../src/browser.js";
import type {GrantManagement} from "../src/grants.js";

const origin="http://127.0.0.1:8787";
const consentA={id:"consent-a",userId:"owner-a",clientId:"chatgpt",scopes:["openid","projects:read"]};
const consentB={id:"consent-b",userId:"owner-b",clientId:"claude",scopes:["projects:read"]};
type MockOptions={user?:string|null;failGrants?:boolean;failDelete?:boolean;spoofClient?:boolean};
function fixture(options:MockOptions={}){
  const calls:string[]=[];
  const currentUser=options.user===undefined?"owner-a":options.user;
  let consents=[consentA,consentB];
  const auth={
    $context:Promise.resolve({secret:"test-only-identity-secret"}),
    api:{
      getSession:async()=>currentUser?{session:{id:"session-a"},user:{id:currentUser}}:null,
      getOAuthConsents:async()=>consents.filter(c=>c.userId===currentUser),
      getOAuthConsent:async({query}:{query:{id:string}})=>consents.find(c=>c.id===query.id && c.userId===currentUser)??null,
      deleteOAuthConsent:async({body}:{body:{id:string}})=>{
        calls.push("delete:"+body.id);
        if(options.failDelete) throw new Error("backend unavailable");
        consents=consents.filter(c=>c.id!==body.id);
      }
    },
    handler:async(request:Request)=>{
      const clientId=new URL(request.url).searchParams.get("client_id");
      return Response.json({client_id:options.spoofClient?"spoof":clientId,client_name:"<script>evil()</script> & Client"});
    }
  } as unknown as BrowserIdentity;
  const grants:GrantManagement={
    async setGrant(){return false;},
    async revokeClient(user,client){
      calls.push("disable:"+user+":"+client);
      if(options.failGrants) throw new Error("db error");
      return 3;
    }
  };
  return {auth,grants,calls};
}
async function view(f:ReturnType<typeof fixture>){
  return connectionsResponse(new Request(origin+"/connections"),f.auth,origin,f.grants);
}
function inputs(page:string):{id:string;clientId:string;csrf:string}{
  const id=/name="id" value="([^"]+)"/.exec(page)?.[1]??"";
  const clientId=/name="client_id" value="([^"]+)"/.exec(page)?.[1]??"";
  const csrf=/name="csrf" value="([^"]+)"/.exec(page)?.[1]??"";
  return {id,clientId,csrf};
}
function post(fields:{id:string;clientId:string;csrf:string},cookie:string,originHeader=origin) {
  return new Request(origin+"/connections/revoke",{
    method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded","Origin":originHeader,"Cookie":cookie},
    body:new URLSearchParams({id:fields.id,client_id:fields.clientId,csrf:fields.csrf})
  });
}
test("connection list requires session and escapes untrusted client metadata",async()=>{
  const noSession=await view(fixture({user:null}));
  assert.equal(noSession?.status,303);
  assert.equal(noSession?.headers.get("location"),"/sign-in");
  const response=await view(fixture());
  assert.equal(response?.status,200);
  const body=await response!.text();
  assert.match(body,/&lt;script&gt;/);
  assert.equal(body.toLowerCase().includes("<script"),false);
  assert.match(body,/projects:read/);
  assert.doesNotMatch(body,/consent-b/);
  assert.match(response!.headers.get("set-cookie")??"",/HttpOnly; SameSite=Strict/);
  // HTML form navigations send Origin: null under no-referrer; strict Origin validation must remain intact.
  assert.equal(response!.headers.get("Referrer-Policy"),"same-origin");
});
test("revoke disables project grants before deleting own OAuth consent",async()=>{
  const f=fixture();
  const response=await view(f);
  const fields=inputs(await response!.text());
  const state=(response!.headers.get("set-cookie")??"").split(";")[0];
  const result=await connectionsResponse(post(fields,state),f.auth,origin,f.grants);
  assert.equal(result?.status,303);
  assert.equal(result?.headers.get("location"),"/connections?removed=1");
  assert.deepEqual(f.calls,["disable:owner-a:chatgpt","delete:consent-a"]);
  const listAfter=await view(f);
  assert.doesNotMatch(await listAfter!.text(),/consent-a/);
});
test("tampered, cross-origin, cross-user and no-cookie requests cannot revoke",async()=>{
  const f=fixture();
  const response=await view(f);
  const fields=inputs(await response!.text());
  const state=(response!.headers.get("set-cookie")??"").split(";")[0];
  assert.equal((await connectionsResponse(post(fields,state,"https://attacker.invalid"),f.auth,origin,f.grants))?.status,403);
  assert.equal((await connectionsResponse(post(fields,""),f.auth,origin,f.grants))?.status,403);
  assert.equal((await connectionsResponse(post({...fields,id:"consent-b"},state),f.auth,origin,f.grants))?.status,403);
  assert.equal((await connectionsResponse(post({...fields,clientId:"claude"},state),f.auth,origin,f.grants))?.status,403);
  const other=fixture({user:"owner-b"});
  assert.equal((await connectionsResponse(post(fields,state),other.auth,origin,other.grants))?.status,403);
  assert.deepEqual(f.calls,[]);
  assert.deepEqual(other.calls,[]);
});
test("failed DB operation does not delete OAuth consent; failed OAuth deletion remains fail closed",async()=>{
  const db=fixture({failGrants:true});
  const list=await view(db);
  const form=inputs(await list!.text());
  const state=(list!.headers.get("set-cookie")??"").split(";")[0];
  assert.equal((await connectionsResponse(post(form,state),db.auth,origin,db.grants))?.status,503);
  assert.deepEqual(db.calls,["disable:owner-a:chatgpt"]);
  const api=fixture({failDelete:true});
  const apiList=await view(api);
  const apiForm=inputs(await apiList!.text());
  const apiState=(apiList!.headers.get("set-cookie")??"").split(";")[0];
  assert.equal((await connectionsResponse(post(apiForm,apiState),api.auth,origin,api.grants))?.status,502);
  assert.deepEqual(api.calls,["disable:owner-a:chatgpt","delete:consent-a"]);
});
test("authenticated consent of another owner cannot be revoked even with a forged form state",async()=>{
  const f=fixture();
  const response=await view(f);
  const form=inputs(await response!.text());
  const state=(response!.headers.get("set-cookie")??"").split(";")[0];
  // The hidden id is bound into the token, so replacing it cannot trigger a delete.
  assert.equal((await connectionsResponse(post({...form,id:"consent-b"},state),f.auth,origin,f.grants))?.status,403);
  assert.deepEqual(f.calls,[]);
});


test("browser connections guidance does not expose an external endpoint to an anonymous visitor",async()=>{
  const guest=fixture({user:null});
  const result=await connectionsResponse(
    new Request(origin+"/connections"),guest.auth,origin,guest.grants);
  assert.equal(result?.status,303);
  assert.equal(result.headers.get("Location"),"/sign-in");
});
