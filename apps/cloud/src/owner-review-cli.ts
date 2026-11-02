import {readFile} from "node:fs/promises";
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {Pool} from "pg";
import {createIdentity} from "./identity.js";
import {createIndependentOwnerSessionVerifier}
  from "./owner-read-better-auth-session.js";
import {PgOwnerReadPasskeyRegistration}
  from "./owner-read-passkey-registration.js";
import {PgOwnerReadWebAuthnIssuer} from "./owner-read-webauthn-issuer.js";
import {createOwnerReadReviewHandler} from "./owner-read-review-http.js";
import {createVerifiedOwnerIntentIntake}
  from "./owner-read-intent-transfer.js";
import {createOwnerAcceptanceServer}
  from "./owner-acceptance-server.js";

function required(name:string,env:NodeJS.ProcessEnv):string{
  const value=env[name];
  if(!value?.trim())throw Error("Missing independent owner issuer setting");
  return value;
}
function exactOrigin(text:string):string{
  const url=new URL(text);
  if(url.protocol!=="https:"||url.origin!==text||url.pathname!=="/"||
     url.username||url.password||url.search||url.hash||text.length>256)
    throw Error("Issuer requires exact HTTPS origin");
  return text;
}
function databaseURL(name:string,env:NodeJS.ProcessEnv){
  const value=required(name,env),parsed=new URL(value);
  if(!["postgres:","postgresql:"].includes(parsed.protocol)||
     !parsed.username||!parsed.password)
    throw Error("Independent PostgreSQL credentials required");
  return value;
}
function pool(url:string){
  return new Pool({connectionString:url,max:4,connectionTimeoutMillis:3_000});
}
type RoleIdentity={principal:string;database:string;schema:string;
  receipt_oid:string|null;passkey_oid:string|null};
async function roleIdentity(db:Pool):Promise<RoleIdentity>{
  const result=await db.query<RoleIdentity>(
    "SELECT session_user AS principal,current_database() AS database,"+
    "current_schema() AS schema,"+
    "to_regclass('owner_read_approvals')::oid::text AS receipt_oid,"+
    "to_regclass('owner_read_passkeys')::oid::text AS passkey_oid"
  );
  if(!result.rows[0]?.principal||!result.rows[0].receipt_oid||
     !result.rows[0].passkey_oid)
    throw Error("Independent owner SQL schema unavailable");
  return result.rows[0];
}

/**
 * Explicit independent owner issuer executable. Different process, identity,
 * SQL principals and signing boundary from the Cloud API. Does not expose
 * activation, WSS, Cloud OAuth token issuance or device read endpoints.
 *
 * This launcher is NOT used by the production Cloud deployment.
 */
