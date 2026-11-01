import assert from "node:assert/strict";
import {createHash,createHmac,randomBytes} from "node:crypto";
import {readFile} from "node:fs/promises";
import {test} from "node:test";
import type {AddressInfo} from "node:net";
import {request as nodeRequest,type Server} from "node:http";
import pg from "pg";
import {decodeJwt,exportJWK,generateKeyPair,SignJWT} from "jose";
import {createIdentity} from "../src/identity.js";
import {createHttpServer} from "../src/http.js";
import {PgGrantManagement} from "../src/grants.js";
import type {Config} from "../src/config.js";

const databaseUrl=process.env.TEST_DATABASE_URL;
test("real MCP OAuth server: authorize redirect, session consent and PKCE code exchange",
  {skip:!databaseUrl},async()=>{
  const root=new pg.Pool({connectionString:databaseUrl});
  const schema="pkce_"+randomBytes(6).toString("hex");
  const publicOrigin="http://127.0.0.1:8787";
  let pool:pg.Pool|undefined;
  let grants:PgGrantManagement|undefined;
  let server:Server|undefined;
  try{
    await root.query('CREATE SCHEMA "'+schema+'"');
    const uri=new URL(databaseUrl!);
    uri.searchParams.set("options","-c search_path="+schema);
    const scoped=uri.toString();
    pool=new pg.Pool({connectionString:scoped});
    for(const file of ["001_inventory.pgsql","002_client_grants.pgsql","003_better_auth.pgsql",
      "004_client_revocation.pgsql","005_token_cutoff.pgsql","006_oauth_issuance_fence.pgsql"]){
      await pool.query(await readFile(new URL("../db/"+file,import.meta.url),"utf8"));
    }
    grants=new PgGrantManagement(scoped,true);
    const secret=randomBytes(40).toString("hex");
    const identity=createIdentity({publicOrigin,audience:publicOrigin+"/mcp",databaseUrl:scoped},{
      secret,googleId:"synthetic-google",googleSecret:"synthetic-google-secret",
      githubId:"synthetic-github",githubSecret:"synthetic-github-secret"
    },pool);
    const conf:Config={host:"127.0.0.1",port:0,publicOrigin,issuer:publicOrigin+"/api/auth",
      jwksUrl:publicOrigin+"/api/auth/jwks",audience:publicOrigin+"/mcp",
      databaseUrl:scoped,allowedOrigins:[],managementClientId:"portal"};
    server=createHttpServer(conf, grants, async()=>{throw new Error("unexpected resource access")}, {grants:grants, identity:identity});
    await new Promise<void>(resolve=>server!.listen(0,"127.0.0.1",resolve));
    const address="http://127.0.0.1:"+(server.address() as AddressInfo).port;
    const now=new Date(),expire=new Date(now.getTime()+60*60*1000);
    await pool.query('INSERT INTO "users"("id","name","email","emailVerified","createdAt","updatedAt") VALUES($1,$2,$3,true,$4,$4)',
      ["owner-pkce","Tester","tester@example.invalid",now]);
    await pool.query('INSERT INTO "session"("id","expiresAt","token","createdAt","updatedAt","userId") VALUES($1,$2,$3,$4,$4,$5)',
      ["session-pkce",expire,"session-fixture-token",now,"owner-pkce"]);
    const cookieValue="session-fixture-token."+createHmac("sha256",secret).update("session-fixture-token").digest("base64");
    const cookie="better-auth.session_token="+encodeURIComponent(cookieValue);
    await pool.query('INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod","grantTypes","responseTypes","scopes","requirePKCE") VALUES($1,$1,$2,$3,$4,$5,$6,true)',
      ["fixture-mcp-client",JSON.stringify(["http://127.0.0.1:8888/callback"]),"none",
        JSON.stringify(["authorization_code","refresh_token"]),JSON.stringify(["code"]),
        JSON.stringify(["openid","profile","offline_access","projects:read"])]);
    await pool.query('INSERT INTO "oauthClientResource"("id","clientId","resourceId") VALUES($1,$2,$3)',
      ["fixture-link","fixture-mcp-client",publicOrigin+"/mcp"]);
    const verifier=randomBytes(48).toString("base64url");
    const challenge=createHash("sha256").update(verifier).digest("base64url");
    const state=randomBytes(18).toString("base64url");
    const params=new URLSearchParams({client_id:"fixture-mcp-client",response_type:"code",
      redirect_uri:"http://127.0.0.1:8888/callback",
      scope:"openid profile offline_access projects:read",state,
      code_challenge:challenge,code_challenge_method:"S256",
      resource:publicOrigin+"/mcp"
    });
    const browserNavigate=(cookieHeader?:string)=>new Promise<{status:number;location:string;body:string}>((resolve,reject)=>{
      const req=nodeRequest(address+"/api/auth/oauth2/authorize?"+params,{
        method:"GET",headers:{Accept:"text/html",...(cookieHeader?{Cookie:cookieHeader}:{})}
      },res=>{
        const chunks:Buffer[]=[];
        res.on("data",(piece:Buffer)=>chunks.push(piece));
        res.on("end",()=>resolve({
          status:res.statusCode??0,location:String(res.headers.location??""),
          body:Buffer.concat(chunks).toString("utf8")
        }));
      });
      req.on("error",reject);
      req.end();
    });
    const anonymous=await browserNavigate();
    assert.equal(anonymous.status,302,"anonymous request should redirect to login");
    assert.match(anonymous.location,/sign-in/);
    const signIn=new URL(anonymous.location,publicOrigin);
    const signInPage=await fetch(address+signIn.pathname+signIn.search);
    assert.equal(signInPage.status,200);
    const loginHtml=await signInPage.text();
    assert.match(loginHtml,/Continue with Google/);
    assert.match(loginHtml,/Continue with GitHub/);
    const signedQuery=signIn.search.slice(1);
    for(const [provider,expectedHost] of [["google","accounts.google.com"],["github","github.com"]] as const){
      const started=await fetch(address+"/auth/start/"+provider,{
        method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded",
          "Origin":publicOrigin},
        body:new URLSearchParams({oauth_query:signedQuery}),redirect:"manual"
      });
      assert.equal(started.status,303,"signed query must survive social login initiation");
      assert.equal(new URL(started.headers.get("location")!).hostname,expectedHost);
      assert.match(started.headers.get("set-cookie")??"",/HttpOnly/);
    }
    const authenticated=await browserNavigate(cookie);
    assert.ok([302,303].includes(authenticated.status),
      "logged-in user should be redirected to verified consent screen");
    const destination=authenticated.location;
    assert.match(destination,/consent/);
    const consentUrl=new URL(destination,publicOrigin);
    const consent=await fetch(address+consentUrl.pathname+consentUrl.search,{
      headers:{cookie},redirect:"manual"
    });
    assert.equal(consent.status,200);
    const form=await consent.text();
    // Real browsers decode HTML attributes on form submission. Instead
    // of writing a custom decoder or dynamic RegExp in the test, send the
    // same signed query that the server put in the consent redirect.
    assert.match(form,/name="oauth_query" value="/);
    const csrf=/name="csrf" value="([^"]+)"/.exec(form)?.[1]??"";
    assert.ok(csrf);
    const csrfCookie=consent.headers.get("set-cookie")?.split(";")[0]??"";
    const approved=await fetch(address+"/consent",{
      method:"POST",headers:{"Origin":publicOrigin,
        "Content-Type":"application/x-www-form-urlencoded","Cookie":cookie+"; "+csrfCookie},
      body:new URLSearchParams({oauth_query:consentUrl.search.slice(1),csrf,decision:"approve"}),
      redirect:"manual"
    });
    assert.equal(approved.status,303);
    const redirected=new URL(approved.headers.get("location")!);
    assert.equal(redirected.origin,"http://127.0.0.1:8888");
    assert.equal(redirected.searchParams.get("state"),state);
    const code=redirected.searchParams.get("code");
    assert.ok(code);
    const exchange=async (codeVerifier:string)=>fetch(address+"/api/auth/oauth2/token",{
      method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},
      body:new URLSearchParams({grant_type:"authorization_code",client_id:"fixture-mcp-client",
        code:code!,redirect_uri:"http://127.0.0.1:8888/callback",
        code_verifier:codeVerifier}),redirect:"manual"
    });
    const correct=await exchange(verifier);
    assert.equal(correct.status,200);
    const tokens=await correct.json() as Record<string,unknown>;
    assert.equal(typeof tokens.access_token,"string");
    assert.equal(typeof tokens.refresh_token,"string");
    assert.ok([decodeJwt(tokens.access_token as string).aud].flat().includes(publicOrigin+"/mcp"),
      "access tokens must be bound to the requested MCP resource");
    const wrong=await exchange("wrong-verifier-not-valid-but-long-enough-string-00000");
    assert.notEqual(wrong.status,200,"invalid verifier must not issue tokens");
    const reuse=await exchange(verifier);
    assert.notEqual(reuse.status,200,"authorization code is single-use");
    // A fresh authorization has a separate code. Exercise PKCE rejection
    // before that authorization code has ever been redeemed.
    const secondState=randomBytes(18).toString("base64url");
    params.set("state",secondState);
    const second=await browserNavigate(cookie);
    assert.ok([302,303].includes(second.status));
    const secondUrl=new URL(second.location,publicOrigin);
    assert.equal(secondUrl.searchParams.get("state"),secondState);
    const secondCode=secondUrl.searchParams.get("code");
    assert.ok(secondCode,"previous consent should permit a new authorization");
    const invalid=await fetch(address+"/api/auth/oauth2/token",{
      method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},
      body:new URLSearchParams({grant_type:"authorization_code",client_id:"fixture-mcp-client",
        code:secondCode!,redirect_uri:"http://127.0.0.1:8888/callback",
        code_verifier:"incorrect-but-valid-length-verifier-for-s256-000000"}),
      redirect:"manual"
    });
    assert.equal(invalid.status,400,"a new code must require its matching PKCE verifier");
    assert.equal((await invalid.json() as {error:string}).error,"invalid_grant");

    // ChatGPT CIMD publishes token_endpoint_auth_method: private_key_jwt.
    // Prove the real provider can exchange a PKCE code for that client type
    // without hosting any test key or creating access in production.
    const confidentialId="chatgpt-like-private-jwt";
    const {publicKey,privateKey}=await generateKeyPair("RS256",{extractable:true});
    const publishedKey={...await exportJWK(publicKey),kid:"synthetic-jwt-key",alg:"RS256",use:"sig"};
    await pool.query('INSERT INTO "oauthClient"("id","clientId","redirectUris","tokenEndpointAuthMethod",'+
      '"jwks","grantTypes","responseTypes","scopes","requirePKCE") VALUES($1,$1,$2,$3,$4,$5,$6,$7,true)',
      [confidentialId,JSON.stringify(["http://127.0.0.1:8888/callback"]),"private_key_jwt",
        JSON.stringify({keys:[publishedKey]}),JSON.stringify(["authorization_code","refresh_token"]),
        JSON.stringify(["code"]),JSON.stringify(["openid","profile","offline_access","projects:read"])]);
    await pool.query('INSERT INTO "oauthClientResource"("id","clientId","resourceId") VALUES($1,$2,$3)',
      ["confidential-link",confidentialId,publicOrigin+"/mcp"]);
    params.set("client_id",confidentialId);
    params.set("state",randomBytes(16).toString("base64url"));
    const pending=await browserNavigate(cookie);
    assert.ok([302,303].includes(pending.status));
    assert.match(pending.location,/consent/);
    const signedConsent=new URL(pending.location,publicOrigin);
    const consentPage=await fetch(address+signedConsent.pathname+signedConsent.search,{
      headers:{cookie},redirect:"manual"
    });
    assert.equal(consentPage.status,200);
    assert.equal(consentPage.headers.get("referrer-policy"),"same-origin");
    assert.match(consentPage.headers.get("content-security-policy")??"",
      /form-action 'self' http:\/\/127\.0\.0\.1:8888;/);
    const consentHtml=await consentPage.text();
    const proof=/name="csrf" value="([^"]+)"/.exec(consentHtml)?.[1]??"";
    assert.ok(proof);
    const stateCookie=consentPage.headers.get("set-cookie")?.split(";")[0]??"";
    const explicit=await fetch(address+"/consent",{
      method:"POST",headers:{"Origin":publicOrigin,"Content-Type":"application/x-www-form-urlencoded",
        "Cookie":cookie+"; "+stateCookie},
      body:new URLSearchParams({oauth_query:signedConsent.search.slice(1),csrf:proof,decision:"approve"}),
      redirect:"manual"
    });
    assert.equal(explicit.status,303);
    const callback=new URL(explicit.headers.get("location")!);
    const confidentialCode=callback.searchParams.get("code");
    assert.ok(confidentialCode);
    const exchangeConfidential=async(assertion:string)=>fetch(address+"/api/auth/oauth2/token",{
      method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},
      body:new URLSearchParams({grant_type:"authorization_code",client_id:confidentialId,
        code:confidentialCode!,redirect_uri:"http://127.0.0.1:8888/callback",
        code_verifier:verifier,
        client_assertion_type:"urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        client_assertion:assertion})
    });
    const unsigned=await exchangeConfidential("not-a-valid-assertion");
    assert.notEqual(unsigned.status,200,"Unverified client assertion must fail");
    const assertion=await new SignJWT({})
      .setProtectedHeader({alg:"RS256",kid:"synthetic-jwt-key",typ:"JWT"})
      .setIssuer(confidentialId).setSubject(confidentialId)
      .setAudience(publicOrigin+"/api/auth/oauth2/token")
      .setIssuedAt().setExpirationTime("60s")
      .setJti(randomBytes(16).toString("base64url"))
      .sign(privateKey);
    const verified=await exchangeConfidential(assertion);
    assert.equal(verified.status,200,await verified.clone().text());
    const issued=await verified.json() as {access_token:string;refresh_token?:string};
    assert.equal(typeof issued.access_token,"string");
    assert.equal(typeof issued.refresh_token,"string");
    assert.ok([decodeJwt(issued.access_token).aud].flat().includes(publicOrigin+"/mcp"));
  }finally{
    if(server) await new Promise<void>(resolve=>server!.close(()=>resolve()));
    await grants?.close();
    await pool?.end();
    await root.query('DROP SCHEMA IF EXISTS "'+schema+'" CASCADE');
    await root.end();
  }
});
