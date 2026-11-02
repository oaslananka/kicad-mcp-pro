"use strict";
// Standalone independently authenticated owner issuer, not the Cloud router.
(() => {
  const button=document.getElementById("register");
  const status=document.getElementById("status");
  const {csrf}=JSON.parse(document.getElementById("enrollment").textContent);
  let attempted=false;
  const decode=value=>{
    const encoded=value.replaceAll("-","+").replaceAll("_","/")+
      "=".repeat((4-value.length%4)%4);
    return Uint8Array.from(atob(encoded),char=>char.charCodeAt(0));
  };
  const finish=message=>{
    button.disabled=true;
    status.textContent=message;
  };
  button.addEventListener("click",async()=>{
    if(attempted)return;
    attempted=true;
    button.disabled=true;
    status.textContent="Requesting owner passkey challenge...";
    try{
      if(location.protocol!=="https:"){
        finish("Insecure origin; registration is blocked.");return;
      }
      const started=await fetch("/owner-passkey/register/begin",{
        method:"POST",credentials:"same-origin",cache:"no-store",mode:"same-origin",
        headers:{"Content-Type":"application/json"},body:JSON.stringify({csrf})
      });
      if(!started.ok)throw new Error("Registration challenge refused");
      const {options,requestId}=await started.json();
      if(!options||options.rp?.id!==location.hostname||
        options.authenticatorSelection?.userVerification!=="required"||
        typeof options.challenge!=="string")
        throw new Error("Untrusted passkey challenge");
      status.textContent="Waiting for your passkey PIN or biometric verification...";
      const credential=await navigator.credentials.create({publicKey:{
        ...options,
        challenge:decode(options.challenge),
        user:{...options.user,id:decode(options.user.id)},
        excludeCredentials:options.excludeCredentials?.map(value=>({
          ...value,id:decode(value.id)
        }))
      }});
      if(!credential||credential.type!=="public-key"||
         typeof credential.toJSON!=="function")
        throw new Error("Passkey creation not supported");
      const completed=await fetch("/owner-passkey/register/complete",{
        method:"POST",credentials:"same-origin",cache:"no-store",mode:"same-origin",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({csrf,requestId,response:credential.toJSON()})
      });
      if(!completed.ok)throw new Error("Passkey verification rejected");
      const result=await completed.json();
      if(result?.state!=="registered_inactive")
        throw new Error("Passkey not stored inactive");
      finish("Passkey registered but not activated. Independent owner approval is required.");
    }catch{
      finish("Passkey registration cancelled or denied. No access was authorized.");
    }
  });
})();
