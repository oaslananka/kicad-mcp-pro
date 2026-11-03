import assert from "node:assert/strict";
import {test} from "node:test";
import {captureOAuthProviderError,oauthProviderResponse} from "../src/oauth-error.js";

const origin="http://127.0.0.1:8787";
function request(type="refresh_token"):Request {
  return new Request(origin+"/api/auth/oauth2/token",{
    method:"POST",
    headers:{"Content-Type":"application/x-www-form-urlencoded"},
    body:new URLSearchParams({grant_type:type,refresh_token:"test-token",client_id:"client-a"})
  });
}
const rawError={code:"23514",message:"oauth_client_revoked"};
test("only exact database fence is mapped to OAuth invalid_grant",async()=>{
  const mapped=await oauthProviderResponse(request(),async()=>{
    captureOAuthProviderError(rawError);
    return new Response(null,{status:500});
  });
  assert.equal(mapped.status,400);
  assert.deepEqual(await mapped.json(),{error:"invalid_grant",error_description:"invalid refresh token"});
  assert.equal(mapped.headers.get("Cache-Control"),"no-store");
  const otherSql=await oauthProviderResponse(request(),async()=>{
    captureOAuthProviderError({code:"23514",message:"other_constraint"});
    return new Response(null,{status:500});
  });
  assert.equal(otherSql.status,500);
  const unrelated=await oauthProviderResponse(request(),async()=>{
    captureOAuthProviderError({code:"08006",message:"connection dropped"});
    return new Response(null,{status:500});
  });
  assert.equal(unrelated.status,500);
});
test("normal OAuth responses, authorization_code and unrelated paths are unchanged",async()=>{
  const tokenResponse=new Response(JSON.stringify({error:"invalid_grant"}),{status:400});
  assert.strictEqual(await oauthProviderResponse(request(),async()=>tokenResponse),tokenResponse);
  const authCode=await oauthProviderResponse(request("authorization_code"),async()=>{
    captureOAuthProviderError(rawError);
    return new Response(null,{status:500});
  });
  assert.equal(authCode.status,500);
  const signIn=await oauthProviderResponse(new Request(origin+"/api/auth/sign-in/social"),async()=>{
    captureOAuthProviderError(rawError);
    return new Response(null,{status:500});
  });
  assert.equal(signIn.status,500);
});
test("overlapping OAuth requests never share an SQL fence decision",async()=>{
  let releaseFence:()=>void=()=>{};
  const blocked=new Promise<void>(resolve=>{releaseFence=resolve;});
  let entered:()=>void=()=>{};
  const ready=new Promise<void>(resolve=>{entered=resolve;});
  const mapped=oauthProviderResponse(request(),async()=>{
    captureOAuthProviderError(rawError);
    entered();
    await blocked;
    return new Response(null,{status:500});
  });
  await ready;
  const other=await oauthProviderResponse(request(),async()=>{
    captureOAuthProviderError({code:"08006",message:"DB down"});
    return new Response(null,{status:500});
  });
  releaseFence();
  assert.equal(other.status,500);
  assert.equal((await mapped).status,400);
});
