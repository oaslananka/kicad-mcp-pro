import assert from "node:assert/strict";
import {test} from "node:test";
import {runInNewContext} from "node:vm";
import {randomUUID} from "node:crypto";
import {pairingReviewClient} from "../src/pairing-review-client.js";

function page(hash:string){
  const elements=new Map<string, {
    value?:string; textContent?:string; hidden:boolean; open?:boolean;
    addEventListener:(event:string,listener:()=>void)=>void; trigger?:()=>void;
  }>();
  for(const name of ["pairing-manual","pairing-actions","pairing-id-input",
    "pairing-code-input","pairing-ready","pairing-start","pairing-invalid","pairing-code"]){
    elements.set(name,{hidden:false,addEventListener(_e,fn){this.trigger=fn;}});
  }
  const calls:string[]=[];
  const window={
    location:{href:"https://cloud.example/devices/pairing"+hash},
    history:{replaceState(_a:unknown,_b:string,path:string){calls.push(path);}}
  };
  runInNewContext(pairingReviewClient,{
    window,document:{getElementById:(name:string)=>elements.get(name)},
    URL,URLSearchParams
  });
  return {elements,calls};
}
test("one-click pairing link fills the form without auto-approval and scrubs URL fragment",()=>{
  const id=randomUUID(),code="ABCDEF-123456";
  const p=page("#challenge="+id+"&code="+code);
  assert.equal(p.elements.get("pairing-id-input")?.value,id);
  assert.equal(p.elements.get("pairing-code-input")?.value,code);
  assert.equal(p.elements.get("pairing-code")?.textContent,code);
  assert.equal(p.elements.get("pairing-ready")?.hidden,false);
  assert.equal(p.elements.get("pairing-start")?.hidden,true);
  assert.equal(p.elements.get("pairing-actions")?.hidden,false);
  assert.equal(p.elements.get("pairing-manual")?.hidden,true);
  assert.deepEqual(p.calls,["/devices/pairing"]);
});
test("no link hides actionable approval until advanced form is deliberately opened",()=>{
  const p=page("");
  assert.equal(p.elements.get("pairing-actions")?.hidden,true);
  const manual=p.elements.get("pairing-manual")!;
  manual.open=true;
  manual.trigger?.();
  assert.equal(p.elements.get("pairing-actions")?.hidden,false);
  assert.deepEqual(p.calls,[]);
});
test("malformed and duplicate fragment fields never unlock approval",()=>{
  for(const hash of ["#challenge=bad&code=ABCDEF-123456",
    "#challenge="+randomUUID()+"&code=ABCDEF-123456&code=ABCDEF-123456",
    "#challenge="+randomUUID()+"&code=CODE-123",
    "#challenge="+randomUUID()+"&code=ABCDEF-123456&deviceCode=private"]){
    const p=page(hash);
    assert.equal(p.elements.get("pairing-actions")?.hidden,true);
    assert.equal(p.elements.get("pairing-invalid")?.hidden,false);
    assert.deepEqual(p.calls,["/devices/pairing"]);
  }
});
