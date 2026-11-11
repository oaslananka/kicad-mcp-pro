import assert from "node:assert/strict";
import {test} from "node:test";
import type {Config} from "../src/config.js";
import {createLocalDevIdentity} from "../src/local-dev-identity.js";
import {browserResponse} from "../src/browser.js";
import {localDevLoopbackSource} from "../src/trusted-ingress.js";

const origin="http://127.0.0.1:8787";
const config:Config={host:"127.0.0.1",port:8787,publicOrigin:origin,
  issuer:"https://local-dev.invalid/issuer",jwksUrl:"https://local-dev.invalid/jwks",
  audience:origin+"/mcp",
  databaseUrl:"postgresql://kicad_dev:fake@127.0.0.1:15432/kicad_cloud_dev",
  allowedOrigins:[],managementClientId:""};
const env={AUTH_MODE:"local_dev",LOCAL_DEV_SANDBOX:"acknowledged",NODE_ENV:"development"};
test("local dev account requires explicit opt-in and loopback-only origin, listener and database",()=>{
  assert.throws(()=>createLocalDevIdentity(config,{...env,LOCAL_DEV_SANDBOX:undefined}));
  assert.throws(()=>createLocalDevIdentity(config,{...env,AUTH_MODE:"builtin"}));
  assert.throws(()=>createLocalDevIdentity(config,{...env,NODE_ENV:"production"}));
  assert.throws(()=>createLocalDevIdentity({...config,host:"0.0.0.0"},env));
  assert.throws(()=>createLocalDevIdentity({...config,publicOrigin:"https://cloud.example"},env));
  assert.throws(()=>createLocalDevIdentity({...config,databaseUrl:"postgresql://x:fake@prod.example/db_dev"},env));
  assert.throws(()=>createLocalDevIdentity({...config,databaseUrl:"postgresql://x:fake@127.0.0.1/prod"},env));
});
test("sandbox permits local browser workspace access without representing real OAuth",async()=>{
  const id=createLocalDevIdentity(config,env);
  const session=await id.api?.getSession({headers:new Headers()});
  assert.equal(session?.user?.id,"local-dev-owner");
  assert.equal(id.localDevSandbox,true);
  const account=await browserResponse(new Request(origin+"/account"),id,origin);
  assert.equal(account?.status,200);
  assert.match(await account!.text(),/Local development workspace/i);
  const signIn=await browserResponse(new Request(origin+"/sign-in"),id,origin);
  assert.equal(signIn?.status,303);
  assert.equal(signIn?.headers.get("location"),"/account");
  const oauth=await id.handler(new Request(origin+"/api/auth/authorize"));
  assert.equal(oauth.status,404);
});

test("local dev device requests require direct 127.0.0.1 TCP and no forwarded identity",()=>{
  const source=(local:string,remote:string,headers:string[]=[])=>
    localDevLoopbackSource({socket:{localAddress:local,remoteAddress:remote},
      rawHeaders:headers} as never);
  assert.equal(source("127.0.0.1","127.0.0.1"),"127.0.0.1");
  assert.equal(source("127.0.0.1","127.0.0.1",["X-Forwarded-For","127.0.0.1"]),null);
  assert.equal(source("127.0.0.1","127.0.0.2"),null);
  assert.equal(source("0.0.0.0","127.0.0.1"),null);
  assert.equal(source("::1","::1"),null);
});
