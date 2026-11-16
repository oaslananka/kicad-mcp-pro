/** Progressive enhancement for the existing no-JavaScript device wizard. */
export const deviceOnboardingClient = `"use strict";
(() => {
  const trigger = document.querySelector(".device-add-button[href='#connect-computer']");
  const section = document.getElementById("connect-computer");
  const wizard = section?.querySelector(".device-setup-wizard");
  const modal = document.getElementById("device-connect-modal");
  const content = document.getElementById("device-connect-modal-content");
  if(!trigger || !section || !wizard || !modal || !content ||
      typeof modal.showModal !== "function")return;
  const home = wizard.parentNode;
  const next = wizard.nextSibling;
  if(!home)return;
  const restore = () => {
    if(next && next.parentNode === home)home.insertBefore(wizard,next);
    else home.appendChild(wizard);
  };
  trigger.addEventListener("click", event => {
    if(event.defaultPrevented || event.button !== 0 ||
       event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
    event.preventDefault();
    if(modal.open)return;
    content.appendChild(wizard);
    try{
      modal.showModal();
      wizard.querySelector('input[type="radio"]:checked')?.focus();
    }catch{
      restore();
      window.location.hash = "connect-computer";
    }
  });
  modal.addEventListener("close", () => {restore();trigger.focus();});
  modal.addEventListener("click", event => {
    if(event.target === modal)modal.close();
  });
})();
`;
