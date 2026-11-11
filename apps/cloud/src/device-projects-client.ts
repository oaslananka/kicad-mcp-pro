/** Small CSP-compliant browser enhancement for local device/project management. */
export const deviceProjectsClient=String.raw`"use strict";
(() => {
  const storagePrefix="kicad-mcp-cloud:device-projects:v1:";
  const menus=document.querySelectorAll("details.device-projects-menu[data-device-id]");
  for(const menu of menus){
    const key=storagePrefix+menu.getAttribute("data-device-id");
    try{
      const saved=window.localStorage.getItem(key);
      if(saved==="closed")menu.open=false;
      else if(saved==="open")menu.open=true;
    }catch{/* Private browsing or disabled storage: default open. */}
    menu.addEventListener("toggle",()=>{
      try{window.localStorage.setItem(key,menu.open?"open":"closed");}
      catch{/* Keep native details usable without storage. */}
    });
  }

  document.addEventListener("click",event=>{
    const trigger=event.target instanceof Element?
      event.target.closest("button[data-open-project-dialog]"):null;
    if(trigger){
      const id=trigger.getAttribute("data-open-project-dialog");
      const dialog=id?document.getElementById(id):null;
      if(dialog instanceof HTMLDialogElement){
        dialog.showModal();
        if(dialog.classList.contains("project-rename-dialog")){
          const name=dialog.querySelector('input[name="alias"]');
          if(name instanceof HTMLInputElement){name.focus();name.select();}
        }
      }
      return;
    }
    const close=event.target instanceof Element?
      event.target.closest("button[data-close-project-dialog]"):null;
    if(close){
      const dialog=close.closest("dialog");
      if(dialog instanceof HTMLDialogElement)dialog.close();
    }
  });
  document.querySelectorAll("dialog.project-action-dialog").forEach(dialog=>{
    dialog.addEventListener("click",event=>{
      if(event.target===dialog)dialog.close();
    });
  });

  // Owner forms are tied to a short-lived CSRF cookie. Leaving a device
  // screen open for five minutes must not strand the next Browse in a
  // misleading "Device management not enabled" error page.
  const managedForms=document.querySelectorAll(
    '.device-native-browse-form, .project-action-dialog form'
  );
  for(const form of managedForms){
    form.addEventListener("submit",async event=>{
      const token=form.querySelector('input[name="csrf"]');
      if(!(token instanceof HTMLInputElement))return;
      // Always refresh: a second browser tab may have rotated the HttpOnly
      // CSRF cookie even while this form's timestamp still looks recent.
      event.preventDefault();
      if(form.dataset.refreshing==="yes")return;
      form.dataset.refreshing="yes";
      const submitter=event.submitter;
      if(submitter instanceof HTMLButtonElement)submitter.disabled=true;
      try{
        // GET is read-only and refreshes the session-bound nonce + CSRF
        // cookie; never reuse another project's token or submit on failure.
        const response=await fetch("/devices?csrf-refresh=1",{
          method:"GET",credentials:"same-origin",cache:"no-store"
        });
        if(!response.ok||!response.headers.get("content-type")?.includes("text/html"))
          throw new Error("Device session refresh failed");
        const updated=new DOMParser().parseFromString(await response.text(),"text/html");
        const action=form.getAttribute("action");
        const idField=form.querySelector('input[name="project_id"]')?
          "project_id":"device_id";
        const id=form.querySelector('input[name="'+idField+'"]')?.value;
        if(!id||!action)throw new Error("Missing form identity");
        const current=Array.from(updated.querySelectorAll('form[action="'+action+'"]'))
          .find(item=>item.querySelector('input[name="'+idField+'"]')?.value===id);
        const fresh=current?.querySelector('input[name="csrf"]')?.value;
        if(!fresh||fresh.split(".")[0].length!==13)throw new Error("Fresh owner form unavailable");
        token.value=fresh;
        // The user already clicked the original, validated submit button;
        // submit once without invoking the refresh handler again.
        HTMLFormElement.prototype.submit.call(form);
      }catch{
        form.dataset.refreshing="no";
        if(submitter instanceof HTMLButtonElement)submitter.disabled=false;
        let status=form.querySelector(".project-form-refresh-error");
        if(!status){
          status=document.createElement("p");
          status.className="project-form-refresh-error";
          status.setAttribute("role","alert");
          form.appendChild(status);
        }
        status.textContent="Could not refresh the device session. Reload this page and try again.";
      }
    });
  }
})();
`;
