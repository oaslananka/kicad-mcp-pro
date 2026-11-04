import type {IncomingMessage,ServerResponse} from "node:http";
import type {RegistrationSessionVerifier} from "./owner-read-registration-http.js";

/** Standalone, disabled-by-default issuer UI; a real independent owner
 * session verifier must be injected. No production router mounts it. */
function htmlEscape(input:string):string{
  return input.replace(/[&<>"']/g,c=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[c]??c);
}
function jsonLiteral(input:unknown):string{
  return JSON.stringify(input).replace(/[<>&\u2028\u2029]/g,c=>
    "\\u"+c.codePointAt(0)!.toString(16).padStart(4,"0"));
}
const headers={
  "Content-Type":"text/html; charset=utf-8",
  "Cache-Control":"no-store",
  "Referrer-Policy":"no-referrer",
  "X-Content-Type-Options":"nosniff",
  "X-Frame-Options":"DENY",
  "Content-Security-Policy":
    "default-src 'none'; script-src 'self'; style-src 'unsafe-inline';"+
    " base-uri 'none'; frame-ancestors 'none'; form-action 'none'; connect-src 'self'"
} as const;
export function renderOwnerPasskeyEnrollment(ownerSub:string,csrf:string):string{
  if(typeof ownerSub!=="string"||!ownerSub||ownerSub.length>256||
     typeof csrf!=="string"||csrf.length<16||csrf.length>512)
    throw new Error("Invalid verified owner session");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Register owner passkey · KiCad Cloud</title>
<style>
:root{font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color-scheme:dark}
body{margin:0;background:#0b0f17;color:#f1f5f9;padding:24px}
main{max-width:620px;margin:6vh auto;background:#131926;border:1px solid rgba(255,255,255,0.08);
padding:32px;border-radius:14px;line-height:1.6;box-shadow:0 10px 25px -5px rgba(0,0,0,0.5)}
h1{font-size:1.7rem;line-height:1.3;margin:4px 0 15px;letter-spacing:-0.03em;font-weight:700}
.hint{color:#94a3b8}
#owner{font-family:'JetBrains Mono','Fira Code',ui-monospace,monospace;color:#38bdf8}
button{background:#0284c7;color:#ffffff;padding:12px 20px;border:0;border-radius:8px;
font:inherit;font-weight:650;cursor:pointer;font-size:13px;transition:background .15s,box-shadow .15s;
box-shadow:0 2px 8px rgba(2,132,199,0.3)}
button:hover:not(:disabled){background:#0369a1}
button:disabled{opacity:.55;cursor:not-allowed}
button:focus-visible{outline:2px solid #38bdf8;outline-offset:2px;box-shadow:0 0 0 2px #0b0f17,0 0 0 4px #38bdf8}
#status{min-height:2em;margin-top:22px;color:#94a3b8;font-size:13px}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{transition:none!important;animation:none!important}}
</style></head><body><main>
<p class="hint">KiCad Cloud · Owner security</p>
<h1>Register a passkey</h1>
<p>Owner: <strong id="owner">${htmlEscape(ownerSub)}</strong></p>
<p class="hint">Your browser will ask you to create a passkey using PIN, fingerprint
or another user-verification method. Registration does not activate
a passkey and does not authorize any remote KiCad read. Independent
owner approval is required before this passkey can be used.</p>
<button type="button" id="register">Register passkey</button>
<p role="status" aria-live="polite" id="status">Not registered.</p>
<script id="enrollment" type="application/json">${jsonLiteral({csrf})}</script>
<script defer src="/owner-passkey/register/client.js"></script>
</main></body></html>`;
}
export function createOwnerPasskeyEnrollmentPageHandler(
  authorityOrigin:string,authenticate:RegistrationSessionVerifier
){
  const origin=new URL(authorityOrigin);
  if(origin.protocol!=="https:"||origin.origin!==authorityOrigin||
    origin.pathname!=="/"||origin.search||origin.hash)
    throw new Error("Issuer requires exact HTTPS origin");
  return async (request:IncomingMessage,response:ServerResponse):Promise<void>=>{
    const fail=(status:number)=>{
      response.writeHead(status,{"Cache-Control":"no-store",
        "X-Content-Type-Options":"nosniff"});response.end();
    };
    if(request.url!=="/owner-passkey/register"||request.method!=="GET"){
      fail(404);return;
    }
    if(request.headers.host!==origin.host||
      (request.headers["sec-fetch-site"]&&
       !["same-origin","none"].includes(request.headers["sec-fetch-site"]))){
      fail(403);return;
    }
    try{
      const session=await authenticate(request);
      if(!session?.ownerSub||!session.csrf){fail(403);return;}
      const page=renderOwnerPasskeyEnrollment(session.ownerSub,session.csrf);
      response.writeHead(200,headers);response.end(page);
    }catch{fail(403);}
  };
}
export const ownerEnrollmentPageHeaders=headers;
