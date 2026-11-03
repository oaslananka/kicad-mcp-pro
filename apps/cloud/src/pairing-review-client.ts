/** Browser-only helper: pairing code never appears in an HTTP URL or request log. */
export const pairingReviewClient=String.raw`"use strict";
(() => {
  const url=new URL(window.location.href);
  const details=document.getElementById("pairing-manual");
  const actions=document.getElementById("pairing-actions");
  const id=document.getElementById("pairing-id-input");
  const code=document.getElementById("pairing-code-input");
  const ready=document.getElementById("pairing-ready");
  const empty=document.getElementById("pairing-start");
  const invalid=document.getElementById("pairing-invalid");
  const display=document.getElementById("pairing-code");
  const data=url.hash.startsWith("#")?new URLSearchParams(url.hash.slice(1)):null;
  if(url.hash)window.history.replaceState(null,"",url.pathname+url.search);
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const humanCode=/^[0-9A-HJKMNP-TV-Z]{6}-[0-9A-HJKMNP-TV-Z]{6}$/;
  const challenge=data?.get("challenge")??"";
  const userCode=data?.get("code")??"";
  const valid=data&&[...data.keys()].length===2&&
    data.getAll("challenge").length===1&&data.getAll("code").length===1&&
    uuid.test(challenge)&&humanCode.test(userCode);
  if(valid){
    id.value=challenge;
    code.value=userCode;
    display.textContent=userCode;
    empty.hidden=true;
    ready.hidden=false;
    details.hidden=true;
    actions.hidden=false;
  }else{
    if(url.hash){invalid.hidden=false;empty.hidden=true;}
    actions.hidden=true;
    details.addEventListener("toggle",()=>{actions.hidden=!details.open;});
  }
})();
`;
