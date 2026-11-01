import assert from "node:assert/strict";
import {generateKeyPairSync,randomBytes,randomUUID,sign} from "node:crypto";
import type {Server} from "node:http";
import type {AddressInfo} from "node:net";
import {test} from "node:test";
import type {Pool} from "pg";
import {inIsolatedDatabase} from "./isolated-db.js";
import {createHttpServer} from "../src/http.js";
import type {Config} from "../src/config.js";
import type {BrowserIdentity} from "../src/browser.js";
import {PgPairingReview} from "../src/pairing-review.js";
import {PgPairingDeviceAPI} from "../src/pairing-device-api.js";
import {PgDeviceManagement} from "../src/device-management.js";
import {PgGrantManagement} from "../src/grants.js";
import {redemptionProof} from "../src/device-pairing.js";

const migrations=[
  "001_inventory.pgsql","002_client_grants.pgsql","003_better_auth.pgsql",
  "004_client_revocation.pgsql","005_token_cutoff.pgsql","006_oauth_issuance_fence.pgsql",
  "007_device_pairing.pgsql","008_device_credentials.pgsql","009_device_handshake.pgsql",
  "010_connector_sessions.pgsql","011_pairing_review_budget.pgsql",
  "012_pairing_device_budget.pgsql"
];
const secret="isolated-owner-pairing-journey-secret-32-plus-bytes";
const owner="local-journey-owner",other="local-journey-other",client="journey-oauth-client";
const config:Config={
  host:"127.0.0.1",port:0,publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example.invalid",jwksUrl:"https://issuer.example.invalid/jwks",
  audience:"http://127.0.0.1/mcp",databaseUrl:"isolated-postgres-only",
  allowedOrigins:[],managementClientId:"manager"
};
const htmlCsrf=(html:string,action:string):string=>{
  const start=html.indexOf('<form action="'+action+'"');
  assert.ok(start>=0,"expected form "+action);
  const stop=html.indexOf("</form>",start);
  assert.ok(stop>start,"expected form close "+action);
  const result=/name="csrf" value="([^"]+)"/.exec(html.slice(start,stop));
  assert.ok(result?.[1],"expected CSRF for "+action);
  return result[1];
};
const pageCookie=(response:Response):string=>
  (response.headers.get("set-cookie")??"").split(";")[0];
