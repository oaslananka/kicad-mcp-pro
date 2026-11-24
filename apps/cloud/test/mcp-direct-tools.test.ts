import test from "node:test";
import assert from "node:assert/strict";
import {createCloudMcpHandler, type GenericMcpTool} from "../src/mcp.js";
import {CLOUD_DIRECT_TOOLS} from "../src/cloud-direct-tool-contracts.generated.js";
import type {Inventory,Project} from "../src/store.js";
import type {Actor} from "../src/auth.js";

const projectId="22222222-2222-4222-8222-222222222222";
const deviceId="11111111-1111-4111-8111-111111111111";

type PostWriteChange="remove_grant"|"downgrade_grant"|"disable_project"|"change_device"|"revoke_token"|null;
function setup(
  edit:boolean,permitted:boolean,stale=false,grantEdit=edit,unavailable=false,
  postWriteChange:PostWriteChange=null,directTools=true
){
  let calls=0;
  let writeCalls=0;
  let granted=permitted;
  let currentDeviceId=deviceId;
  let currentGrantEdit=grantEdit;
  let projectEnabled=true;
  let tokenAllowed=true;
  const actor:Actor={
    sub:"user",clientId:"client",
    scopes:new Set(edit?["projects:read","projects:write"]:["projects:read"]),
    issuedAt:Math.floor(Date.now()/1000)
  };
  const inventory:Inventory={
    async listDevices(){return [];},
    async listProjects(){return [await this.getProject("user","client",projectId)].filter(
      (p):p is Project=>Boolean(p));},
    async getProject(_sub,_client,id){
      if(!granted||id!==projectId)return null;
      return {id:projectId,deviceId:currentDeviceId,alias:"Disposable board",
        enabled:projectEnabled,maxMode:currentGrantEdit?"write":"readonly",
        available:false,reason:"cloud_read_not_enabled"};
    },
    async isAccessTokenAllowed(){return tokenAllowed;}
  };
  const localCatalog=async(_dev:string,_proj:string,_offset:number,name?:string)=>{
    const specs=(unavailable?[]:CLOUD_DIRECT_TOOLS).filter(spec=>spec.name===name||name===undefined)
      .map(spec=>({name:spec.name,description:spec.description,
        inputSchema:stale?{type:"object",properties:{new_required:{type:"number"}}}:
          spec.inputSchema as unknown as Record<string,unknown>,
        accessMode:spec.accessMode as "readonly"|"write"}));
    return {tools:specs as GenericMcpTool[],nextOffset:null};
  };
  const localCall=async(_dev:string,_proj:string,name:string,args:Record<string,unknown>,
    write:boolean)=>{
    calls++;
    if(write){
      writeCalls++;
      if(postWriteChange==="remove_grant")granted=false;
      if(postWriteChange==="downgrade_grant")currentGrantEdit=false;
      if(postWriteChange==="disable_project")projectEnabled=false;
      if(postWriteChange==="change_device")
        currentDeviceId="44444444-4444-4444-8444-444444444444";
      if(postWriteChange==="revoke_token")tokenAllowed=false;
    }
    assert.equal("project_id" in args,false);
    return {isError:false,structuredContent:{success:true,name,args}};
  };
  const handler=createCloudMcpHandler(
    inventory,actor,undefined,undefined,undefined,undefined,undefined,
    undefined,undefined,undefined,undefined,localCatalog,localCall,directTools);
  const invoke=async(method:string,params:Record<string,unknown>={},id=1)=>{
    const payload={jsonrpc:"2.0",id,method,params:{...params,_meta:{
      "io.modelcontextprotocol/clientInfo":{name:"direct-tools-test",version:"1"},
      "io.modelcontextprotocol/protocolVersion":"2026-07-28",
      "io.modelcontextprotocol/clientCapabilities":{}
    }}};
    const resp=await handler.fetch(new Request("http://localhost/mcp",{
      method:"POST",headers:{
        "Content-Type":"application/json",
        "Accept":"application/json, text/event-stream",
        "MCP-Protocol-Version":"2026-07-28",
        "Mcp-Method":method,
        ...(method==="tools/call"&&typeof params.name==="string"?
          {"Mcp-Name":params.name}:{})
      },
      body:JSON.stringify(payload)
    }));
    const body=await resp.text();
    const dataLine=body.split("\n").find(l=>l.startsWith("data: "));
    return {status:resp.status,data:JSON.parse(dataLine?dataLine.slice(6):body)};
  };
  return {handler,invoke,get calls(){return calls;},get writes(){return writeCalls;}};
}

test("direct tools expose reviewed independent schemas and a versioned contract, not generic dispatch",async()=>{
  const t=setup(false,true);
  try{
    const response=await t.invoke("tools/list");
    assert.equal(response.status,200);
    const tools=response.data.result.tools as Array<{
      name:string;inputSchema:{properties:Record<string,unknown>;required?:string[]};
      annotations:{readOnlyHint:boolean;destructiveHint:boolean};
      _meta:Record<string,unknown>&{securitySchemes:Array<{scopes:string[]}>};
    }>;
    assert.ok(tools.some(tool=>tool.name==="kicad_get_version"));
    assert.ok(tools.some(tool=>tool.name==="sch_move_symbol"));
    assert.ok(tools.some(tool=>tool.name==="pcb_save"));
    assert.ok(!tools.some(tool=>tool.name==="sch_add_symbol"));
    assert.ok(!tools.some(tool=>tool.name==="pcb_add_track"));
    assert.ok(!tools.some(tool=>tool.name==="local_mcp_call"));
    const selected=tools.find(tool=>tool.name==="sch_move_symbol")!;
    assert.equal(selected.annotations.readOnlyHint,false);
    assert.equal(selected.annotations.destructiveHint,true);
    assert.ok("project_id" in selected.inputSchema.properties);
    assert.deepEqual(selected.inputSchema.required,["reference","x_mm","y_mm"]);
    assert.deepEqual(selected._meta.securitySchemes,[{
      type:"oauth2",scopes:["projects:read","projects:write"]
    }]);
    assert.equal(selected._meta["com.kicad-mcp-pro.maturity"],"beta");
    assert.equal(String(selected._meta["com.kicad-mcp-pro.contractRevision"]).length,64);
    const read=await t.invoke("tools/call",{name:"kicad_get_version",arguments:{
      project_id:projectId
    }},2);
    assert.equal(read.data.result.structuredContent.success,true);
    assert.equal(t.calls,1);
  }finally{await t.handler.close();}
});

