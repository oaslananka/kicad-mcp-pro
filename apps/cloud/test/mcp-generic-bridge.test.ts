import test from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync} from "node:crypto";
import {request as httpRequest} from "node:http";
import type {AddressInfo} from "node:net";
import {createHttpServer} from "../src/http.js";
import {createSignedGenericMcpProposal} from "../src/connector-generic-mcp-proof.js";
import {CLOUD_DIRECT_TOOLS} from "../src/cloud-direct-tool-contracts.generated.js";
import type {Config} from "../src/config.js";
import type {Inventory,Project} from "../src/store.js";
import type {Actor,Verifier} from "../src/auth.js";

const config:Config={
  port:0,host:"127.0.0.1",publicOrigin:"http://127.0.0.1",
  issuer:"https://issuer.example",jwksUrl:"https://issuer.example/keys",
  audience:"http://127.0.0.1/mcp",databaseUrl:"postgres://mock",
  allowedOrigins:[],managementClientId:"portal-client"
};
const deviceId="11111111-1111-4111-8111-111111111111";
const projectId="22222222-2222-4222-8222-222222222222";
const sessionId="33333333-3333-4333-8333-333333333333";
const connectionBinding="A".repeat(43);
const key=generateKeyPairSync("ed25519");
const tokenActors:Record<string,Actor>={
  "token-read":{sub:"user",clientId:"client",scopes:new Set(["projects:read"]),
    issuedAt:Math.floor(Date.now()/1000)},
  "token-edit":{sub:"user",clientId:"client",scopes:new Set(["projects:read","projects:write"]),
    issuedAt:Math.floor(Date.now()/1000)}
};

