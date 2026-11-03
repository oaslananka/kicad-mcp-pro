"use strict";
// Static browser script, not attached to production. The isolated issuer must
// enforce authenticated owner session, exact pending intent and CSRF/origin.
(() => {
  const approve = document.getElementById("approve");
  const deny = document.getElementById("deny");
  const status = document.getElementById("status");
  const data = JSON.parse(document.getElementById("request-data").textContent);
  let attempted = false;
  const bytes = (value) => {
    const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") +
      "=".repeat((4 - value.length % 4) % 4));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  const encode = (value) => {
    const b64 = btoa(String.fromCharCode(...new Uint8Array(value)));
    return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };
  const lock = (message) => {
    approve.disabled = true;
    deny.disabled = true;
    status.textContent = message;
  };
  deny.addEventListener("click", () => {
    attempted = true;
    lock("Request denied. No approval was sent.");
  });
  approve.addEventListener("click", async () => {
    if (attempted) return;
    attempted = true;
    if (Date.now() >= data.expiresAtUnixMs ||
        !location.protocol.startsWith("https") ||
        location.origin !== data.origin) {
      lock("Request expired or origin mismatch. No approval was sent.");
      return;
    }
    lock("Waiting for passkey user verification...");
    try {
      const source = data.publicKey;
      const credential = await navigator.credentials.get({
        publicKey: {
          ...source,
          challenge: bytes(source.challenge),
          allowCredentials: source.allowCredentials?.map((entry) => ({
            ...entry, id: bytes(entry.id)
          })),
          userVerification: "required"
        }
      });
      if (!credential || credential.type !== "public-key") {
        lock("No passkey assertion. Request not approved."); return;
      }
      const response = credential.response;
      const assertion = typeof credential.toJSON === "function"
        ? credential.toJSON()
        : {
          id:credential.id,rawId:encode(credential.rawId),
          type:credential.type,clientExtensionResults:{},
          response: {
            clientDataJSON:encode(response.clientDataJSON),
            authenticatorData:encode(response.authenticatorData),
            signature:encode(response.signature),
            ...(response.userHandle?{userHandle:encode(response.userHandle)}:{})
          }
        };
      const reply = await fetch("/owner-read/approval", {
        method:"POST",
        credentials:"same-origin",
        mode:"same-origin",
        cache:"no-store",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          requestId:data.requestId,challenge:data.challenge,
          csrf:data.csrf,assertion
        })
      });
      lock(reply.ok?"Passkey accepted. Approval submitted.":
        "Approval rejected or unavailable.");
    } catch {
      lock("Passkey verification cancelled or failed. No approval was sent.");
    }
  });
})();
