import {scryptSync} from "node:crypto";
// Read public deployment selectors from Doppler-injected environment.
// Never print the full environment, access tokens or credential-bearing URLs.
const origin=process.env.PUBLIC_ORIGIN??"";
let parsed;
try { parsed=new URL(origin); } catch { throw new Error("PUBLIC_ORIGIN_REQUIRED"); }
if(parsed.protocol!=="https:"||parsed.origin!==origin||parsed.username||parsed.password||
   parsed.search||parsed.hash||parsed.pathname!=="/")
  throw new Error("INVALID_PUBLIC_ORIGIN");
const network=process.env.KICAD_TUNNEL_NETWORK??"ops_internal";
if(!/^[A-Za-z][A-Za-z0-9_.-]{0,62}$/.test(network))
  throw new Error("INVALID_TUNNEL_NETWORK");
const githubId=process.env.GITHUB_CLIENT_ID??"";
const githubSecret=process.env.GITHUB_CLIENT_SECRET??"";
const googleId=process.env.GOOGLE_CLIENT_ID??"";
const googleSecret=process.env.GOOGLE_CLIENT_SECRET??"";
const github=Boolean(githubId&&githubSecret);
const google=Boolean(googleId&&googleSecret);
function checkProviderPairs(){
  if(Boolean(githubId)!==Boolean(githubSecret)||Boolean(googleId)!==Boolean(googleSecret))
    throw new Error("INCOMPLETE_OAUTH_PROVIDER_CREDENTIALS");
}
const kind=process.argv[2];
if(kind==="origin")process.stdout.write(origin+"\n");
else if(kind==="network")process.stdout.write(network+"\n");
else if(kind==="google"){
  checkProviderPairs();
  process.stdout.write(String(google)+"\n");
}else if(kind==="validate"||kind==="fingerprint"){
  checkProviderPairs();
  // The fresh-VPS contract serves a first-party OAuth login, not an
  // externally provisioned identity system. Legacy production can continue
  // using AUTH_MODE=external; only this fresh-install validator is strict.
  const auth=process.env.AUTH_MODE??"";
  const allowedBootstrapAuthModes=new Set(["builtin"]);
  if(!allowedBootstrapAuthModes.has(auth))
    throw new Error("NEW_VPS_REQUIRES_BUILTIN_AUTH");
  const issuer=process.env.OAUTH_ISSUER??"",jwks=process.env.OAUTH_JWKS_URL??"";
  const audience=process.env.OAUTH_AUDIENCE??"";
  if(audience!==origin+"/mcp")throw new Error("OAUTH_AUDIENCE_MISMATCH");
  if(issuer!==origin+"/api/auth"||jwks!==origin+"/api/auth/jwks")
    throw new Error("BUILTIN_OAUTH_ORIGIN_MISMATCH");
  for(const value of [issuer,jwks]){
    let url;try{url=new URL(value);}catch{throw new Error("INVALID_OAUTH_URL");}
    if(url.protocol!=="https:"||url.username||url.password)throw new Error("INVALID_OAUTH_URL");
  }
  if(!(process.env.KICAD_DB_PASSWORD??""))throw new Error("KICAD_DB_PASSWORD_REQUIRED");
  // Better Auth itself refuses secrets shorter than 32 characters. Catch
  // mismatched Doppler configs before any database or network is allocated.
  if((process.env.BETTER_AUTH_SECRET??"").length<32)
    throw new Error("BETTER_AUTH_SECRET_TOO_SHORT");
  if(!github)throw new Error("BUILTIN_GITHUB_OAUTH_CREDENTIALS_REQUIRED");
  // Mirror the application's HTTPS-only origin allowlist validation. This
  // prevents a malformed optional Doppler value from crashing the new app
  // only after the database and ingress have already been provisioned.
  for(const entry of (process.env.ALLOWED_ORIGINS??"").split(",")){
    const value=entry.trim();
    if(!value)continue;
    let allowed;
    try{allowed=new URL(value);}catch{throw new Error("INVALID_ALLOWED_ORIGINS");}
    if(allowed.protocol!=="https:"||allowed.origin!==value||
       allowed.username||allowed.password)
      throw new Error("INVALID_ALLOWED_ORIGINS");
  }
  if(process.env.PAIRING_DEVICE_API_ENABLED==="true"||process.env.CONNECTOR_WS_ENABLED==="true")
    throw new Error("DEVICE_ROLLOUT_REQUIRES_SEPARATE_SECURITY_ACCEPTANCE");
  if(kind==="fingerprint"){
    // No raw credentials are emitted or persisted. Derive the entire config
    // fingerprint directly with memory-hard scrypt, not with a fast hash of
    // a password-bearing record. The production-random Better Auth root is
    // the private salt; all inputs stay inside this short-lived process.
    // Keep every eligible environment field explicitly enumerated.
    const values=[
      ["PUBLIC_ORIGIN",origin],
      ["OAUTH_ISSUER",issuer],["OAUTH_JWKS_URL",jwks],
      ["OAUTH_AUDIENCE",audience],
      ["KICAD_DB_PASSWORD",process.env.KICAD_DB_PASSWORD??null],
      ["AUTH_MODE",auth],
      ["BETTER_AUTH_SECRET",process.env.BETTER_AUTH_SECRET??null],
      ["GITHUB_CLIENT_ID",githubId],["GITHUB_CLIENT_SECRET",githubSecret],
      ["GOOGLE_CLIENT_ID",googleId],["GOOGLE_CLIENT_SECRET",googleSecret],
      ["MANAGEMENT_CLIENT_ID",process.env.MANAGEMENT_CLIENT_ID??null],
      ["ALLOWED_ORIGINS",process.env.ALLOWED_ORIGINS??null],
      ["KICAD_TUNNEL_NETWORK",network],
      ["CLOUDFLARE_TUNNEL_TOKEN",process.env.CLOUDFLARE_TUNNEL_TOKEN??null],
      ["PAIRING_DEVICE_API_ENABLED",process.env.PAIRING_DEVICE_API_ENABLED??null],
      ["CONNECTOR_WS_ENABLED",process.env.CONNECTOR_WS_ENABLED??null]
    ];
    const digest=scryptSync(
      JSON.stringify(values),process.env.BETTER_AUTH_SECRET,32
    ).toString("hex");
    process.stdout.write(digest+"\n");
  }else{
    process.stdout.write("Portable runtime configuration valid (secrets not printed)\n");
  }
}else throw new Error("Usage: portable-config.mjs origin|network|google|validate|fingerprint");