test("direct write calls respect OAuth, project Edit and original schemas",async()=>{
  const read=setup(false,true);
  try{
    const denied=await read.invoke("tools/call",{name:"pcb_save",arguments:{
      project_id:projectId
    }},3);
    assert.equal(denied.data.result.isError,true);
    assert.match(JSON.stringify(denied.data),/insufficient_scope_write_required/);
    assert.equal(read.writes,0);
  }finally{await read.handler.close();}

  const readOnlyGrant=setup(true,true,false,false);
  try{
    const noGrant=await readOnlyGrant.invoke("tools/call",{name:"pcb_save",arguments:{
      project_id:projectId
    }},4);
    assert.equal(noGrant.data.result.isError,true);
    assert.match(JSON.stringify(noGrant.data),/project_edit_permission_required/);
    assert.equal(readOnlyGrant.writes,0);
  }finally{await readOnlyGrant.handler.close();}

  const editor=setup(true,true);
  try{
    const good=await editor.invoke("tools/call",{name:"pcb_save",arguments:{
      project_id:projectId
    }},4);
    assert.equal(good.data.result.structuredContent.success,true);
    assert.equal(editor.writes,1);
    const moved=await editor.invoke("tools/call",{name:"sch_move_symbol",arguments:{
      project_id:projectId,reference:"R1",x_mm:10,y_mm:20
    }},5);
    assert.equal(moved.data.result.structuredContent.success,true);
    assert.equal(editor.writes,2);
    const bad=await editor.invoke("tools/call",{name:"sch_move_symbol",arguments:{
      project_id:projectId,reference:"R1"
    }},6);
    assert.equal(bad.data.result.isError,true);
    assert.equal(editor.writes,2);
  }finally{await editor.handler.close();}
});

test("direct tools explain when the local Connector does not expose an operation",async()=>{
  const readUnavailable=setup(false,true,false,false,true);
  try{
    const result=await readUnavailable.invoke("tools/call",{name:"kicad_get_version",arguments:{
      project_id:projectId
    }});
    assert.equal(result.data.result.isError,true);
    assert.match(JSON.stringify(result.data),/open the selected project in KiCad/);
    assert.equal(readUnavailable.calls,0);
  }finally{await readUnavailable.handler.close();}

  const writeUnavailable=setup(true,true,false,true,true);
  try{
    const result=await writeUnavailable.invoke("tools/call",{name:"sch_move_symbol",arguments:{
      project_id:projectId,reference:"R1",x_mm:10,y_mm:20
    }});
    assert.equal(result.data.result.isError,true);
    assert.match(JSON.stringify(result.data),/enable signed native write/);
    assert.equal(writeUnavailable.calls,0);
  }finally{await writeUnavailable.handler.close();}
});

test("direct tools never dispatch on missing project or stale local schema",async()=>{
  const missing=setup(true,false);
  try{
    const result=await missing.invoke("tools/call",{name:"kicad_get_version",arguments:{
      project_id:projectId
    }});
    assert.equal(result.data.result.isError,true);
    assert.equal(missing.calls,0);
  }finally{await missing.handler.close();}
  const stale=setup(true,true,true);
  try{
    const result=await stale.invoke("tools/call",{name:"kicad_get_version",arguments:{
      project_id:projectId
    }});
    assert.equal(result.data.result.isError,true);
    assert.match(JSON.stringify(result.data),/local_tool_contract_mismatch/);
    assert.equal(stale.calls,0);
  }finally{await stale.handler.close();}
});

test("revocation during an in-flight signed write never produces client-visible success",async()=>{
  for(const change of [
    "remove_grant","downgrade_grant","disable_project","change_device","revoke_token"
  ] as const){
    for(const direct of [true,false]){
      const label=(direct?"direct ":"generic ")+change;
      const t=setup(true,true,false,true,false,change,direct);
      try{
        const tool=direct?"sch_move_symbol":"local_mcp_write";
        const args=direct
          ?{project_id:projectId,reference:"R1",x_mm:10,y_mm:20}
          :{project_id:projectId,tool_name:"sch_move_symbol",
            arguments:{reference:"R1",x_mm:10,y_mm:20}};
        const reply=await t.invoke("tools/call",{name:tool,arguments:args},117);
        const response=reply.data.result;
        assert.equal(t.writes,1,label+" must exercise actual local write relay");
        assert.equal(response?.isError,true,label+" must not report success after revocation");
        assert.equal(response?.structuredContent?.success,false,label);
        assert.equal(response?.structuredContent?.reason,"local_mcp_operation_unconfirmed",label);
        assert.equal(response?.structuredContent?.outcomeUnknown,true,label);
        assert.equal(response?.structuredContent?.retrySafe,false,label);
      }finally{await t.handler.close();}
    }
  }
});
