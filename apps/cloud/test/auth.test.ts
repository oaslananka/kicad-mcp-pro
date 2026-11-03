import assert from "node:assert/strict";
import { test } from "node:test";
import { createLocalJWKSet, exportJWK, generateKeyPair, SignJWT } from "jose";
import { createVerifier } from "../src/auth.js";
import { loadConfig } from "../src/config.js";

test("access tokens require signed issuer, audience, subject and scope", async () => {
  const { publicKey, privateKey } = await generateKeyPair("RS256");
  const jwk = await exportJWK(publicKey);
  const jwks = createLocalJWKSet({ keys:[{...jwk, kid:"key-1", alg:"RS256", use:"sig"}] });
  const config = { issuer:"https://auth.example", jwksUrl:"https://auth.example/jwks", audience:"https://cloud.example/mcp" };
  const verifier = createVerifier(config,jwks);
  const mint = (claims: Record<string,unknown>) => new SignJWT(claims)
    .setProtectedHeader({alg:"RS256",kid:"key-1"})
    .setIssuedAt().setExpirationTime("2m").sign(privateKey);
  const valid = await mint({iss:config.issuer,aud:config.audience,sub:"owner-1",scope:"projects:read",client_id:"test-client"});
  assert.equal((await verifier(valid)).sub,"owner-1");
  assert.equal(typeof (await verifier(valid)).issuedAt,"number");
  await assert.rejects(verifier(await mint({iss:"https://evil.example",aud:config.audience,sub:"owner-1",scope:"projects:read",client_id:"test-client"})));
  await assert.rejects(verifier(await mint({iss:config.issuer,aud:"https://wrong.example/mcp",sub:"owner-1",scope:"projects:read",client_id:"test-client"})));
  await assert.rejects(verifier(await mint({iss:config.issuer,aud:config.audience,sub:"owner-1",scope:"projects:write",client_id:"test-client"})));
  await assert.rejects(verifier(await mint({iss:config.issuer,aud:config.audience,scope:"projects:read",client_id:"test-client"})));
  const noExp = await new SignJWT({iss:config.issuer,aud:config.audience,sub:"owner-1",scope:"projects:read",client_id:"test-client"}).setProtectedHeader({alg:"RS256",kid:"key-1"}).sign(privateKey);
  await assert.rejects(verifier(noExp));
  const noIssuedAt=await new SignJWT({iss:config.issuer,aud:config.audience,sub:"owner-1",scope:"projects:read",client_id:"test-client"})
    .setProtectedHeader({alg:"RS256",kid:"key-1"}).setExpirationTime("2m").sign(privateKey);
  await assert.rejects(verifier(noIssuedAt));
  await assert.rejects(verifier(await mint({
    iss:config.issuer,aud:config.audience,sub:"owner-1",
    scope:"projects:read",client_id:"test-client", cnf: {jkt:"proof-bound"}
  })));
  await assert.rejects(verifier(await mint({iss:config.issuer,aud:config.audience,sub:"owner-1",scope:"projects:read"})));
});
test("startup rejects missing auth and insecure public origin",()=>{
  const base = {
    PUBLIC_ORIGIN:"https://cloud.example",
    OAUTH_ISSUER:"https://auth.example",
    OAUTH_JWKS_URL:"https://auth.example/jwks",
    OAUTH_AUDIENCE:"https://cloud.example/mcp",
    DATABASE_URL:"postgres://example"
  };
  assert.equal(loadConfig(base).publicOrigin, "https://cloud.example");
  assert.throws(()=>loadConfig({...base,OAUTH_AUDIENCE:"https://cloud.example/mcp-extra"}));
  assert.throws(()=>loadConfig({...base,PUBLIC_ORIGIN:"http://cloud.example",OAUTH_AUDIENCE:"http://cloud.example/mcp"}));
  assert.throws(()=>loadConfig({...base,OAUTH_JWKS_URL:"http://auth.example/jwks"}));
  assert.throws(()=>loadConfig({...base, DATABASE_URL:""}));
});
