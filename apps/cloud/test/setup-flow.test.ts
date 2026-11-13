import assert from "node:assert/strict";
import {runInNewContext} from "node:vm";
import {test} from "node:test";
import {copyValueClient} from "../src/copy-value.js";
import {renderConnectionsPage} from "../src/connections-ui.js";
import {renderDevicesPage} from "../src/devices-ui.js";

test("setup copy reports actual clipboard success and selects the value when clipboard access fails",async()=>{
  for(const access of ["allowed","denied","unavailable"]){
    const value="https://cloud.example.test/mcp";
    const code={textContent:value},status={textContent:""};
    let click:()=>Promise<void>=async()=>{},copied="",selected=false;
    const button={hidden:true,disabled:false,addEventListener:(_name:string,handler:typeof click)=>{click=handler;}};
    const container={querySelector:(selector:string)=>{
      if(selector==="code")return code;
      if(selector==="button")return button;
      return status;
    }};
    runInNewContext(copyValueClient,{
      navigator:access==="unavailable"?{}:{clipboard:{writeText:async(text:string)=>{
        if(access==="denied")throw new Error("Permission denied");
        copied=text;
      }}},
      document:{querySelectorAll:()=>[container],createRange:()=>({
        selectNodeContents:(target:unknown)=>{assert.equal(target,code);}
      })},
      window:{getSelection:()=>({removeAllRanges:()=>{},addRange:()=>{selected=true;}})}
    });
    assert.equal(button.hidden,false,"copy is progressively enhanced");
    await click();
    assert.equal(button.disabled,false,"copy remains retryable");
    if(access==="allowed"){
      assert.equal(copied,value);
      assert.equal(status.textContent,"Copied.");
      assert.equal(selected,false);
    }else{
      assert.equal(copied,"");
      assert.equal(selected,true);
      assert.match(status.textContent,/Selected.*Ctrl\+C.*⌘C/);
      assert.doesNotMatch(status.textContent,/Copied/);
    }
  }
});

test("AI setup precedes the empty app list and leads back to project access",()=>{
  const empty=renderConnectionsPage([],undefined,"https://cloud.example.test");
  assert.ok(empty.indexOf('id="mcp-setup"')<empty.indexOf('id="connected-clients"'));
  assert.match(empty,/Copy MCP endpoint/);
  assert.match(empty,/Authorize your account/);
  assert.match(empty,/Choose project access/);
  assert.match(empty,/href="\/projects"[^>]*>Choose projects/);
  assert.doesNotMatch(empty,/authorize it below/);
  const connected=renderConnectionsPage([{id:"app",clientId:"client",name:"AI app",scopes:["projects:read"],csrf:"fixture"}],undefined,"https://cloud.example.test");
  assert.ok(connected.indexOf('id="connected-clients"')<connected.indexOf('id="mcp-setup"'),"returning users see their apps first");
  assert.doesNotMatch(renderConnectionsPage([],undefined,"http://127.0.0.1:8787"),/Copy MCP endpoint/);
  const devices=renderDevicesPage([]);
  assert.match(devices,/Copy setup command/);
  assert.match(devices,/src="\/assets\/copy-value\.js"/);
});
