import assert from "node:assert/strict";
const origin=process.env.PUBLIC_ORIGIN??"https://kicad-mcp-pro.oaslananka.dev";
const parsedOrigin=new URL(origin);
assert.equal(parsedOrigin.origin,origin);
assert.equal(parsedOrigin.protocol,"https:");

// The deployment target comes from validated Doppler PUBLIC_ORIGIN (legacy default for manual runs).
// This probe sends only an anonymous read/initialize request.
const options={redirect:"manual",signal:AbortSignal.timeout(15000)};
const landingResponse=await fetch(`${origin}/`,options);
assert.equal(landingResponse.status,200,"Premium overview must be public");
assert.match(landingResponse.headers.get("content-type")??"",/text\/html/);
assert.match(landingResponse.headers.get("content-security-policy")??"",/style-src 'self'/);
const page=await landingResponse.text();
assert.match(page,/KiCad MCP Cloud/);
assert.match(page,/href="\/sign-in"/,
  "Public overview must link to the enabled sign-in route");
assert.doesNotMatch(page,/<script[\s>]/i);
assert.doesNotMatch(page,/Account access pending/,
  "Public overview must not claim sign-in is disabled");

const stylesheet=await fetch(`${origin}/assets/ui.css`,options);
assert.equal(stylesheet.status,200);
assert.match(stylesheet.headers.get("content-type")??"",/text\/css/);
assert.match(await stylesheet.text(),/\.landing-panel/);

const health=await fetch(`${origin}/health`,options);
assert.equal(health.status,200);
const status=await health.json();
assert.equal(status.status,"ok");
if (process.env.EXPECTED_REVISION) {
  assert.match(process.env.EXPECTED_REVISION,/^[0-9a-f]{40}$/);
  assert.equal(status.revision,process.env.EXPECTED_REVISION,
    "Live release commit must match exact successfully tested main SHA");
}
assert.equal(status.remoteConnector,"not_implemented",
  "Do not claim the local KiCad connector exists");

const metadata=await fetch(`${origin}/.well-known/oauth-protected-resource`,options);
assert.equal(metadata.status,200);
const resource=await metadata.json();
assert.equal(resource.resource,`${origin}/mcp`);
assert.deepEqual(resource.authorization_servers,
  [`${origin}/api/auth`],
  "OAuth authorization server must match this production origin exactly");

const unauthenticated=await fetch(`${origin}/mcp`,{
  method:"POST",redirect:"manual",signal:AbortSignal.timeout(15000),
  headers:{"Content-Type":"application/json"},
  body:JSON.stringify({jsonrpc:"2.0",id:1,method:"initialize",
    params:{protocolVersion:"2025-11-25",capabilities:{},
      clientInfo:{name:"production-smoke",version:"1.0"}}})
});
assert.equal(unauthenticated.status,401,"MCP must reject untrusted clients");
const signIn=await fetch(`${origin}/sign-in`,options);
assert.equal(signIn.status,200,"GitHub sign-in page must be enabled");
assert.equal(signIn.headers.get("referrer-policy"),"same-origin",
  "Native HTML form POST must retain same-origin Origin in Chrome");
assert.match(signIn.headers.get("content-security-policy")??"",/form-action 'self' https:\/\/github\.com/,
  "Browser form-action CSP must permit the approved GitHub OAuth redirect");
const signInBody=await signIn.text();
assert.match(signInBody,/Continue with GitHub/,
  "First login must offer configured GitHub OAuth");
if(process.env.EXPECTED_GOOGLE_OAUTH==="true")
  assert.match(signInBody,/Continue with Google/,"Configured Google OAuth must be shown");
else
  assert.doesNotMatch(signInBody,/Continue with Google/,
    "Unconfigured Google OAuth must not be shown");
const directAuthStart=await fetch(`${origin}/auth/start/github`,options);
assert.equal(directAuthStart.status,303,"Direct OAuth start GET must return to the sign-in form");
assert.equal(directAuthStart.headers.get("location"),"/sign-in");
const opaqueOriginNavigation=await fetch(`${origin}/auth/start/github`,{
  ...options,headers:{Origin:"null"}
});
assert.equal(opaqueOriginNavigation.status,303,"Public GET must redirect even for opaque Origin");
assert.equal(opaqueOriginNavigation.headers.get("location"),"/sign-in");
const opaqueSignIn=await fetch(`${origin}/sign-in`,{
  ...options,headers:{Origin:"null"}
});
assert.equal(opaqueSignIn.status,200,"Public sign-in GET must support opaque-Origin navigation");
const opaquePost=await fetch(`${origin}/auth/start/github`,{
  method:"POST",redirect:"manual",signal:AbortSignal.timeout(15000),
  headers:{Origin:"null","Content-Type":"application/x-www-form-urlencoded"},
  body:"oauth_query="
});
assert.equal(opaquePost.status,403,"OAuth POST must still require strict Origin");
const account=await fetch(`${origin}/account`,options);
assert.equal(account.status,303,"Anonymous account access must redirect to sign-in");
assert.equal(account.headers.get("location"),"/sign-in");
const authorizationMetadata=await fetch(
  `${origin}/.well-known/oauth-authorization-server/api/auth`,
  options);
assert.equal(authorizationMetadata.status,200,"OAuth discovery must be reachable");
console.log("Production smoke PASS: HTTPS, UI/CSS, OAuth discovery, anonymous MCP 401, GitHub-only login and protected account");