test("generic and direct Cloud MCP routes share the signed local write boundary",async()=>{
  let clientMode:"readonly"|"write"="readonly";
  let writePolicy=true;
  let remoteCalls=0;
  let localWrites=0;
  let wrongTarget=false;
  const inventory:Inventory={
    async listDevices(){return [];},
    async listProjects(sub,client){return sub==="user"&&client==="client"?[await this.getProject(sub,client,projectId)].filter(
      (p):p is Project=>p!==null):[];},
    async getProject(sub,client,id){
      if(sub!=="user"||client!=="client"||id!==projectId||wrongTarget)return null;
      return {id:projectId,deviceId,alias:"Temporary test board",enabled:true,
        maxMode:clientMode,available:false,reason:"cloud_read_not_enabled"};
    },
    async isAccessTokenAllowed(){return true;}
  };
  const verify:Verifier=async token=>{if(!(token in tokenActors))throw Error("invalid_token");return tokenActors[token]!;};
  const relay={
    prepareOwnerSummary:()=>null,requestSummary:async()=>null,
    isDeviceConnected:()=>true,
    getTrustedContext:()=>({deviceId,sessionId,connectionBinding}),
    async requestMcp(_oauth:unknown,devId:string,projId:string,request:{
      requestId:string;method:string;toolName?:string;argumentsJson?:string;proof?:object;
    }){
      assert.equal(devId,deviceId);assert.equal(projId,projectId);
      if(request.method==="catalog"){
        const tools=CLOUD_DIRECT_TOOLS.filter(tool=>
          tool.name==="kicad_get_version"||tool.name==="sch_move_symbol")
          .map(tool=>({name:tool.name,description:tool.description,
            inputSchema:tool.inputSchema as unknown as Record<string,unknown>,
            accessMode:tool.accessMode as "readonly"|"write"}));
        return {kind:"connector.mcp_result" as const,version:1 as const,
          requestId:request.requestId,projectId,method:"catalog" as const,
          ok:true,tools:request.toolName?tools.filter(t=>t.name===request.toolName):tools,
          nextOffset:null};
      }
      remoteCalls++;
      if(request.toolName==="sch_move_symbol"){
        localWrites++;
        assert.ok(request.proof);
        const payload=JSON.parse(Buffer.from((request.proof as {payload:string}).payload,"base64url").toString());
        assert.equal(payload.toolName,"sch_move_symbol");
      }else{
        assert.equal(request.proof,undefined);
      }
      return {kind:"connector.mcp_result" as const,version:1 as const,
        requestId:request.requestId,projectId,method:"call" as const,
        ok:true,result:{content:[{type:"text",text:"native-evidence"}],isError:false}};
    }
  };
  const issuer=(candidate:unknown,binding:any,nowMs:number)=>
    createSignedGenericMcpProposal(candidate,binding,nowMs,key.privateKey);
  const preflight={
    checkCurrentPolicy:async()=>writePolicy,
    reserveAuthorizedWrite:async()=>writePolicy
  };
  const disabled=createHttpServer(config,inventory,verify,{summaryRelay:()=>relay as never});
  const enabled=createHttpServer(config,inventory,verify,{
    summaryRelay:()=>relay as never,mcpGenericBridgeEnabled:true,
    writeIssuer:issuer,writePreflight:preflight as never
  });
  const direct=createHttpServer(config,inventory,verify,{
    summaryRelay:()=>relay as never,mcpGenericBridgeEnabled:true,
    mcpDirectToolPilotEnabled:true,writeIssuer:issuer,writePreflight:preflight as never
  });
  const invoke=async(server:typeof enabled,token:string,method:string,
    params:Record<string,unknown>={},id=1,name?:string)=>{
    const port=(server.address() as AddressInfo).port;
    const payload=JSON.stringify({jsonrpc:"2.0",id,method,params:{...params,_meta:{
      "io.modelcontextprotocol/clientInfo":{name:"test-client",version:"1.0.0"},
      "io.modelcontextprotocol/protocolVersion":"2026-07-28",
      "io.modelcontextprotocol/clientCapabilities":{}
    }}});
    // Only the loopback host and ephemeral port of this test-owned server.
    // No external or user-provided URL is accepted by the HTTP test client.
    const response=await new Promise<{status:number;body:string}>((resolve,reject)=>{
      const req=httpRequest({
        hostname:"127.0.0.1",port,path:"/mcp",method:"POST",
        headers:{Authorization:"Bearer "+token,
          "Content-Type":"application/json",Accept:"application/json, text/event-stream",
          "MCP-Protocol-Version":"2026-07-28","Mcp-Method":method,
          ...(name?{"Mcp-Name":name}:{})}
      },res=>{
        let body="";
        res.setEncoding("utf8");
        res.on("data",chunk=>{body+=chunk;});
        res.on("end",()=>resolve({status:res.statusCode??0,body}));
        res.on("error",reject);
      });
      req.on("error",reject);
      req.end(payload);
    });
    const line=response.body.split("\n").find(l=>l.startsWith("data: "));
    return {status:response.status,data:JSON.parse(line?line.slice(6):response.body)};
  };
  try{
    await new Promise<void>(resolve=>disabled.listen(0,"127.0.0.1",resolve));
    await new Promise<void>(resolve=>enabled.listen(0,"127.0.0.1",resolve));
    await new Promise<void>(resolve=>direct.listen(0,"127.0.0.1",resolve));
    const off=await invoke(disabled,"token-read","tools/list");
    assert.doesNotMatch(JSON.stringify(off.data),/local_mcp_call/);
    const on=await invoke(enabled,"token-read","tools/list");
    assert.match(JSON.stringify(on.data),/local_mcp_call/);
    const list=(on.data.result?.tools??[]) as Array<{name:string;_meta?:{securitySchemes?:unknown}}>;
    const dynamicCall=list.find(t=>t.name==="local_mcp_call");
    assert.deepEqual(dynamicCall?._meta?.securitySchemes,[
      {type:"oauth2",scopes:["projects:read"]},
      {type:"oauth2",scopes:["projects:read","projects:write"]}
    ]);

    const independent=await invoke(direct,"token-read","tools/list");
    const names=(independent.data.result?.tools??[]).map((t:{name:string})=>t.name);
    assert.ok(names.includes("kicad_get_version"));
    assert.ok(names.includes("sch_move_symbol"));
    assert.ok(names.includes("pcb_save"));
    assert.ok(!names.includes("sch_add_symbol"));
    assert.ok(!names.includes("local_mcp_call"));

    const listing=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_catalog",arguments:{project_id:projectId,offset:0}
    },2,"local_mcp_catalog");
    assert.equal(listing.data.result?.structuredContent?.tools.length,1);
    assert.equal(listing.data.result?.structuredContent?.tools[0].name,"kicad_get_version");

    const read=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },3,"local_mcp_call");
    assert.match(JSON.stringify(read.data),/native-evidence/);
    assert.equal(remoteCalls,1);

    const noScope=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },4,"local_mcp_call");
    assert.match(JSON.stringify(noScope.data),/insufficient_scope_write_required/);
    assert.equal(localWrites,0);

    const noGrant=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },5,"local_mcp_call");
    assert.match(JSON.stringify(noGrant.data),/project_edit_permission_required/);
    assert.equal(localWrites,0);

    const directNoScope=await invoke(direct,"token-read","tools/call",{
      name:"sch_move_symbol",arguments:{project_id:projectId,
        reference:"R1",x_mm:10,y_mm:20}
    },6,"sch_move_symbol");
    assert.match(JSON.stringify(directNoScope.data),/insufficient_scope_write_required/);
    assert.equal(localWrites,0);

    const directNoGrant=await invoke(direct,"token-edit","tools/call",{
      name:"sch_move_symbol",arguments:{project_id:projectId,
        reference:"R1",x_mm:10,y_mm:20}
    },7,"sch_move_symbol");
    assert.match(JSON.stringify(directNoGrant.data),/project_edit_permission_required/);
    assert.equal(localWrites,0);

    clientMode="write";
    const directGood=await invoke(direct,"token-edit","tools/call",{
      name:"sch_move_symbol",arguments:{project_id:projectId,
        reference:"R1",x_mm:10,y_mm:20}
    },8,"sch_move_symbol");
    assert.match(JSON.stringify(directGood.data),/native-evidence/);
    assert.equal(localWrites,1);
    assert.equal(remoteCalls,2);

    const good=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },9,"local_mcp_call");
    assert.match(JSON.stringify(good.data),/native-evidence/);
    assert.equal(localWrites,2);

    writePolicy=false;
    const revoked=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },10,"local_mcp_call");
    assert.match(JSON.stringify(revoked.data),/local_mcp_operation_unconfirmed/);
    assert.equal(localWrites,2);
    wrongTarget=true;
    const other=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_call",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },11,"local_mcp_call");
    assert.equal(other.data.result?.isError,true);
  }finally{
    for(const server of [disabled,enabled,direct])await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});
