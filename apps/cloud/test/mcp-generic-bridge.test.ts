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
import type {ConnectorCapabilityClaim} from "../src/connector-capability-claim.js";

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
  let mismatchedRelayReply:"request"|"project"|null=null;
  let mismatchedCatalogReply:"request"|"project"|null=null;
  let deviceOnline=true;
  let catalogResponds=true;
  let catalogAttempts=0;
  let transientCatalogFailures=0;
  let onTransientCatalogFailure:(()=>void)|null=null;
  let signedRelaySerialOnly=false;
  let signedRelayBusy=false;
  let signalCatalogInFlight:(()=>void)|null=null;
  let signedClaim:ConnectorCapabilityClaim|null=null;
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
    isDeviceConnected:()=>deviceOnline,
    getDeviceCapabilityClaim:()=>signedClaim,
    getTrustedContext:()=>({deviceId,sessionId,connectionBinding}),
    async requestMcp(_oauth:unknown,devId:string,projId:string,request:{
      requestId:string;method:string;toolName?:string;argumentsJson?:string;proof?:object;
    }){
      assert.equal(devId,deviceId);assert.equal(projId,projectId);
      // Model the actual Connector: concurrent native RPCs are rejected.
      if(signedRelaySerialOnly&&signedRelayBusy)return null;
      if(signedRelaySerialOnly)signedRelayBusy=true;
      try{
        if(signedRelaySerialOnly&&request.method==="catalog"){
          signalCatalogInFlight?.();
          signalCatalogInFlight=null;
        }
        if(signedRelaySerialOnly)await new Promise<void>(resolve=>setTimeout(resolve,60));
      if(request.method==="catalog"){
        catalogAttempts++;
        if(transientCatalogFailures>0){
          transientCatalogFailures--;
          onTransientCatalogFailure?.();
          onTransientCatalogFailure=null;
          return null;
        }
        if(!catalogResponds)return null;
        const tools:Array<{name:string;description:string;inputSchema:Record<string,unknown>;accessMode:"readonly"|"write"}>=CLOUD_DIRECT_TOOLS.filter(tool=>
          tool.name==="kicad_get_version"||tool.name==="sch_move_symbol")
          .map(tool=>({name:tool.name,description:tool.description,
            inputSchema:tool.inputSchema as unknown as Record<string,unknown>,
            accessMode:tool.accessMode as "readonly"|"write"}));
        if(request.toolName==="kicad_get_server_info")
          tools.push({name:"kicad_get_server_info",
            description:"Read bounded KiCad editor status",
            inputSchema:{type:"object",properties:{}},accessMode:"readonly"});
        return {kind:"connector.mcp_result" as const,version:1 as const,
          requestId:mismatchedCatalogReply==="request"
            ?"99999999-9999-4999-8999-999999999999":request.requestId,
          projectId:mismatchedCatalogReply==="project"
            ?"88888888-8888-4888-8888-888888888888":projectId,
          method:"catalog" as const,
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
        requestId:mismatchedRelayReply==="request"
          ?"99999999-9999-4999-8999-999999999999":request.requestId,
        projectId:mismatchedRelayReply==="project"
          ?"88888888-8888-4888-8888-888888888888":projectId,
        method:"call" as const,
        ok:true,result:request.toolName==="kicad_get_server_info"
          ?{content:[{type:"text",text:"private-native-evidence"}],isError:false,
            structuredContent:{kicad:{ipcAvailable:true,livePcbContext:true,
              cliPath:"never-export-this-path"}}}
          :{content:[{type:"text",text:"native-evidence"}],isError:false}};
      }finally{
        if(signedRelaySerialOnly)signedRelayBusy=false;
      }
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
    mcpProjectPresenceEnabled:true,
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
    assert.ok(!(off.data.result?.tools??[]).some((tool:{name:string})=>
      tool.name==="local_mcp_call"),"disabled bridge must not register an executable tool");
    const on=await invoke(enabled,"token-read","tools/list");
    assert.deepEqual((on.data.result?.tools??[]).map((tool:{name:string})=>tool.name).sort(),
      ["get_project_editor_status","list_projects","local_mcp_catalog","local_mcp_read","local_mcp_write"],
      "Production Cloud should expose only project discovery and the real local tool gateway");
    assert.match(JSON.stringify(on.data),/local_mcp_read/);
    assert.doesNotMatch(JSON.stringify(on.data),/local_mcp_call/,
      "Modern Cloud tool inventory must not mention the superseded command");
    const list=(on.data.result?.tools??[]) as Array<{name:string;_meta?:{securitySchemes?:unknown;ui?:{visibility?:string[]};"openai/widgetAccessible"?:boolean}}>;
    const readEndpoint=list.find(t=>t.name==="local_mcp_read");
    const writeEndpoint=list.find(t=>t.name==="local_mcp_write");
    const widgetEndpoint=list.find(t=>t.name==="get_project_editor_status");
    assert.deepEqual(widgetEndpoint?._meta?.ui?.visibility,["app"]);
    assert.equal(widgetEndpoint?._meta?.["openai/widgetAccessible"],true);
    assert.deepEqual(widgetEndpoint?._meta?.securitySchemes,
      [{type:"oauth2",scopes:["projects:read"]}]);
    assert.notEqual(writeEndpoint?._meta?.["openai/widgetAccessible"],true);
    assert.notEqual(readEndpoint?._meta?.["openai/widgetAccessible"],true);
    assert.deepEqual(readEndpoint?._meta?.securitySchemes,
      [{type:"oauth2",scopes:["projects:read"]}]);
    assert.deepEqual(writeEndpoint?._meta?.securitySchemes,
      [{type:"oauth2",scopes:["projects:read","projects:write"]}]);

    const independent=await invoke(direct,"token-read","tools/list");
    const names=(independent.data.result?.tools??[]).map((t:{name:string})=>t.name);
    assert.ok(names.includes("kicad_get_version"));
    assert.ok(names.includes("sch_move_symbol"));
    assert.ok(names.includes("pcb_save"));
    assert.ok(!names.includes("sch_add_symbol"));
    assert.ok(!names.includes("local_mcp_read")&&!names.includes("local_mcp_write"));

    // MCP relay readiness is distinct from legacy read availability. A
    // connected device alone cannot prove that a local KiCad operation works.
    const inventoryDisabled=await invoke(disabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },20,"list_projects");
    const projectDisabled=inventoryDisabled.data.result?.structuredContent?.projects[0];
    assert.equal(projectDisabled.available,false);
    assert.deepEqual(projectDisabled.localMcp,{
      bridgeConfigured:false,readAttemptReady:false,
      state:"not_configured",nativeWriteAuthorization:"unverified",sessionNativeWriteMode:"unverified"
    });
    const inventoryEnabled=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },21,"list_projects");
    const projectEnabled=inventoryEnabled.data.result?.structuredContent?.projects[0];
    assert.equal(projectEnabled.available,false,"Do not broaden legacy operation contract");
    assert.equal(projectEnabled.reason,"owner_operation_required");
    assert.deepEqual(projectEnabled.localMcp,{
      bridgeConfigured:true,readAttemptReady:true,
      state:"signed_session_connected",nativeWriteAuthorization:"unverified",sessionNativeWriteMode:"unverified"
    });
    assert.match(projectEnabled.guidance??"",/local_mcp_catalog/);
    deviceOnline=false;
    const disconnected=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },23,"list_projects");
    assert.deepEqual(disconnected.data.result?.structuredContent?.projects[0]?.localMcp,{
      bridgeConfigured:true,readAttemptReady:false,
      state:"device_not_connected",nativeWriteAuthorization:"unverified",sessionNativeWriteMode:"unverified"
    });
    deviceOnline=true;
    // A signed claim can narrow (not grant) advertised local MCP support.
    signedClaim={
      schemaVersion:"1.0.0",catalogRevision:"a".repeat(64),
      operations:["project_summary","mcp_bridge"]
    };
    const readonlyClaim=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },24,"list_projects");
    const readonlyLocal=readonlyClaim.data.result?.structuredContent?.projects[0]?.localMcp;
    assert.equal(readonlyLocal.readAttemptReady,true);
    assert.equal(readonlyLocal.sessionNativeWriteMode,"not_advertised");
    assert.equal(readonlyLocal.nativeWriteAuthorization,"unverified");
    signedClaim={...signedClaim,operations:["project_summary","mcp_bridge","move_footprint"]};
    const writeModeClaim=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },25,"list_projects");
    const writeLocal=writeModeClaim.data.result?.structuredContent?.projects[0]?.localMcp;
    assert.equal(writeLocal.sessionNativeWriteMode,"advertised");
    assert.equal(writeLocal.nativeWriteAuthorization,"unverified");
    signedClaim={...signedClaim,operations:["project_summary"]};
    const noMcpClaim=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },26,"list_projects");
    const unavailableLocal=noMcpClaim.data.result?.structuredContent?.projects[0]?.localMcp;
    assert.equal(unavailableLocal.readAttemptReady,false);
    assert.equal(unavailableLocal.state,"connector_mcp_unavailable");
    signedClaim=null;

    const listing=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_catalog",arguments:{project_id:projectId,offset:0}
    },2,"local_mcp_catalog");
    assert.equal(listing.data.result?.structuredContent?.tools.length,1);
    assert.equal(listing.data.result?.structuredContent?.tools[0].name,"kicad_get_version");

    const read=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },3,"local_mcp_read");
    assert.match(JSON.stringify(read.data),/native-evidence/);
    assert.equal(remoteCalls,1);

    // A scheduled signed session refresh can cause one or two catalog
    // attempts to return null BEFORE the native READ dispatch. Retry only
    // safe discovery, never the native action or a WRITE call.
    let catalogsBefore=catalogAttempts;
    transientCatalogFailures=2;
    const renewed=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },53,"local_mcp_read");
    assert.equal(renewed.data.result?.structuredContent?.success,true);
    assert.equal(catalogAttempts-catalogsBefore,3);
    assert.equal(remoteCalls,2);

    catalogsBefore=catalogAttempts;
    transientCatalogFailures=1;
    const directRenewed=await invoke(direct,"token-read","tools/call",{
      name:"kicad_get_version",arguments:{project_id:projectId}
    },54,"kicad_get_version");
    assert.equal(directRenewed.data.result?.structuredContent?.success,true);
    assert.equal(catalogAttempts-catalogsBefore,2);
    assert.equal(remoteCalls,3);

    // Discovery by itself must also recover after a signed session rotation.
    catalogsBefore=catalogAttempts;
    transientCatalogFailures=1;
    const renewedCatalog=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_catalog",arguments:{project_id:projectId}
    },57,"local_mcp_catalog");
    assert.equal(renewedCatalog.data.result?.structuredContent?.available,true);
    assert.equal(catalogAttempts-catalogsBefore,2);

    // A revoked grant while waiting for a renewed signed catalog must not
    // dispatch local READ even if the new relay happens to answer.
    catalogsBefore=catalogAttempts;
    transientCatalogFailures=1;
    onTransientCatalogFailure=()=>{wrongTarget=true;};
    const revokedDuringRefresh=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },55,"local_mcp_read");
    assert.equal(revokedDuringRefresh.data.result?.structuredContent?.reason,"project_not_granted");
    assert.equal(remoteCalls,3);
    wrongTarget=false;

    // WRITE discovery is never automatically retried, including under
    // a signed session refresh.
    clientMode="write";
    catalogsBefore=catalogAttempts;
    transientCatalogFailures=1;
    const writeDuringRefresh=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_write",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },56,"local_mcp_write");
    assert.equal(writeDuringRefresh.data.result?.structuredContent?.reason,"owner_connector_mcp_unavailable");
    assert.equal(catalogAttempts-catalogsBefore,1);
    assert.equal(remoteCalls,3);
    clientMode="readonly";

    // A busy, refreshing, or otherwise unavailable signed relay is not an
    // authoritative empty local catalog. No native call must be dispatched.
    catalogResponds=false;
    const unavailable=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },35,"local_mcp_read");
    assert.equal(unavailable.data.result?.isError,true);
    assert.equal(unavailable.data.result?.structuredContent?.reason,"owner_connector_mcp_unavailable");
    assert.match(unavailable.data.result?.structuredContent?.guidance??"",/one at a time/);
    assert.equal(remoteCalls,3);
    catalogResponds=true;
    const missing=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"nonexistent_local_tool",arguments:{}}
    },36,"local_mcp_read");
    assert.equal(missing.data.result?.isError,true);
    assert.equal(missing.data.result?.structuredContent?.reason,"local_tool_unavailable");
    assert.equal(remoteCalls,3);

    const wrongMode=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },34,"local_mcp_read");
    assert.match(JSON.stringify(wrongMode.data),/write_tool_requires_local_mcp_write/);
    assert.equal(localWrites,0);

    catalogsBefore=catalogAttempts;
    const noScope=await invoke(enabled,"token-read","tools/call",{
      name:"local_mcp_write",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },4,"local_mcp_write");
    assert.match(JSON.stringify(noScope.data),/insufficient_scope_write_required/);
    assert.equal(catalogAttempts,catalogsBefore,"Denied WRITE must not query local catalog");
    assert.equal(localWrites,0);

    const noGrant=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_write",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },5,"local_mcp_write");
    assert.match(JSON.stringify(noGrant.data),/project_edit_permission_required/);
    assert.equal(catalogAttempts,catalogsBefore,"Read grant must not query local WRITE catalog");
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
    assert.equal(remoteCalls,4);

    const good=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_write",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },9,"local_mcp_write");
    assert.match(JSON.stringify(good.data),/native-evidence/);
    assert.equal(localWrites,2);

    writePolicy=false;
    const revoked=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_write",arguments:{project_id:projectId,
        tool_name:"sch_move_symbol",arguments:{reference:"R1",x_mm:10,y_mm:20}}
    },10,"local_mcp_write");
    assert.match(JSON.stringify(revoked.data),/local_mcp_operation_unconfirmed/);
    assert.equal(localWrites,2);
    // Simultaneous read requests must serialize the complete signed
    // catalog -> native call sequence, never just individual RPCs.
    signedRelaySerialOnly=true;
    const overlappingReads=await Promise.all([
      invoke(enabled,"token-read","tools/call",{
        name:"local_mcp_read",arguments:{project_id:projectId,
          tool_name:"kicad_get_version",arguments:{}}
      },41,"local_mcp_read"),
      invoke(enabled,"token-read","tools/call",{
        name:"local_mcp_read",arguments:{project_id:projectId,
          tool_name:"kicad_get_version",arguments:{}}
      },42,"local_mcp_read")
    ]);
    assert.equal(overlappingReads[0].data.result?.structuredContent?.success,true);
    assert.equal(overlappingReads[1].data.result?.structuredContent?.success,true);

    // Independently advertised Cloud READ tools use the same per-device lane.
    const directReads=await Promise.all([
      invoke(direct,"token-read","tools/call",{
        name:"kicad_get_version",arguments:{project_id:projectId}
      },43,"kicad_get_version"),
      invoke(direct,"token-read","tools/call",{
        name:"kicad_get_version",arguments:{project_id:projectId}
      },44,"kicad_get_version")
    ]);
    assert.equal(directReads[0].data.result?.structuredContent?.success,true);
    assert.equal(directReads[1].data.result?.structuredContent?.success,true);

    // Discovery and execution share the lane, preventing a discovery race.
    const [discovery,execution]=await Promise.all([
      invoke(enabled,"token-read","tools/call",{
        name:"local_mcp_catalog",arguments:{project_id:projectId}
      },45,"local_mcp_catalog"),
      invoke(enabled,"token-read","tools/call",{
        name:"local_mcp_read",arguments:{project_id:projectId,
          tool_name:"kicad_get_version",arguments:{}}
      },46,"local_mcp_read")
    ]);
    assert.equal(discovery.data.result?.structuredContent?.available,true);
    assert.equal(execution.data.result?.structuredContent?.success,true);

    // An Edit grant downgraded while a queued catalog is waiting may no
    // longer disclose write tool contracts when the response is returned.
    clientMode="write";
    const catalogStarted=new Promise<void>((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error("catalog start timed out")),2_000);
      signalCatalogInFlight=()=>{clearTimeout(timer);resolve();};
    });
    const inFlightCatalog=invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_catalog",arguments:{project_id:projectId}
    },47,"local_mcp_catalog");
    await catalogStarted;
    clientMode="readonly";
    const downgraded=await inFlightCatalog;
    const exposed=downgraded.data.result?.structuredContent?.tools??[];
    assert.ok(exposed.some((tool:{name:string})=>tool.name==="kicad_get_version"));
    assert.ok(!exposed.some((tool:{accessMode:string})=>tool.accessMode==="write"),
      "A stale Edit grant must not reveal write tool contracts");
    clientMode="write";
    signedRelaySerialOnly=false;

    wrongTarget=true;
    const revokedProjects=await invoke(enabled,"token-read","tools/call",{
      name:"list_projects",arguments:{}
    },33,"list_projects");
    assert.deepEqual(revokedProjects.data.result?.structuredContent?.projects,[],
      "Revoked project must not disclose device status");
    const other=await invoke(enabled,"token-edit","tools/call",{
      name:"local_mcp_read",arguments:{project_id:projectId,
        tool_name:"kicad_get_version",arguments:{}}
    },11,"local_mcp_read");
    assert.equal(other.data.result?.isError,true);

    // Widget-exposed probe is a fixed safe READ, not a general native gateway.
    wrongTarget=false;
    clientMode="readonly";
    const callsBeforeEditor=remoteCalls;
    const writesBeforeEditor=localWrites;
    const editor=await invoke(enabled,"token-read","tools/call",{
      name:"get_project_editor_status",arguments:{project_id:projectId}
    },62,"get_project_editor_status");
    assert.deepEqual(editor.data.result?.structuredContent,{
      success:true,local_result:{isError:false,structuredContent:{
        kicad:{ipcAvailable:true,livePcbContext:true}
      }}
    });
    assert.doesNotMatch(JSON.stringify(editor.data),/never-export-this-path|private-native-evidence/);
    assert.equal(remoteCalls,callsBeforeEditor+1);
    assert.equal(localWrites,writesBeforeEditor);
    wrongTarget=true;
    const deniedEditor=await invoke(enabled,"token-read","tools/call",{
      name:"get_project_editor_status",arguments:{project_id:projectId}
    },63,"get_project_editor_status");
    assert.equal(deniedEditor.data.result?.structuredContent?.reason,"project_not_granted");
    assert.equal(remoteCalls,callsBeforeEditor+1);

    // A compromised/stale relay must not deliver a signed WRITE result
    // for a different request or different project, even if ok:true.
    // The WebSocket validates this too; Cloud's HTTP boundary must still
    // enforce it rather than trusting mocked/alternate transport clients.
    wrongTarget=false;
    clientMode="write";
    writePolicy=true;
    for(const mismatch of ["request","project"] as const){
      mismatchedCatalogReply=mismatch;
      const priorWrites:number=localWrites;
      const mismatchedCatalog=await invoke(enabled,"token-edit","tools/call",{
        name:"local_mcp_catalog",arguments:{project_id:projectId}
      },90,"local_mcp_catalog");
      assert.equal(mismatchedCatalog.data.result?.structuredContent?.available,false,
        mismatch+" catalog cannot publish another request or project's tools");
      assert.equal(localWrites,priorWrites,
        "A mismatched catalog must not dispatch native edits");
      mismatchedCatalogReply=null;
      for(const directTool of [false,true]){
        // Isolate the result binding test from the separately checked
        // catalog binding: its catalog lookup must remain properly matched.
        mismatchedRelayReply=null;
        const toolName=directTool?"sch_move_symbol":"local_mcp_write";
        const args=directTool
          ?{project_id:projectId,reference:"R1",x_mm:10,y_mm:20}
          :{project_id:projectId,tool_name:"sch_move_symbol",
            arguments:{reference:"R1",x_mm:10,y_mm:20}};
        mismatchedRelayReply=mismatch;
        const reply=await invoke(
          directTool?direct:enabled,"token-edit","tools/call",
          {name:toolName,arguments:args},80,toolName
        );
        assert.equal(reply.data.result?.isError,true,
          mismatch+" "+toolName+" response must not claim success");
        const status=reply.data.result?.structuredContent;
        assert.equal(status?.reason,"local_mcp_operation_unconfirmed");
        assert.equal(status?.outcomeUnknown,true);
        assert.equal(status?.retrySafe,false);
      }
    }
    mismatchedRelayReply=null;
  }finally{
    for(const server of [disabled,enabled,direct])await new Promise<void>(resolve=>server.close(()=>resolve()));
  }
});
