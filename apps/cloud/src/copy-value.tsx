export function CopyValue({value,label}:Readonly<{value:string;label:string}>){
  return <div className="copy-value">
    <div className="copy-value-row"><code>{value}</code>
      <button type="button" className="button secondary" hidden={true} aria-label={"Copy "+label}>Copy</button>
    </div>
    <output className="copy-value-status" aria-live="polite"/>
  </div>;
}

export const copyValueClient=`"use strict";
(() => {
  for(const container of document.querySelectorAll(".copy-value")){
    const code=container.querySelector("code");
    const button=container.querySelector("button");
    const status=container.querySelector("output");
    if(!code||!button||!status)continue;
    button.hidden=false;
    button.addEventListener("click",async()=>{
      button.disabled=true;
      status.textContent="";
      try{
        await navigator.clipboard.writeText(code.textContent);
        status.textContent="Copied.";
      }catch{
        const selection=window.getSelection();
        if(selection){
          const range=document.createRange();
          range.selectNodeContents(code);
          selection.removeAllRanges();
          selection.addRange(range);
          status.textContent="Selected. Press Ctrl+C (⌘C on Mac) to copy.";
        }else status.textContent="Select and copy the value above.";
      }finally{
        button.disabled=false;
      }
    });
  }
})();
`;
