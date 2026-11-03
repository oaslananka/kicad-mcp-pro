import {AsyncLocalStorage} from "node:async_hooks";

type IssuanceContext = {revocationFenceRejected:boolean};
const issuanceContext=new AsyncLocalStorage<IssuanceContext>();

/** Called only from Better Auth's onAPIError callback. */
export function captureOAuthProviderError(error:unknown):void {
  const context=issuanceContext.getStore();
  if(!context) return;
  if(error && typeof error==="object" && "code" in error && "message" in error &&
    error.code==="23514" && error.message==="oauth_client_revoked") {
    context.revocationFenceRejected=true;
  }
}

/**
 * The pinned provider emits HTTP 500 when PostgreSQL denies a late refresh
 * INSERT. Convert ONLY that specific, captured SQL fence to RFC 6749's
 * invalid_grant. All other provider responses pass through unchanged.
 * AsyncLocalStorage isolates overlapping OAuth requests.
 */
export async function oauthProviderResponse(request:Request,handler:(request:Request)=>Promise<Response>):Promise<Response>{
  if(request.method!=="POST" || new URL(request.url).pathname!=="/api/auth/oauth2/token"){
    return handler(request);
  }
  // Do not rewrite generic endpoint errors or authorization-code grants.
  if(request.headers.get("content-type")?.split(";")[0].trim()!=="application/x-www-form-urlencoded"){
    return handler(request);
  }
  const encoded=await request.clone().text();
  if(encoded.length>8192 || new URLSearchParams(encoded).get("grant_type")!=="refresh_token"){
    return handler(request);
  }
  return issuanceContext.run({revocationFenceRejected:false},async()=>{
    const context=issuanceContext.getStore();
    const response=await handler(request);
    if(response.status!==500 || !context?.revocationFenceRejected) return response;
    return new Response(JSON.stringify({
      error:"invalid_grant",error_description:"invalid refresh token"
    }),{
      status:400,
      headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store",
        "Pragma":"no-cache","X-Content-Type-Options":"nosniff"}
    });
  });
}