export async function startOwnerReviewAuthority(env:NodeJS.ProcessEnv=process.env){
  if(env.OWNER_REVIEW_ENABLED!=="true")
    throw Error("Owner issuer disabled: explicit opt-in required");
  // Required values are read only after the exact opt-in. No defaults,
  // implicit local OAuth login, synthetic owner or generated signing key.
  const need=(name:string)=>required(name,env);
  const origin=exactOrigin(need("OWNER_REVIEW_ORIGIN"));
  const cloudOrigin=exactOrigin(need("OWNER_REVIEW_CLOUD_ORIGIN"));
  if(origin===cloudOrigin)throw Error("Independent owner and Cloud origins required");
  const port=Number(need("OWNER_REVIEW_PORT"));
  if(!Number.isInteger(port)||port<1024||port>65535)
    throw Error("Invalid independent owner HTTPS port");
  const identityAddress=databaseURL("OWNER_REVIEW_IDENTITY_DB_URL",env);
  const registrationAddress=databaseURL("OWNER_REVIEW_REGISTRATION_DB_URL",env);
  const issuerAddress=databaseURL("OWNER_REVIEW_ISSUER_DB_URL",env);
  const ownerSub=need("OWNER_REVIEW_OWNER_SUB");
  const secret=need("OWNER_REVIEW_BETTER_AUTH_SECRET");
  const githubId=need("OWNER_REVIEW_GITHUB_CLIENT_ID");
  const githubSecret=need("OWNER_REVIEW_GITHUB_CLIENT_SECRET");
  const rawCsrf=need("OWNER_REVIEW_CSRF_KEY");
  const csrf=Buffer.from(rawCsrf,"base64url");
  if(ownerSub.length>256||secret.length<32||githubId.length<8||
     githubSecret.length<20||rawCsrf.length<43||csrf.length<32||
     csrf.toString("base64url")!==rawCsrf)
    throw Error("Issuer owner identity and CSRF configuration incomplete");
  // Validate essential key material before opening DB sessions or listener.
  const tls={
    key:await readFile(need("OWNER_REVIEW_TLS_KEY_FILE")),
    cert:await readFile(need("OWNER_REVIEW_TLS_CERT_FILE"))
  };
  const verifyKey=await readFile(need("OWNER_REVIEW_CLOUD_PUBLIC_KEY_FILE"));
  const registrationScript=await readFile(
    new URL("./owner-read-enrollment-client.js",import.meta.url));
  const reviewScript=await readFile(
    new URL("./owner-read-review-client.js",import.meta.url));

  const identityPool=pool(identityAddress);
  const registrationPool=pool(registrationAddress);
  const issuerPool=pool(issuerAddress);
  let listening=false;
  try{
    const [id,reg,iss]=await Promise.all([
      roleIdentity(identityPool),roleIdentity(registrationPool),
      roleIdentity(issuerPool)
    ]);
    if(new Set([id.principal,reg.principal,iss.principal]).size!==3||
       id.principal===iss.principal||
       id.database!==reg.database||reg.database!==iss.database||
       id.schema!==reg.schema||reg.schema!==iss.schema||
       id.receipt_oid!==reg.receipt_oid||
       reg.receipt_oid!==iss.receipt_oid||
       id.passkey_oid!==reg.passkey_oid||
       reg.passkey_oid!==iss.passkey_oid)
      throw Error("Independent issuer database principal isolation failed");
    const registration=new PgOwnerReadPasskeyRegistration(
      registrationPool,origin);
    const issuer=new PgOwnerReadWebAuthnIssuer(issuerPool,origin);
    if(!await registration.verifyRestrictedRole()||
       !await issuer.verifyRestrictedRole())
      throw Error("Independent owner SQL role privileges denied");
    const identity=createIdentity({
      publicOrigin:origin,audience:origin+"/mcp",databaseUrl:identityAddress
    },{
      secret,githubId,githubSecret,googleId:"",googleSecret:""
    },identityPool);
    const authenticate=createIndependentOwnerSessionVerifier(
      identity,origin,ownerSub,csrf);
    const review=createOwnerReadReviewHandler(
      issuer,origin,authenticate,reviewScript);
    const intake=createVerifiedOwnerIntentIntake(
      origin,cloudOrigin,verifyKey,
      async requestOwner=>{
        if(requestOwner!==ownerSub)return null;
        // A selected credential must be independently ACTIVE. Ambiguous
        // multiple active credentials fail closed rather than choosing one.
        const result=await issuerPool.query<{credential_id:string}>(
          "SELECT credential_id FROM owner_read_passkeys "+
          "WHERE owner_sub=$1 AND enabled=true ORDER BY created_at DESC LIMIT 2",
          [ownerSub]);
        return result.rowCount===1?result.rows[0]!.credential_id:null;
      },review
    );
    const server=createOwnerAcceptanceServer({
      authorityOrigin:origin,identity,sessionVerifier:authenticate,
      registration,tls,clientScript:registrationScript,
      approval:{receiveSignedIntent:intake,review:review.handle}
    });
    try{
      await new Promise<void>((resolve,reject)=>{
        server.once("error",reject);
        server.listen(port,"127.0.0.1",()=>{
          server.off("error",reject);resolve();
        });
      });
      listening=true;
    }catch{
      server.close();
      throw Error("Independent issuer HTTPS listener failed");
    }
    let closed=false;
    return {
      server,
      close:async()=>{
        if(closed)return;
        closed=true;
        await new Promise<void>(resolve=>server.close(()=>resolve()));
        await Promise.all([issuerPool.end(),registrationPool.end(),
          identityPool.end()]);
      }
    };
  }catch{
    if(!listening)await Promise.allSettled([
      issuerPool.end(),registrationPool.end(),identityPool.end()
    ]);
    // Never leak raw connection string, credentials, private key or SQL
    // diagnostic output through a production error.
    throw Error("Independent owner issuer startup denied");
  }
}

if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  void startOwnerReviewAuthority().then(runtime=>{
    process.stdout.write(
      "Independent owner WebAuthn review listener on loopback; "+
      "no connector, activation or Cloud OAuth issuance\n"
    );
    for(const signal of ["SIGINT","SIGTERM"] as const){
      process.once(signal,()=>{
        void runtime.close().catch(()=>{process.exitCode=1;});
      });
    }
  }).catch(()=>{
    process.stderr.write("Independent owner issuer startup denied\n");
    process.exitCode=1;
  });
}
