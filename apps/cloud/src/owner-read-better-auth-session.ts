import {createHmac} from "node:crypto";
import type {IncomingMessage} from "node:http";
import type {Identity} from "./identity.js";
import type {RegistrationSessionVerifier}
  from "./owner-read-registration-http.js";

/**
 * An independently deployed owner's Better Auth identity instance can
 * authenticate the standalone passkey issuer/registration authority.
 *
 * SECURITY: The instance MUST be configured for the independent authority's
 * own origin, session database, and provider credentials. Never proxy or
 * transplant Cloud's first-party session cookie to a different host. This
 * factory is NOT mounted by the production Cloud HTTP router.
 */
export function createIndependentOwnerSessionVerifier(
  identity:Pick<Identity,"api"|"options">,
  authorityOrigin:string,
  expectedOwnerSub:string,
  csrfKey:Uint8Array
):RegistrationSessionVerifier{
  const origin=new URL(authorityOrigin);
  if(origin.protocol!=="https:"||origin.origin!==authorityOrigin||
     origin.pathname!=="/"||origin.search||origin.hash||
     identity.options.baseURL!==authorityOrigin)
    throw Error("Independent Better Auth must use exact HTTPS authority origin");
  if(typeof expectedOwnerSub!=="string"||!expectedOwnerSub||
     expectedOwnerSub.length>256||csrfKey.length<32)
    throw Error("Owner allowlist and independent CSRF key required");

  const key=Buffer.from(csrfKey);
  return async (request:IncomingMessage)=>{
    if(request.headers.host!==origin.host ||
       request.headers.authorization !== undefined ||
       request.headers["x-forwarded-host"] !== undefined ||
       request.headers["x-forwarded-proto"] !== undefined)return null;
    const raw=request.headers.cookie;
    if(typeof raw!=="string"||raw.length===0||raw.length>4096)return null;
    // Never forward untrusted headers such as arbitrary Bearer, fake user
    // subjects, forwarded hosts or origin to the Better Auth API.
    let session:Awaited<ReturnType<Identity["api"]["getSession"]>>;
    try{
      session=await identity.api.getSession({
        headers:new Headers({cookie:raw})
      });
    }catch{return null;}
    if(!session?.user||!session.session||
      session.user.id!==expectedOwnerSub||
      session.user.emailVerified!==true||
      typeof session.session.id!=="string"||!session.session.id||
      typeof session.session.token!=="string"||!session.session.token||
      new Date(session.session.expiresAt).getTime()<=Date.now())return null;

    // Domain-separated, authenticated, session-bound token. No CSRF secret
    // or session ID is returned; revoking the Better Auth session makes the
    // verifier reject future requests even with a copied CSRF token.
    const csrf=createHmac("sha256",key).update(JSON.stringify([
      "owner-passkey-registration-session-v1",authorityOrigin,
      expectedOwnerSub,session.session.id,session.session.token
    ])).digest("base64url");
    return {ownerSub:expectedOwnerSub,csrf};
  };
}
