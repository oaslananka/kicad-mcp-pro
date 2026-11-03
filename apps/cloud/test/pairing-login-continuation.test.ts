import assert from "node:assert/strict";
import {runInNewContext} from "node:vm";
import {test} from "node:test";
import {pairingLoginContinuationClient} from "../src/pairing-login-continuation.js";
import {pairingBrowserResponse} from "../src/pairing-browser.js";
import type {BrowserIdentity} from "../src/browser.js";

const challenge="11111111-1111-4111-8111-111111111111";
const code="ABCDEF-123456";
const key="kicad-pairing-return-v1";
function script(path:"/devices/pairing"|"/account",hash:string,store=new Map<string,string>(),
  time=1_800_000){
  const redirects:string[]=[];
  const history:string[]=[];
  const window={
    location:{pathname:path,hash,
      replace:(value:string)=>{redirects.push(value);}},
    history:{replaceState:(_a:unknown,_b:string,value:string)=>{history.push(value);}},
    sessionStorage:{
      getItem:(name:string)=>store.get(name)??null,
      setItem:(name:string,value:string)=>{store.set(name,value);},
      removeItem:(name:string)=>{store.delete(name);}
    }
  };
  runInNewContext(pairingLoginContinuationClient,{
    window,URLSearchParams,Date:class extends Date {static override now(){return time;}},
    JSON,Number
  });
  return {redirects,history,store};
}

test("signed-out pairing keeps only a short user code in same-tab temporary storage",()=>{
  const store=new Map<string,string>();
  const a=script("/devices/pairing",`#challenge=${challenge}&code=${code}`,store);
  assert.deepEqual(a.history,["/devices/pairing"]);
  assert.deepEqual(a.redirects,[]);
  const saved=JSON.parse(store.get(key)??"{}");
  assert.deepEqual(Object.keys(saved).sort(),["challenge","code","created"]);
  assert.equal(saved.code,code);
  const b=script("/account","",store,1_800_300);
  assert.deepEqual(b.redirects,[`/devices/pairing#challenge=${challenge}&code=${code}`]);
  assert.equal(store.has(key),false);
  assert.deepEqual(script("/account","",store).redirects,[],"one-time continuation");
});

test("invalid, duplicated or expired pairing fragments are never resumed",()=>{
  for(const hash of [
    "#challenge=x&code="+code,
    `#challenge=${challenge}&code=${code}&bad=1`,
    `#challenge=${challenge}&challenge=${challenge}&code=${code}`,
    `#challenge=${challenge}&code=BAD`,
    "#code="+code
  ]){
    const storage=new Map<string,string>();
    const a=script("/devices/pairing",hash,storage);
    assert.deepEqual(a.history,["/devices/pairing"]);
    assert.equal(storage.has(key),false);
  }
  const storage=new Map([[key,JSON.stringify({challenge,code,created:0})]]);
  assert.deepEqual(script("/account","",storage).redirects,[]);
  assert.equal(storage.has(key),false);
  assert.deepEqual(script("/devices/pairing","").redirects,[]);
});

test("signed-out pairing offers existing social login, no implicit approval",async()=>{
  const origin="https://kicad-mcp-pro.example.invalid";
  const identity={
    handler:async()=>new Response(null,{status:404}),
    api:{getSession:async()=>null},
    $context:Promise.resolve({secret:"unit-test"})
  } as unknown as BrowserIdentity;
  const response=await pairingBrowserResponse(
    new Request(origin+"/devices/pairing"),identity,origin,{
      review:async()=>{throw Error("owner review must not run");}
    });
  assert.equal(response?.status,200);
  const html=await response!.text();
  assert.match(html,/Continue with Google/);
  assert.match(html,/Continue with GitHub/);
  assert.match(html,/pairing-login-continuation\.js/);
  assert.doesNotMatch(html,/challenge=11111111/);
  assert.match(response?.headers.get("content-security-policy")??"",/script-src 'self'/);
});
