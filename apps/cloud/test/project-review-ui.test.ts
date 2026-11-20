import assert from "node:assert/strict";
import {test} from "node:test";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {runInNewContext} from "node:vm";
import {transformSync} from "esbuild";
const template=readFileSync(fileURLToPath(new URL("../src/project-review.html",import.meta.url)),"utf8");
const script=readFileSync(fileURLToPath(new URL("../src/project-review-app.ts",import.meta.url)),"utf8");

test("portable MCP App presents an accessible, host-adaptive project review",()=>{
  assert.match(template,/name="viewport"/);
  assert.match(template,/role="status" aria-live="polite"/);
  assert.match(template,/id="details"[^>]*hidden/);
  assert.match(template,/id="project-name"/);
  assert.match(template,/id="project-connection"/);
  assert.match(template,/id="refresh"[^>]*disabled/);
  assert.match(template,/id="check-editor"[^>]*disabled/);
  assert.match(template,/id="editor-status"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(template,/@media\s*\(prefers-color-scheme:\s*light\)/);
  assert.match(template,/--color-text-primary/);
  assert.match(template,/min-height:\s*44px/);
  assert.doesNotMatch(template,/@import|url\(https?:/i);
  assert.match(script,/new App\(/);
  assert.match(script,/\.ontoolresult\s*=/);
  assert.match(script,/\.callServerTool\(/);
  assert.match(script,/\.textContent\s*=/);
  assert.match(script,/readAttemptReady===true/);
  assert.match(script,/MCP read tools can be requested/);
  assert.match(script,/sessionNativeWriteMode==="not_advertised"/);
  assert.match(script,/sessionNativeWriteMode==="advertised"/);
  assert.match(script,/Editing is not enabled in this Connector session/);
  assert.match(script,/Review your project Edit access/);
  assert.match(script,/advertises native editing but does not prove authorization/);
  assert.match(script,/name:"local_mcp_read"/);
  assert.match(script,/tool_name:"kicad_get_server_info"/);
  assert.match(script,/name:"local_mcp_catalog"/);
  assert.match(script,/tool_name:"pcb_move_footprint"/);
  assert.match(script,/accessMode==="write"/);
  assert.match(template,/>Check PCB Editor<\/button>/);
  assert.match(script,/does not authorize editing or prove save\/reopen/);
  assert.match(script,/reported capabilities do not include the MCP bridge/);
  assert.match(script,/does not confirm native editing or KiCad readiness/);
  assert.doesNotMatch(script,/innerHTML\s*=/);
});

type Snapshot={structuredContent?:unknown};
type ServerCall={name:string;arguments:{project_id:string;tool_name?:string;arguments?:Record<string,unknown>}};
type StubNode={
  disabled:boolean;hidden:boolean;textContent:string;className:string;
  click?:()=>Promise<void>;
  addEventListener:(name:string,fn:()=>Promise<void>)=>void;
};

function createReviewHarness(){
  const ids=["status","details","refresh","check-editor","editor-status",
    "project-name","project-connection","project-id"];
  const nodes=Object.fromEntries(ids.map(id=>{
    const node:StubNode={
      disabled:true,hidden:true,textContent:"",className:"",
      addEventListener(name,fn){if(name==="click")node.click=fn;}
    };
    return [id,node];
  })) as Record<string,StubNode>;
  const calls:ServerCall[]=[];
  let request:(_call:ServerCall)=>Promise<Snapshot>=async()=>({structuredContent:{available:true,tools:[]}});
  class AppStub {
    ontoolresult?: (result:Snapshot)=>void;
    connect(){return Promise.resolve();}
    async callServerTool(call:ServerCall){
      calls.push(call);
      return await request(call);
    }
  }
  let instance:AppStub|undefined;
  class CaptureApp extends AppStub {
    constructor(){super();instance=this;}
  }
  const compiled=transformSync(script,{loader:"ts",format:"cjs"}).code;
  runInNewContext(compiled,{
    require(id:string){
      if(id==="@modelcontextprotocol/ext-apps")return {App:CaptureApp};
      throw new Error("unexpected import");
    },
    document:{getElementById:(id:string)=>nodes[id]}
  });
  assert.ok(instance);
  const app=instance as AppStub;
  const project=(mode:"advertised"|"not_advertised"|"unverified")=>({
    structuredContent:{project:{
      id:"22222222-2222-4222-8222-222222222222",
      alias:"Safe temporary board",connectorConnected:true,
      localMcp:{readAttemptReady:true,sessionNativeWriteMode:mode}
    }}
  });
  return {app,nodes,calls,project,setRequest(fn:(call:ServerCall)=>Promise<Snapshot>){request=fn;}};
}

test("PCB editor check is available without native write and checks real read-only IPC",async()=>{
  const h=createReviewHarness();
  h.app.ontoolresult?.(h.project("not_advertised"));
  assert.equal(h.nodes["check-editor"].disabled,false);
  h.setRequest(async()=>({structuredContent:{success:true,local_result:{
    isError:false,structuredContent:{
      kicad:{ipcAvailable:false,livePcbContext:false}
    }
  }}}));
  await h.nodes["check-editor"].click?.();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0]?.name,"local_mcp_read");
  assert.equal(h.calls[0]?.arguments.tool_name,"kicad_get_server_info");
  assert.equal(h.calls[0]?.arguments.project_id,"22222222-2222-4222-8222-222222222222");
  assert.match(h.nodes["editor-status"].textContent,/PCB Editor IPC is unavailable/);
  assert.equal(h.nodes["check-editor"].disabled,false);
  assert.equal(h.calls.some(call=>call.name==="local_mcp_catalog"),false);
});

test("PCB editor verification does not conflate live IPC or read calls with write grants",async()=>{
  const h=createReviewHarness();
  h.app.ontoolresult?.(h.project("advertised"));
  h.setRequest(async(call)=>{
    if(call.name==="local_mcp_read")return {structuredContent:{
      success:true,local_result:{isError:false,
        structuredContent:{kicad:{ipcAvailable:true,livePcbContext:true}}}
    }};
    return {structuredContent:{available:true,tools:[{
      name:"pcb_move_footprint",accessMode:"write"
    }]}};
  });
  await h.nodes["check-editor"].click?.();
  assert.equal(h.calls.length,2);
  assert.equal(h.calls[0]?.name,"local_mcp_read");
  assert.equal(h.calls[1]?.name,"local_mcp_catalog");
  assert.equal(h.calls[1]?.arguments.tool_name,"pcb_move_footprint");
  assert.match(h.nodes["editor-status"].textContent,/does not authorize editing/);
  assert.match(h.nodes["editor-status"].textContent,/Edit permissions in Devices|does not authorize editing/);
  h.setRequest(async(call)=>call.name==="local_mcp_read"
    ?{structuredContent:{success:true,local_result:{isError:false,
      structuredContent:{kicad:{ipcAvailable:true,livePcbContext:true}}}}}
    :{structuredContent:{available:true,tools:[]}}
  );
  await h.nodes["check-editor"].click?.();
  assert.match(h.nodes["editor-status"].textContent,/PCB move tool is not listed/);
  h.app.ontoolresult?.(h.project("not_advertised"));
  await h.nodes["check-editor"].click?.();
  assert.match(h.nodes["editor-status"].textContent,/native editing is not enabled/);
  assert.match(h.nodes["editor-status"].textContent,/Edit permissions in Devices|does not authorize editing/);
  assert.equal(h.calls.filter(call=>call.name==="local_mcp_catalog").length,2);
  h.setRequest(async()=>{throw Error("secret/private-path");});
  await h.nodes["check-editor"].click?.();
  assert.match(h.nodes["editor-status"].textContent,/Could not verify PCB Editor/);
  assert.doesNotMatch(h.nodes["editor-status"].textContent,/secret/);
});

test("a refused or malformed local engine reply does not claim KiCad readiness",async()=>{
  const h=createReviewHarness();
  h.app.ontoolresult?.(h.project("advertised"));
  for(const result of [
    {structuredContent:{success:false,local_result:{}}},
    {structuredContent:{success:true,local_result:{isError:true,
      structuredContent:{kicad:{ipcAvailable:true,livePcbContext:true}}}}},
    {structuredContent:{success:true,local_result:{structuredContent:{kicad:{
      ipcAvailable:"yes",livePcbContext:true
    }}}}}
  ]){
    h.setRequest(async()=>result);
    await h.nodes["check-editor"].click?.();
    assert.match(h.nodes["editor-status"].textContent,/Could not verify PCB Editor/);
  }
  assert.equal(h.calls.every(call=>call.name==="local_mcp_read"),true);
  h.setRequest(async()=>({structuredContent:{
    success:true,local_result:{isError:true,structuredContent:{
      success:false,reason:"local_mcp_read_timeout",
      diagnostics:"PRIVATE_PATH_DO_NOT_RENDER"
    }}
  }}));
  await h.nodes["check-editor"].click?.();
  assert.match(h.nodes["editor-status"].textContent,/KiCad status check timed out/);
  assert.match(h.nodes["editor-status"].textContent,/retry/);
  assert.doesNotMatch(h.nodes["editor-status"].textContent,/PRIVATE_PATH|re-pair your device/);
});

test("a revoked project invalidates in-flight PCB editor tool discovery",async()=>{
  const h=createReviewHarness();
  h.app.ontoolresult?.(h.project("advertised"));
  let finish:(value:Snapshot)=>void=()=>{throw Error("missing resolver");};
  h.setRequest(()=>new Promise<Snapshot>(resolve=>{finish=resolve;}));
  const pending=h.nodes["check-editor"].click?.();
  assert.equal(h.nodes["check-editor"].disabled,true);
  h.app.ontoolresult?.({structuredContent:{}});
  finish({structuredContent:{success:true,local_result:{isError:false,
    structuredContent:{kicad:{ipcAvailable:true,livePcbContext:true}}}}});
  await pending;
  assert.equal(h.nodes["editor-status"].hidden,true);
  assert.equal(h.nodes["check-editor"].disabled,true);
  assert.match(h.nodes["status"].textContent,/Project unavailable/);
});