const identityCookie=(actor:string):string=>"journey_actor="+actor;
const ownerCookie=identityCookie(owner);
async function seededIdentity(db:Pool):Promise<BrowserIdentity>{
  return {
    handler:async()=>new Response(null,{status:404}),
    $context:Promise.resolve({secret}),
    api:{
      // A synthetic browser session lives ONLY in this isolated test; a genuine
      // production login is neither simulated as a success nor asserted here.
      getSession:async({headers}:{headers:Headers})=>{
        const actor=headers.get("cookie")?.includes(ownerCookie)?owner:
          headers.get("cookie")?.includes(identityCookie(other))?other:null;
        return actor?{user:{id:actor},session:{id:"session-"+actor}}:null;
      },
      getOAuthConsents:async({headers}:{headers:Headers})=>{
        if(!headers.get("cookie")?.includes(ownerCookie))return [];
        const data=await db.query<{id:string;clientId:string;userId:string;scopes:string|string[]}>(
          'SELECT "id","clientId","userId","scopes" FROM "oauthConsent" WHERE "userId"=$1',
          [owner]);
        return data.rows.map(row=>({...row,scopes:typeof row.scopes==="string"?
          JSON.parse(row.scopes) as string[]:row.scopes}));
      }
    }
  } as unknown as BrowserIdentity;
}
test("real HTTP owner journey: DB pairing, browser consent gates, project grant and revoke",
  {skip:!process.env.TEST_DATABASE_URL},async()=>{
  await inIsolatedDatabase(process.env.TEST_DATABASE_URL!,migrations,async db=>{
    const scoped=(db as unknown as {options:{connectionString:string}}).options.connectionString;
    const grants=new PgGrantManagement(scoped,true);
    let server:Server|undefined;
    try{
      await db.query('INSERT INTO "users"("id","name","email","emailVerified") VALUES($1,$2,$3,true)',
        [owner,"Test owner","owner@example.invalid"]);
      await db.query(
        'INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod",'+
        '"grantTypes","scopes") VALUES($1,$1,$2,$3,$4,$5)',
        [client,JSON.stringify(["https://client.invalid/callback"]),"none",
          JSON.stringify(["authorization_code"]),JSON.stringify(["projects:read"])]);
      const devices=new PgDeviceManagement(db);
      server=createHttpServer(config,grants,async()=>{throw Error("not used");},{
        grants,identity:await seededIdentity(db),devices,
        pairings:new PgPairingReview(db,secret),pairingDevice:new PgPairingDeviceAPI(db,secret),
        // Source trust is a loopback fixture only, never a production setting.
        deviceSource:req=>req.socket.remoteAddress==="127.0.0.1"?"fixture-loopback":null
      });
      await new Promise<void>(resolve=>server!.listen(0,"127.0.0.1",resolve));
      const base="http://127.0.0.1:"+(server.address() as AddressInfo).port;
      type BrowserAction="review"|"enable"|"register"|"grant"|"revoke";
      function postForm(action:BrowserAction,fields:Record<string,string>,cookie:string,
        origin=config.publicOrigin):Promise<Response>{
        const init:RequestInit={method:"POST",headers:{
          "Content-Type":"application/x-www-form-urlencoded",Origin:origin,Cookie:cookie
        },body:new URLSearchParams(fields),redirect:"manual"};
        // Fixed endpoint allowlist: no untrusted input can become an HTTP target.
        switch(action){
          case "review":return fetch(base+"/devices/pairing/review",init);
          case "enable":return fetch(base+"/devices/enable",init);
          case "register":return fetch(base+"/devices/projects/create",init);
          case "grant":return fetch(base+"/devices/projects/grant",init);
          case "revoke":return fetch(base+"/devices/revoke",init);
        }
      }
      function devicePost(action:"challenge"|"redeem",data:object):Promise<Response>{
        const init:RequestInit={method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify(data)};
        return action==="challenge"?
          fetch(base+"/api/v1/pairing/device/challenge",init):
          fetch(base+"/api/v1/pairing/device/redeem",init);
      }
      assert.equal((await fetch(base+"/devices/pairing",{redirect:"manual"})).status,303);
      const keys=generateKeyPairSync("ed25519");
      const publicKeyDer=keys.publicKey.export({format:"der",type:"spki"}) as Buffer;
      const issued=await devicePost("challenge",{
        alias:"Owner approved local test",publicKeyDer:publicKeyDer.toString("base64")
      });
      assert.equal(issued.status,201);
      const challenge=await issued.json() as {
        challengeId:string;userCode:string;deviceCode:string;deviceFingerprint:string
      };
      assert.ok(challenge.challengeId&&challenge.userCode&&challenge.deviceCode);
      const approvalPage=await fetch(base+"/devices/pairing",{headers:{Cookie:ownerCookie}});
      assert.equal(approvalPage.status,200);
      const approvalCsrf=htmlCsrf(await approvalPage.text(),"/devices/pairing/review");
      const approvalCookie=pageCookie(approvalPage);
      const form={challenge_id:challenge.challengeId,user_code:challenge.userCode,
        decision:"approve",csrf:approvalCsrf};
      assert.equal((await postForm("review",form,
        approvalCookie+"; "+identityCookie(other))).status,403);
      const approved=await postForm("review",form,
        approvalCookie+"; "+ownerCookie);
      assert.equal(approved.status,303);
      const proof=sign(null,redemptionProof(challenge.challengeId,challenge.deviceCode),
        keys.privateKey).toString("base64url");
      const redeemed=await devicePost("redeem",{
        challengeId:challenge.challengeId,deviceCode:challenge.deviceCode,signature:proof
      });
      assert.equal(redeemed.status,200);
      const enrolled=await redeemed.json() as {
        deviceId:string;deviceFingerprint:string;enabled:boolean
      };
      assert.equal(enrolled.enabled,false);
      assert.equal(enrolled.deviceFingerprint,challenge.deviceFingerprint);
      assert.equal((await devicePost("redeem",{
        challengeId:challenge.challengeId,deviceCode:challenge.deviceCode,signature:proof
      })).status,400,"one-use proof must not be replayed");
      assert.equal(await devices.createProject(owner,enrolled.deviceId,"Before enable"),null);
      assert.deepEqual(await devices.list(other),[]);
      const devicePage=await fetch(base+"/devices",{headers:{Cookie:ownerCookie}});
      const deviceHtml=await devicePage.text();
      assert.match(deviceHtml,/Disabled/);
      const enabledCsrf=htmlCsrf(deviceHtml,"/devices/enable");
      const enabledCookie=pageCookie(devicePage)+"; "+ownerCookie;
      assert.equal((await postForm("enable",{
        device_id:enrolled.deviceId,csrf:enabledCsrf
      },enabledCookie,"https://hostile.example.invalid")).status,403);
      assert.equal((await postForm("enable",{
        device_id:enrolled.deviceId,csrf:enabledCsrf
      },enabledCookie)).status,303);
      const projectPage=await fetch(base+"/devices",{headers:{Cookie:ownerCookie}});
      const projectCsrf=htmlCsrf(await projectPage.text(),"/devices/projects/create");
      assert.equal((await postForm("register",{
        device_id:enrolled.deviceId,csrf:projectCsrf,alias:"Test PCB"
      },pageCookie(projectPage)+"; "+ownerCookie)).status,303);
      const projects=await devices.listProjects(owner);
      assert.equal(projects.length,1);
      const projectId=projects[0].id;
      const withoutConsent=await (await fetch(base+"/devices",{
        headers:{Cookie:ownerCookie}
      })).text();
      assert.doesNotMatch(withoutConsent,/Allow read-only metadata/);
      await db.query(
        'INSERT INTO "oauthConsent"("id","clientId","userId","scopes","createdAt","updatedAt") '+
        'VALUES($1,$2,$3,$4,clock_timestamp(),clock_timestamp())',
        [randomUUID(),client,owner,JSON.stringify(["openid","projects:read"])]);
      const grantPage=await fetch(base+"/devices",{headers:{Cookie:ownerCookie}});
      const grantHtml=await grantPage.text();
      assert.match(grantHtml,/Allow read-only metadata/);
      assert.match(grantHtml,/journey-oauth-client/);
      assert.match(grantHtml,/Registered projects/);
      assert.match(grantHtml,/Test PCB/);
      assert.match(grantHtml,/On device: Owner approved local test/);
      assert.doesNotMatch(grantHtml,/Credential fingerprint|Registered project IDs/);
      assert.doesNotMatch(grantHtml,new RegExp("<code>"+projectId+"</code>"));
      assert.match(grantHtml,new RegExp('name="project_id" value="'+projectId+'"'));
      const grantCsrf=htmlCsrf(grantHtml,"/devices/projects/grant");
      const grantCookie=pageCookie(grantPage)+"; "+ownerCookie;
      assert.equal((await postForm("grant",{
        project_id:projectId,client_id:"unconsented-client",enabled:"true",csrf:grantCsrf
      },grantCookie)).status,404);
      assert.equal((await postForm("grant",{
        project_id:projectId,client_id:client,enabled:"true",csrf:grantCsrf
      },grantCookie)).status,303);
      const stored=await db.query<{enabled:boolean;max_mode:string}>(
        "SELECT enabled,max_mode FROM project_client_grants WHERE project_id=$1 AND client_id=$2",
        [projectId,client]);
      assert.deepEqual(stored.rows,[{enabled:true,max_mode:"readonly"}]);
      assert.equal((await postForm("grant",{
        project_id:projectId,client_id:client,enabled:"false",csrf:grantCsrf
      },grantCookie)).status,303);
      assert.equal((await db.query<{enabled:boolean}>(
        "SELECT enabled FROM project_client_grants WHERE project_id=$1",
        [projectId])).rows[0].enabled,false);
      assert.equal((await postForm("grant",{
        project_id:projectId,client_id:client,enabled:"true",csrf:grantCsrf
      },grantCookie)).status,303);
      const revokePage=await fetch(base+"/devices",{headers:{Cookie:ownerCookie}});
      const revokeToken=htmlCsrf(await revokePage.text(),"/devices/revoke");
      assert.equal((await postForm("revoke",{
        device_id:enrolled.deviceId,csrf:revokeToken
      },pageCookie(revokePage)+"; "+ownerCookie)).status,303);
      assert.equal(await devices.enableDevice(owner,enrolled.deviceId),false);
      assert.equal(await grants.setBrowserGrant(owner,projectId,client,true),false);
      assert.equal((await db.query<{enabled:boolean}>(
        "SELECT enabled FROM project_client_grants WHERE project_id=$1",
        [projectId])).rows[0].enabled,false);
    }finally{
      if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));
      await grants.close();
    }
  });
});
