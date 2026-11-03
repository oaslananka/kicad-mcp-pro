import {readFile} from "node:fs/promises";
import {Pool} from "pg";
import {createIdentity} from "./identity.js";
import {createIndependentOwnerSessionVerifier}
  from "./owner-read-better-auth-session.js";
import {PgOwnerReadPasskeyRegistration}
  from "./owner-read-passkey-registration.js";
import {createOwnerAcceptanceServer}
  from "./owner-acceptance-server.js";

function required(name:string):string{
  const value=process.env[name];
  if(!value||!value.trim())throw Error("Missing independent owner authority setting: "+name);
  return value;
}
async function main(){
  const origin=required("OWNER_ACCEPTANCE_ORIGIN");
  const originURL=new URL(origin);
  if(originURL.protocol!=="https:"||originURL.origin!==origin||
     originURL.pathname!=="/"||originURL.search||originURL.hash||
     originURL.username||originURL.password||origin.length>256)
    throw Error("Owner acceptance requires one exact HTTPS origin");
  const identityURL=required("OWNER_ACCEPTANCE_IDENTITY_DB_URL");
  const registrationURL=required("OWNER_ACCEPTANCE_REGISTRATION_DB_URL");
  const idDb=new URL(identityURL),regDb=new URL(registrationURL);
  if(!["postgres:","postgresql:"].includes(idDb.protocol)||
     !["postgres:","postgresql:"].includes(regDb.protocol)||
     identityURL===registrationURL||
     (idDb.username===regDb.username&&idDb.host===regDb.host))
    throw Error("Separate identity and least-privilege registration database users required");
  const owner=required("OWNER_ACCEPTANCE_OWNER_SUB");
  const authSecret=required("OWNER_ACCEPTANCE_BETTER_AUTH_SECRET");
  const githubId=required("OWNER_ACCEPTANCE_GITHUB_CLIENT_ID");
  const githubSecret=required("OWNER_ACCEPTANCE_GITHUB_CLIENT_SECRET");
  const rawCsrf=required("OWNER_ACCEPTANCE_CSRF_KEY");
  const csrf=Buffer.from(rawCsrf,"base64url");
  if(rawCsrf.length<43||csrf.length<32||csrf.toString("base64url")!==rawCsrf)
    throw Error("Owner CSRF key must be independently generated base64url 32+ bytes");
  if(authSecret.length<32||githubId.length<8||githubSecret.length<20||
     owner.length>256||owner.length<1)
    throw Error("Independent owner, OAuth and signing configuration incomplete");
  const port=Number(required("OWNER_ACCEPTANCE_PORT"));
  if(!Number.isInteger(port)||port<1024||port>65535)
    throw Error("Invalid separate owner acceptance port");
  // Bind loopback ONLY. A separately reviewed, TLS-preserving ingress
  // is required for any real OAuth provider callback from the Internet.
  const tls={
    key:await readFile(required("OWNER_ACCEPTANCE_TLS_KEY_FILE")),
    cert:await readFile(required("OWNER_ACCEPTANCE_TLS_CERT_FILE"))
  };
  const script=await readFile(new URL("./owner-read-enrollment-client.js",import.meta.url));
  const openIsolatedPool=(address:string)=>new Pool({
    connectionString:address,max:4,connectionTimeoutMillis:3_000
  });
  const identityPool=openIsolatedPool(identityURL);
  const enrollmentPool=openIsolatedPool(registrationURL);
  try{
    // Reuse the very same role fence that protects each registration call.
    // Never maintain a second SQL privilege list in the launcher.
    const registration=new PgOwnerReadPasskeyRegistration(enrollmentPool,origin);
    if(!await registration.verifyRestrictedRole())
      throw Error("Independent enrollment DB login has unsafe privileges");
    const identity=createIdentity({
      publicOrigin:origin,audience:origin+"/mcp",databaseUrl:identityURL
    },{secret:authSecret,githubId,githubSecret,
      googleId:"",googleSecret:""},identityPool);
    const ownerSession=createIndependentOwnerSessionVerifier(
      identity,origin,owner,csrf);
    const server=createOwnerAcceptanceServer({
      authorityOrigin:origin,identity,sessionVerifier:ownerSession,
      registration,tls,clientScript:script
    });
    await new Promise<void>((resolve,reject)=>{
      server.once("error",reject);
      server.listen(port,"127.0.0.1",()=>{server.off("error",reject);resolve();});
    });
    process.stdout.write(
      "Independent owner enrollment acceptance listener on loopback; "+
      "activation, approval and connector disabled\n"
    );
    for(const signal of ["SIGINT","SIGTERM"] as const)
      process.once(signal,()=>{
        void (async()=>{
          await new Promise<void>(resolve=>server.close(()=>resolve()));
          await enrollmentPool.end();await identityPool.end();
        })().catch(()=>{process.exitCode=1;});
      });
  }catch(error){
    await enrollmentPool.end();
    await identityPool.end();
    throw error;
  }
}
void main().catch(()=>{
  // Configuration/DB errors may contain secrets: never print raw exceptions.
  process.stderr.write("Independent owner acceptance startup denied; check secure configuration\n");
  process.exitCode=1;
});
