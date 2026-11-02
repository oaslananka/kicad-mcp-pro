import type {PublicKeyCredentialRequestOptionsJSON} from "@simplewebauthn/server";
import type {OwnerReadApprovalIntent} from "./owner-read-webauthn-issuer.js";

/** Static, isolated issuer-facing review document; NOT a production route. */
export type OwnerReadReview={
  intent:OwnerReadApprovalIntent;
  options:PublicKeyCredentialRequestOptionsJSON;
};
function escapeHtml(s:string):string{
  return s.replace(/[&<>"']/g,c=>({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  })[c]??c);
}
function literalJson(x:unknown):string{
  return JSON.stringify(x).replace(/[<>&\u2028\u2029]/g,c=>
    "\\u"+c.charCodeAt(0).toString(16).padStart(4,"0"));
}
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Untrusted HTML must never be rendered by the caller. Require the same
 * verified-session owner context as the independent issuer. No user-controlled
 * title, URL, or script is executed. A registration or OAuth login alone is
 * not proof of user-verified approval for this specific request.
 */
export function renderOwnerReadReview(
  review:OwnerReadReview,authenticatedOwner:string,authorityOrigin:string,
  csrf:string
):string{
  const {intent,options}=review;
  const origin=new URL(intent.origin);
  const authority=new URL(authorityOrigin);
  if(!/^[A-Za-z0-9_-]{43}$/.test(csrf))throw Error("Owner review requires session CSRF");
  if(!authenticatedOwner||authenticatedOwner!==intent.ownerSub||
     !UUID.test(intent.requestId)||!UUID.test(intent.deviceId)||
     !UUID.test(intent.projectId)||
     origin.protocol!=="https:"||origin.origin!==intent.origin||
     authority.protocol!=="https:"||authority.origin!==authorityOrigin||
     options.rpId!==authority.hostname||
     options.userVerification!=="required"||
     !/^[A-Za-z0-9_-]{43}$/.test(options.challenge)||
     !Number.isSafeInteger(intent.expiresAtUnixMs)||
     intent.expiresAtUnixMs<=Date.now()||
     intent.expiresAtUnixMs-Date.now()>30_000||
     typeof intent.clientId!=="string"||!intent.clientId||
     intent.clientId.length>1024)throw Error("Invalid owner review scope");
  const data=literalJson({
    requestId:intent.requestId,challenge:options.challenge,
    publicKey:options,origin:authorityOrigin,
    expiresAtUnixMs:intent.expiresAtUnixMs,csrf
  });
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Approve a KiCad project summary</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif}
body{margin:0;background:#0e121b;color:#edf0f7;padding:24px}
main{max-width:620px;margin:5vh auto;background:#19202b;padding:28px;border:1px solid #343e50;border-radius:14px}
h1{font-size:1.75rem;margin:12px 0}.hint{color:#b8c3d7;line-height:1.6}
dl{display:grid;grid-template-columns:120px 1fr;gap:12px;line-height:1.4}
dt{color:#b8c3d7}dd{margin:0;overflow-wrap:anywhere}
button{font:inherit;border:0;border-radius:8px;padding:13px 18px;cursor:pointer}
button:disabled{cursor:not-allowed;opacity:.5}
#approve{background:#83baec;color:#111927;font-weight:650}
#deny{background:#303b4f;color:#f2f2f5}
.actions{display:flex;gap:10px;margin-top:25px;flex-wrap:wrap}
#status{margin-top:18px;min-height:1.5em}
</style></head><body><main>
<p class="hint">KiCad Cloud · Owner approval</p>
<h1>Approve one project summary?</h1>
<p class="hint">You are granting a single metadata-only read. No board contents,
file paths, DRC, ERC or write operations are authorized. This approval
expires within 30 seconds.</p>
<dl>
<dt>Owner</dt><dd id="owner">${escapeHtml(intent.ownerSub)}</dd>
<dt>OAuth client</dt><dd id="client">${escapeHtml(intent.clientId)}</dd>
<dt>Device</dt><dd id="device">${escapeHtml(intent.deviceId)}</dd>
<dt>Project</dt><dd id="project">${escapeHtml(intent.projectId)}</dd>
<dt>Operation</dt><dd id="operation">project_summary (presence flags only)</dd>
<dt>Cloud source</dt><dd id="origin">${escapeHtml(intent.origin)}</dd>
<dt>Approval service</dt><dd id="authority">${escapeHtml(authorityOrigin)}</dd>
<dt>Expires</dt><dd id="expires">${escapeHtml(new Date(intent.expiresAtUnixMs).toISOString())}</dd>
</dl>
<p class="hint">Approve only a request you initiated. Your passkey must verify
you by PIN, fingerprint, or equivalent user verification.</p>
<div class="actions"><button id="approve" type="button">Verify passkey &amp; approve</button>
<button id="deny" type="button">Deny</button></div>
<p id="status" role="status" aria-live="polite">Not approved.</p>
<script id="request-data" type="application/json">${data}</script>
<script defer src="/owner-read/review.js"></script>
</main></body></html>`;
}

export const ownerReadReviewHeaders={
  "Content-Type":"text/html; charset=utf-8",
  "Cache-Control":"no-store",
  "Referrer-Policy":"no-referrer",
  "X-Content-Type-Options":"nosniff",
  "Content-Security-Policy":
    "default-src 'none'; script-src 'self'; style-src 'unsafe-inline';"+
    " base-uri 'none'; frame-ancestors 'none'; form-action 'none'; connect-src 'self'"
} as const;
