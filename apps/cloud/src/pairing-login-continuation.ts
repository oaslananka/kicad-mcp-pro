/**
 * Same-tab, browser-only continuation of an owner-initiated device pairing.
 * The short human verification code is not an OAuth credential. Neither it
 * nor the device's private secret may enter an HTTP query, cookie, or log.
 */
export const pairingLoginContinuationClient=String.raw`"use strict";
(() => {
  const key="kicad-pairing-return-v1";
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const userCode=/^[0-9A-HJKMNP-TV-Z]{6}-[0-9A-HJKMNP-TV-Z]{6}$/;
  const lifetime=300000;

  function valid(challenge,code){
    return typeof challenge==="string"&&uuid.test(challenge)&&
      typeof code==="string"&&userCode.test(code);
  }
  function clear(){
    try{window.sessionStorage.removeItem(key);}catch{/* storage unavailable */}
  }

  if(window.location.pathname==="/devices/pairing"){
    const hash=window.location.hash;
    // Fragment never appears in a request target. Remove it from the address bar
    // before any navigation, including to an external OAuth provider.
    if(hash)window.history.replaceState(null,"",window.location.pathname);
    if(!hash){clear();return;}
    const params=new URLSearchParams(hash.slice(1));
    const challenge=params.get("challenge"),code=params.get("code");
    if([...params.keys()].length!==2||
      params.getAll("challenge").length!==1||params.getAll("code").length!==1||
      !valid(challenge,code)){clear();return;}
    try{
      window.sessionStorage.setItem(key,JSON.stringify({
        challenge,code,created:Date.now()
      }));
    }catch{/* The normal sign-in form still works without continuation. */}
    return;
  }

  if(window.location.pathname==="/account"){
    let pending;
    try{
      const raw=window.sessionStorage.getItem(key);
      clear();
      if(!raw||raw.length>250)return;
      pending=JSON.parse(raw);
    }catch{return;}
    const age=Date.now()-pending?.created;
    if(!valid(pending?.challenge,pending?.code)||
       !Number.isFinite(age)||age<0||age>lifetime)return;
    window.location.replace("/devices/pairing#challenge="+
      pending.challenge+"&code="+pending.code);
  }
})();
`;
