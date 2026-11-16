import assert from "node:assert/strict";
import {runInNewContext} from "node:vm";
import {test} from "node:test";
import {deviceOnboardingClient} from "../src/device-onboarding.js";
import {renderDevicesPage} from "../src/devices-ui.js";

test("first-time and returning devices expose an optional dialog with inline no-JS fallback",()=>{
  const html=renderDevicesPage([],undefined,true,{
    projects:[],clients:[],savedGrants:[],ownerSub:"owner",sandboxMode:false
  });
  assert.match(html,/href="#connect-computer"[^>]*>.*Add a device/);
  assert.match(html,/id="connect-computer"/);
  assert.match(html,/class="device-setup-wizard"/);
  assert.match(html,/id="device-connect-modal"/);
  assert.match(html,/aria-labelledby="device-connect-modal-title"/);
  assert.match(html,/aria-label="Close device setup"/);
  assert.match(html,/src="\/assets\/device-onboarding\.js" defer/);
  assert.equal((html.match(/id="cloud-device-os-windows"/g)??[]).length,1,
    "one reusable wizard avoids duplicate form controls");
});

test("real dialog action moves the existing wizard and restores focus on close",()=>{
  const handlers:Record<string,(event?:any)=>void>={};
  let opener:((event:any)=>void)|undefined;
  let focusedRadio=0,focusedTrigger=0,moved=0,restored=0,showCalls=0;
  type MockContainer={appendChild(node:MockWizard):void;
    insertBefore?(node:MockWizard,next:unknown):void};
  type MockWizard={parentNode:MockContainer;nextSibling:null;
    querySelector(query:string):{focus():void}};
  const home:MockContainer={
    appendChild(node){node.parentNode=home;restored++;},
    insertBefore(node,_next){node.parentNode=home;restored++;}
  };
  const wizard:MockWizard={
    parentNode:home,
    nextSibling:null,
    querySelector:(_query)=>({focus:()=>{focusedRadio++;}})
  };
  const content:MockContainer={appendChild(node){node.parentNode=content;moved++;}};
  const modal={
    open:false,
    showModal(){this.open=true;showCalls++;},
    close(){this.open=false;handlers.close?.();},
    addEventListener(name:string,callback:(event?:any)=>void){handlers[name]=callback;}
  };
  const trigger={
    addEventListener(_name:string,callback:(event:any)=>void){opener=callback;},
    focus(){focusedTrigger++;}
  };
  const section={querySelector:(_selector:string)=>wizard};
  const elements:Record<string,any>={
    "connect-computer":section,
    "device-connect-modal":modal,
    "device-connect-modal-content":content
  };
  const window={location:{hash:""}};
  runInNewContext(deviceOnboardingClient,{
    document:{
      querySelector:(_selector:string)=>trigger,
      getElementById:(id:string)=>elements[id]??null
    },
    window
  });
  assert.ok(opener);
  let prevented=0;
  const event={button:0,defaultPrevented:false,ctrlKey:false,altKey:false,
    shiftKey:false,metaKey:false,preventDefault(){prevented++;}};
  opener?.(event);
  assert.equal(prevented,1);
  assert.equal(moved,1);
  assert.equal(showCalls,1);
  assert.equal(focusedRadio,1);
  assert.equal(modal.open,true);
  modal.close();
  assert.equal(restored,1);
  assert.equal(focusedTrigger,1);
  assert.equal(wizard.parentNode,home);
  assert.equal(window.location.hash,"");
  opener?.({...event,metaKey:true});
  assert.equal(showCalls,1,"modified link activation remains ordinary browser navigation");
});

test("unsupported native dialog leaves no-JS link fully usable",()=>{
  let intercepted=false;
  const trigger={addEventListener:()=>{intercepted=true;}};
  runInNewContext(deviceOnboardingClient,{
    document:{
      querySelector:()=>trigger,
      getElementById:(id:string)=>{
        if(id==="connect-computer")return {querySelector:()=>({parentNode:{}})};
        if(id==="device-connect-modal")return {};
        return {};
      }
    },
    window:{location:{hash:""}}
  });
  assert.equal(intercepted,false);
});
