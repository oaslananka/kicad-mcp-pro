import test from "node:test";
import assert from "node:assert/strict";
import {createCloudMcpHandler, type GenericMcpTool} from "../src/mcp.js";
import {CLOUD_DIRECT_TOOLS} from "../src/cloud-direct-tool-contracts.generated.js";
import type {Inventory,Project} from "../src/store.js";
import type {Actor} from "../src/auth.js";

const projectId="22222222-2222-4222-8222-222222222222";
const deviceId="11111111-1111-4111-8111-111111111111";

function setup(edit:boolean, permitted:boolean, stale=false, grantEdit=edit){
  let calls=0;
  let writeCalls=0;
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
      if(!permitted||id!==projectId)return null;
      return {id:projectId,deviceId,alias:"Disposable board",
        enabled:true,maxMode:grantEdit?"write":"readonly",
        available:false,reason:"cloud_read_not_enabled"};
    },
    async isAccessTokenAllowed(){return true;}
  };
  const localCatalog=async(_dev:string,_proj:string,_offset:number,name?:string)=>{
    const specs=CLOUD_DIRECT_TOOLS.filter(spec=>spec.name===name||name===undefined)
      .map(spec=>({name:spec.name,description:spec.description,
        inputSchema:stale?{type:"object",properties:{new_required:{type:"number"}}}:
          spec.inputSchema as unknown as Record<string,unknown>,
        accessMode:spec.accessMode as "readonly"|"write"}));
    return {tools:specs as GenericMcpTool[],nextOffset:null};
  };
  const localCall=async(_dev:string,_proj:string,name:string,args:Record<string,unknown>,
    write:boolean)=>{
    calls++;
    if(write)writeCalls++;
    assert.equal("project_id" in args,false);
    return {isError:false,structuredContent:{success:true,name,args}};
  };
  const handler=createCloudMcpHandler(
    inventory,actor,undefined,undefined,undefined,undefined,undefined,
    undefined,undefined,undefined,undefined,localCatalog,localCall,true);
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

test("direct tools expose approved stable independent schemas, not generic dispatch",async()=>{
  const t=setup(false,true);
  try{
    const response=await t.invoke("tools/list");
    assert.equal(response.status,200);
    const tools=response.data.result.tools as Array<{
      name:string;inputSchema:{properties:Record<string,unknown>;required?:string[]};
      annotations:{readOnlyHint:boolean};_meta:{securitySchemes:Array<{scopes:string[]}>};
    }>;
    assert.ok(tools.some(tool=>tool.name==="kicad_get_version"));
    assert.ok(tools.some(tool=>tool.name==="sch_add_symbol"));
    assert.ok(tools.some(tool=>tool.name==="pcb_save"));
    assert.ok(!tools.some(tool=>tool.name==="local_mcp_call"));
    const selected=tools.find(tool=>tool.name==="sch_add_symbol")!;
    assert.equal(selected.annotations.readOnlyHint,false);
    assert.ok("project_id" in selected.inputSchema.properties);
    assert.ok(selected.inputSchema.required?.includes("library"));
    assert.deepEqual(selected._meta.securitySchemes,[{
      type:"oauth2",scopes:["projects:read","projects:write"]
    }]);
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
    const bad=await editor.invoke("tools/call",{name:"sch_add_symbol",arguments:{
      project_id:projectId,reference:"R1"
    }},5);
    assert.equal(bad.data.result.isError,true);
    assert.equal(editor.writes,1);
  }finally{await editor.handler.close();}
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
