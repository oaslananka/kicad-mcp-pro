import { readFileSync } from "node:fs";
import {registerDirectCloudMcpTools} from "./cloud-direct-tool-registry.js";
import {runSerializedCloudRead} from "./cloud-read-queue.js";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import type { Actor } from "./auth.js";
import type { Inventory, Project } from "./store.js";
import type {ConnectorCapabilityClaim} from "./connector-capability-claim.js";
import {
  CLOUD_READ_CAPABILITIES,
  CLOUD_READ_CATEGORIES,
  CLOUD_READ_TASKS,
  configuredReadersForClaim,
  listConfiguredCloudCapabilities
} from "./cloud-capabilities.js";

const text = (value: object) => ({
  content: [{ type: "text" as const, text: JSON.stringify(value) }],
  structuredContent: value
});
const readonly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
// Order-independent comparison of signed local versus reviewed Cloud input schemas.
function stableJson(value:unknown):string{
  if(Array.isArray(value))return "["+value.map(stableJson).join(",")+"]";
  if(value!==null&&typeof value==="object"){
    const object=value as Record<string,unknown>;
    return "{"+Object.keys(object).sort().map(k=>
      JSON.stringify(k)+":"+stableJson(object[k])).join(",")+"}";
  }
  return JSON.stringify(value)??"null";
}


export type ProjectPresenceFiles = Readonly<{
  projectPresent:boolean;boardPresent:boolean;schematicPresent:boolean;
}>;
export type ProjectPresenceReader =
  (deviceId:string,projectId:string)=>Promise<ProjectPresenceFiles|null>;
export type DrcCounts=Readonly<{violations:number;unconnectedItems:number}>;
export type ProjectDrcReader =
  (deviceId:string,projectId:string)=>Promise<DrcCounts|null>;
export type ProjectInspectionStatus=Readonly<{
  engineVersion:string;cliAvailable:boolean;ipcAvailable:boolean;
  capabilities:Readonly<{
    fileBackedDrc:boolean;fileBackedErc:boolean;
    livePcbRead:boolean;liveSchematicRead:boolean;
  }>;
}>;
export type ProjectInspectionReader=
  (deviceId:string,projectId:string)=>Promise<ProjectInspectionStatus|null>;
export type ProjectBoardCounts=Readonly<{
  source:"live-gui"|"file-backed";
  tracks:number;vias:number;footprints:number;zones:number;nets:number;shapes:number;
}>;
export type ProjectBoardCountsReader=
  (deviceId:string,projectId:string)=>Promise<ProjectBoardCounts|null>;
export type ProjectSchematicCounts=Readonly<{
  components:number;populated:number;dnp:number;inBom:number;
}>;
export type ProjectSchematicCountsReader=
  (deviceId:string,projectId:string)=>Promise<ProjectSchematicCounts|null>;
export type ProjectWriteResult = Readonly<{
  success: boolean;
  operation: "pcb_move_footprint";
  nativeCommitted: boolean;
  savedToDisk: boolean;
  diskBoardSha256?: string;
  message?: string;
}>;
export type ProjectWriteExecutor = (
  deviceId: string,
  projectId: string,
  command: {
    reference: string;
    xMm: number;
    yMm: number;
    rotationDeg?: number | null;
    saveToDisk?: boolean;
  }
) => Promise<ProjectWriteResult | null>;

export type GenericMcpTool=Readonly<{
  name:string;description:string;inputSchema:Record<string,unknown>;
  accessMode:"readonly"|"write";
}>;
export type GenericMcpCatalog=Readonly<{
  tools:GenericMcpTool[];nextOffset:number|null;
}>;
export type GenericMcpCatalogReader=(
  deviceId:string,projectId:string,offset:number,toolName?:string
)=>Promise<GenericMcpCatalog|null>;
export type GenericMcpCaller=(
  deviceId:string,projectId:string,toolName:string,
  args:Record<string,unknown>,writeRequired:boolean
)=>Promise<unknown|null>;

// The local device owns the actual project. This Cloud lookup only resolves
// an already granted opaque project ID for the current OAuth client. A lone
// project can be selected implicitly; multiple projects require an explicit ID.
async function resolveScopedProject(
  inventory: Inventory, actor: Actor, projectId: string | undefined
): Promise<{project: Project | null; selectionRequired: boolean}> {
  if (projectId !== undefined) {
    return {project: await inventory.getProject(actor.sub, actor.clientId, projectId), selectionRequired: false};
  }
  const projects = await inventory.listProjects(actor.sub, actor.clientId);
  if (projects.length !== 1) {
    return {project: null, selectionRequired: projects.length > 1};
  }
  // The list is a hint, NOT a lasting grant. Revalidate against current
  // device/project permissions before allowing the relay to run.
  return {
    project: await inventory.getProject(actor.sub, actor.clientId, projects[0]!.id),
    selectionRequired: false
  };
}

export function createCloudMcpHandler(
  inventory: Inventory, actor: Actor, projectPresence?:ProjectPresenceReader,
  projectDrc?:ProjectDrcReader, projectInspection?:ProjectInspectionReader,
  boardCounts?:ProjectBoardCountsReader,
  schematicCounts?:ProjectSchematicCountsReader,
  isDeviceConnected?:(ownerSub:string,deviceId:string)=>boolean,
  getDeviceCapabilityClaim?:(ownerSub:string,deviceId:string)=>ConnectorCapabilityClaim|null,
  projectWrite?:ProjectWriteExecutor,
  protectedResourceMetadataUrl?:string,
  genericMcpCatalog?:GenericMcpCatalogReader,
  genericMcpCall?:GenericMcpCaller,
  directToolsEnabled=false
) {
  return createMcpHandler(() => {
    const mcp = new McpServer({ name: "kicad-mcp-pro-cloud", version: "0.1.0" });
    // Reporting must describe the deployed read surface, not old
    // foundation-only placeholders. A signed WebSocket indicates an
    // authenticated device connection, NOT a KiCad GUI or operation grant.
    const localReadEnabled=Boolean(projectPresence||projectDrc||projectInspection||
      boardCounts||schematicCounts);
    const nativeReadEnabled=Boolean(projectDrc||projectInspection||
      boardCounts||schematicCounts);
    const connected=(deviceId:string)=>Boolean(
      isDeviceConnected?.(actor.sub,deviceId));
    // Claims are effective only inside a currently authenticated signed socket.
    // A missing claim is the legacy v1 Connector compatibility path.
    const authenticatedClaim=(project:Project)=>
      connected(project.deviceId)
        ? getDeviceCapabilityClaim?.(actor.sub,project.deviceId)??null
        : null;
    const describeProject=(project:Project)=>{
      const connectorConnected=connected(project.deviceId);
      // Legacy "available" describes the separately enabled legacy read
      // operations, not the generic MCP catalog/relay. Expose the new path
      // independently without treating an open socket as tool success.
      const bridgeConfigured=Boolean(genericMcpCatalog&&genericMcpCall);
      const claim=authenticatedClaim(project);
      // A signed capability report may narrow an already-connected device,
      // but cannot grant project access or prove any native command succeeds.
      const bridgeAdvertised=claim===null||claim.operations.includes("mcp_bridge");
      const readAttemptReady=bridgeConfigured&&connectorConnected&&bridgeAdvertised&&
        actor.scopes.has("projects:read");
      const state=!bridgeConfigured?"not_configured":
        !connectorConnected?"device_not_connected":
        !bridgeAdvertised?"connector_mcp_unavailable":
        !actor.scopes.has("projects:read")?"read_scope_required":
        "signed_session_connected";
      // The same Connector mode controls its signed footprint-write offer
      // and its generic MCP write worker. Legacy clients have no claim.
      const sessionNativeWriteMode=!connectorConnected||claim===null
        ?"unverified" as const
        :claim.operations.includes("move_footprint")
        ?"advertised" as const:"not_advertised" as const;
      return {
        ...project,available:false,
        reason:!localReadEnabled?"cloud_read_not_enabled":
          !connectorConnected?"device_not_connected":"owner_operation_required",
        connectorConnected,
        // A live signed MCP bridge is distinct from the optional legacy
        // presence reader; neither state proves an open KiCad GUI or WRITE.
        ...(readAttemptReady?{guidance:
          "Legacy presence may be unavailable while signed MCP tools work. Use local_mcp_catalog to find actual tools, then local_mcp_read or local_mcp_write. A connected device alone does not confirm KiCad Editor or editing access."
        }:{}),
        localMcp:{
          bridgeConfigured,readAttemptReady,state,sessionNativeWriteMode,
          nativeWriteAuthorization:"unverified" as const
        }
      };
    };
    // Compatibility path only for deployments without the signed generic MCP bridge.
    // The normal connected Cloud exposes exactly four real-local-tool gateway calls.
    const legacyOnly=!genericMcpCatalog||!genericMcpCall;
    if(legacyOnly){
    mcp.registerTool("get_service_status", {
      description: "Describe current Cloud read features without claiming a local KiCad action or GUI session.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({
      status: directToolsEnabled ? "named_local_mcp_tool_pilot" :
        projectInspection ? "local_engine_inspection_pilot" :
        boardCounts||schematicCounts ? "local_project_read_pilot" :
        projectDrc ? "local_native_drc_pilot" :
        projectPresence ? "local_presence_pilot" : "foundation_only",
      remoteKiCadExecution: nativeReadEnabled || Boolean(projectWrite) ||
        (directToolsEnabled && Boolean(genericMcpCall)),
      devicePairing: localReadEnabled,
      projectManagementWrites: Boolean(projectWrite),
      message: directToolsEnabled
        ? "Published pilot tools are reviewable independently of device state. Each read needs a live project grant; edits additionally require OAuth projects:write, project Edit, signed native owner approval and compatible local tool contracts."
        : localReadEnabled
        ? "Only enabled, project-granted owner-foreground read operations are available. Device connection is not proof of KiCad GUI, project contents or permission to execute."
        : "Cloud inventory is read-only. No owner-operated remote reads are enabled."
    }));
    mcp.registerTool("list_devices", {
      description: "List only the authenticated client's granted device metadata, with current signed Connector session state; never infer KiCad GUI readiness.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({ devices: (await inventory.listDevices(actor.sub,actor.clientId))
      .map(d=>({...d,connected:connected(d.id)})) }));
    }
    mcp.registerTool("list_projects", {
      description: "List your granted projects, online device status and signed MCP readiness. Discover real installed tools with local_mcp_catalog; run with local_mcp_read or local_mcp_write according to accessMode. A legacy available:false result does not prove the device is offline. No local paths or design contents.",
      inputSchema: z.object({}), annotations: readonly,
      _meta: { ui: { resourceUri: "ui://project-review" } }
    }, async () => text({ projects: (await inventory.listProjects(actor.sub,actor.clientId))
      .map(describeProject) }));
    if(legacyOnly){
    mcp.registerTool("get_project", {
      description: "Find a granted project with its separate signed generic MCP readiness in localMcp. The legacy available/reason fields are NOT a test of local_mcp_catalog or KiCad Editor. Never exposes local paths or design data.",
      inputSchema: z.object({ project_id: z.string().uuid() }), annotations: readonly,
      _meta: { ui: { resourceUri: "ui://project-review" } }
    }, async ({ project_id }) => {
      const project = await inventory.getProject(actor.sub,actor.clientId,project_id);
      if (!project) {
        return text({ found:false, message:"Project not found or not accessible" });
      }
      const desc = describeProject(project);
      return {
        content: [{ type: "text" as const, text: JSON.stringify({ project: desc }) }],
        structuredContent: { project: desc }
      };
    });
    }
    mcp.registerResource(
      "kicad-project-review",
      "ui://project-review",
      {
        mimeType: "text/html;profile=mcp-app",
        description: "Interactive KiCad Project Review MCP App"
      },
      async (uri) => {
        const html = readFileSync(new URL("../dist/project-review.html", import.meta.url), "utf8");
        return {
          contents: [{
            uri: uri.href,
            mimeType: "text/html;profile=mcp-app",
            text: html,
            _meta: {ui:{csp:{connectDomains:[],resourceDomains:[],frameDomains:[]}}}
          }]
        };
      }
    );
    if(legacyOnly){
    // Task-first discovery describes the CURRENT Cloud MCP surface, not
    // the much broader local KiCad tool registry. Never claim availability
    // for a feature that was not explicitly enabled on this Cloud instance.
    // The same bounded registry powers task discovery and category browsing.
    // Never mirror arbitrary local-only tools into Cloud MCP.
    const enabled={
      inspect_engine:Boolean(projectInspection),
      check_board_drc:Boolean(projectDrc),
      check_project_files:Boolean(projectPresence),
      inspect_board:Boolean(boardCounts),
      inspect_schematic:Boolean(schematicCounts)
    };
    const workflows=Object.fromEntries(CLOUD_READ_CAPABILITIES.map(c=>[
      c.task,{tool:c.tool,enabled:enabled[c.task]}
    ])) as Record<(typeof CLOUD_READ_TASKS)[number],{tool:string;enabled:boolean}>;

    mcp.registerTool("list_project_capabilities",{
      description:"Browse the optional legacy read-only Cloud operations; for an owner-connected signed generic MCP bridge, use localMcp.readAttemptReady and local_mcp_catalog. A missing legacy capability does not imply the device is offline.",
      inputSchema:z.object({
        project_id:z.string().uuid().optional(),
        category:z.enum(CLOUD_READ_CATEGORIES).optional()
      }),annotations:readonly
    },async ({project_id,category})=>{
      const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
      if(!project)return text({catalogAvailable:false,selectionRequired,categories:[]});
      const view=describeProject(project);
      const {connectorConnected,localMcp}=view;
      return text({
        catalogAvailable:true,selectionRequired:false,connectorConnected,localMcp,
        ...("guidance" in view?{guidance:view.guidance}:{}),
        categories:listConfiguredCloudCapabilities(
          enabled,connectorConnected,category,authenticatedClaim(project)
        )
      });
    });

    mcp.registerTool("discover_project_workflow",{
      description:"Discover optional legacy Cloud read operations, separate from installed KiCad tools available through the signed generic MCP bridge. If unavailable, check localMcp.readAttemptReady and verify local_mcp_catalog before suggesting re-pairing.",
      inputSchema:z.object({
        task:z.enum(CLOUD_READ_TASKS),
        project_id:z.string().uuid().optional()
      }),annotations:readonly
    },async ({task,project_id})=>{
      const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
      if(!project)return text({available:false,selectionRequired,tools:[]});
      const chosen=workflows[task];
      const claimEnabled=configuredReadersForClaim(enabled,authenticatedClaim(project));
      const view=describeProject(project);
      return text(chosen.enabled&&claimEnabled[task] ? {
        available:true,selectionRequired:false,
        tools:[chosen.tool],requiresOwnerSession:true
      } : {
        available:false,selectionRequired:false,tools:[],
        reason:chosen.enabled?"connector_operation_not_supported":"cloud_operation_not_enabled",
        localMcp:view.localMcp,
        ...("guidance" in view?{guidance:view.guidance}:{})
      });
    });
    // Pilot presence read is an opt-in Cloud capability. No native commands,
    // file contents, local paths, or editing tools are exposed over MCP.
    if(projectPresence){
      mcp.registerTool("get_project_presence",{
        description:"Legacy opt-in project presence metadata check, NOT a signed KiCad tool call. An unavailable legacy presence result alone does not prove that the signed device is offline; verify current connection and owner-scoped access independently.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project, selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        // A disconnected device or failed authorization is unavailable.
        // Do not leak backend diagnostics through a public MCP tool.
        let files:ProjectPresenceFiles|null=null;
        try{files=await projectPresence(project.deviceId,project.id);}
        catch{files=null;}
        if(files)return text({available:true,files});
        // An unavailable legacy presence probe does not imply the signed
        // generic MCP bridge is offline. Recheck the scoped grant before
        // disclosing any live device readiness after a failed request.
        const current=await inventory.getProject(actor.sub,actor.clientId,project.id);
        if(!current)return text({available:false});
        const view=describeProject(current);
        return text({
          available:false,connectorConnected:view.connectorConnected,localMcp:view.localMcp,
          ...("guidance" in view?{guidance:view.guidance}:{})
        });
      });
    }
    // Deliberately absent unless the separate native DRC pilot is enabled.
    // No board data, paths, command strings, writes or report excerpts.
    if(projectDrc){
      mcp.registerTool("get_project_drc_counts",{
        description:"Run owner-foreground, read-only native KiCad PCB DRC for one granted local project. project_id is optional only when exactly one project is accessible; otherwise select from list_projects. Returns counts only.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project, selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        let counts:DrcCounts|null=null;
        try{counts=await projectDrc(project.deviceId,project.id);}
        catch{counts=null;}
        return text(counts?{available:true,counts}:{available:false});
      });
    }
    // Explicitly opt-in only: the manual local inspection pilot must be
    // enabled independently of the existing presence and DRC capabilities.
    if(projectInspection){
      mcp.registerTool("get_project_engine_status",{
        description:"Inspect bounded KiCad engine availability for one owner-granted project via a manually started local MCP worker. Does not return design contents or paths.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        let status:ProjectInspectionStatus|null=null;
        try{status=await projectInspection(project.deviceId,project.id);}
        catch{status=null;}
        return text(status?{available:true,status}:{available:false});
      });
    }
    if(boardCounts){
      mcp.registerTool("get_project_board_counts",{
        description:"Read only aggregate footprint, net, track, via, zone and shape counts from one owner-approved local PCB; no board contents or local paths.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        let counts:ProjectBoardCounts|null=null;
        try{counts=await boardCounts(project.deviceId,project.id);}
        catch{counts=null;}
        return text(counts?{available:true,board:counts}:{available:false});
      });
    }
    if(schematicCounts){
      mcp.registerTool("get_project_schematic_counts",{
        description:"Read bounded component, population, DNP and BOM counts from one granted local schematic. Never return symbols, names, file paths or design contents.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        let counts:ProjectSchematicCounts|null=null;
        try{counts=await schematicCounts(project.deviceId,project.id);}
        catch{counts=null;}
        return text(counts?{available:true,counts}:{available:false});
      });
    }
    }
    if(genericMcpCatalog&&genericMcpCall&&!directToolsEnabled){
      mcp.registerTool("local_mcp_catalog",{
        description:"Browse the REAL installed KiCad MCP Pro tools and original JSON input schemas on an owner-connected device. Results depend on the current local profile, live Connector and project grant. No tools are reimplemented in Cloud; paginate with next_offset.",
        inputSchema:z.object({
          project_id:z.string().uuid().optional(),
          offset:z.number().int().min(0).max(512).optional(),
          tool_name:z.string().regex(/^[a-z][a-z0-9_]{0,127}$/).optional()
        }),annotations:readonly,
        _meta:{securitySchemes:[{type:"oauth2",scopes:["projects:read"]}]}
      },async ({project_id,offset,tool_name})=>{
        const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        return runSerializedCloudRead(inventory,actor.sub,project.deviceId,async()=>{
          try{
            const catalog=await genericMcpCatalog(project.deviceId,project.id,offset??0,tool_name);
            if(!catalog)return text({available:false,reason:"owner_connector_mcp_unavailable"});
            // Re-check the client's current grant after waiting for the
            // signed Connector. A former Edit grant must not leak write tools.
            const currentGrant=await inventory.getProject(
              actor.sub,actor.clientId,project.id);
            if(!currentGrant||currentGrant.deviceId!==project.deviceId)
              return text({available:false,reason:"project_not_granted"});
            const mayWrite=actor.scopes.has("projects:write")&&currentGrant.maxMode==="write";
            return text({available:true,project_id:project.id,
              tools:catalog.tools.filter(t=>t.accessMode==="readonly"||mayWrite),
              next_offset:catalog.nextOffset});
          }catch{return text({available:false,reason:"owner_connector_mcp_unavailable"});}
        },()=>text({available:false,reason:"owner_connector_mcp_busy",retrySafe:true,
          guidance:"The owner Connector is processing another request. Try again shortly; only bounded READ operations are queued."}));
      });
      const invokeLocalTool=async(
        mode:"readonly"|"write",
        request:{project_id?:string;tool_name:string;arguments:Record<string,unknown>}
      )=>{
        const {project,selectionRequired}=await resolveScopedProject(
          inventory,actor,request.project_id);
        if(!project)return {...text({success:false,selectionRequired,reason:"project_not_granted"}),
          isError:true};
        const execute=async()=>{
          let catalog:Awaited<ReturnType<GenericMcpCatalogReader>>=null;
          try{
            catalog=await genericMcpCatalog(project.deviceId,project.id,0,request.tool_name);
          }catch{/* No call without local contract. */}
          if(!catalog)return {...text({success:false,reason:"owner_connector_mcp_unavailable",
            guidance:"The signed local catalog could not be retrieved. Check the device connection and run operations one at a time; retry discovery after the current operation or session refresh completes. No local tool call was dispatched."
          }),isError:true};
          const tool=catalog.tools.find(t=>t.name===request.tool_name);
          if(!tool)return {...text({success:false,reason:"local_tool_unavailable",
            guidance:"The tool is absent from the current authorized local catalog. Discover available tools with local_mcp_catalog."
          }),isError:true};
          if(tool.accessMode!==mode)return {...text({
            success:false,reason:tool.accessMode==="write"
              ?"write_tool_requires_local_mcp_write":"read_tool_requires_local_mcp_read"
          }),isError:true};
          const write=mode==="write";
          if(write&&(!actor.scopes.has("projects:write")||project.maxMode!=="write")){
            const denied=text({success:false,reason:!actor.scopes.has("projects:write")?
              "insufficient_scope_write_required":"project_edit_permission_required",
              guidance:"Approve projects:write for this application and choose Edit for this project."});
            if(!actor.scopes.has("projects:write")&&protectedResourceMetadataUrl)return {
              ...denied,isError:true,_meta:{"mcp/www_authenticate":[
                'Bearer resource_metadata="'+protectedResourceMetadataUrl+'", '+
                'error="insufficient_scope", scope="projects:read projects:write"'
              ]}
            };
            return {...denied,isError:true};
          }
          try{
            const result=await genericMcpCall(
              project.deviceId,project.id,request.tool_name,request.arguments,write);
            if(result===null)return {...text({success:false,
              reason:"local_mcp_operation_unconfirmed",
              outcomeUnknown:write,retrySafe:!write,
              guidance:write?"Inspect the local design before retrying.":"Check the device connection."}),
              isError:true};
            const actual=result as {isError?:boolean;structuredContent?:{success?:boolean}};
            const success=actual.isError!==true&&actual.structuredContent?.success!==false;
            return {...text({success,tool_name:request.tool_name,local_result:result}),
              ...(success?{}:{isError:true})};
          }catch{
            return {...text({success:false,reason:"local_mcp_operation_unconfirmed",
              outcomeUnknown:write,retrySafe:!write}),isError:true};
          }
        };
        // Write remains immediate and is never placed in this queue.
        return mode==="write"?execute():
          runSerializedCloudRead(inventory,actor.sub,project.deviceId,execute,
            ()=>({...text({success:false,reason:"owner_connector_mcp_busy",
              retrySafe:true,guidance:"The owner Connector is busy. Retry this READ after the current operation finishes; no local tool was dispatched."}),isError:true}));
      };
      const localToolSchema=z.object({
        project_id:z.string().uuid().optional(),
        tool_name:z.string().regex(/^[a-z][a-z0-9_]{0,127}$/),
        arguments:z.record(z.string(),z.unknown())
      });
      mcp.registerTool("local_mcp_read",{
        description:"Run a READ tool from the real, installed KiCad MCP catalog. Discover the exact schema with local_mcp_catalog. Requires one owner-granted connected project; never runs a mutating tool.",
        inputSchema:localToolSchema,annotations:readonly,
        _meta:{securitySchemes:[{type:"oauth2",scopes:["projects:read"]}]}
      },async request=>invokeLocalTool("readonly",request));
      mcp.registerTool("local_mcp_write",{
        description:"Run a WRITE tool from the real installed KiCad MCP catalog. Requires projects:write OAuth consent, project Edit grant, and a locally owner-approved signed edit session. Never executes manufacturing-only operations. A timed-out write has unknown outcome: inspect the project before retrying.",
        inputSchema:localToolSchema,
        annotations:{readOnlyHint:false,destructiveHint:true,idempotentHint:false,openWorldHint:false},
        _meta:{securitySchemes:[{type:"oauth2",scopes:["projects:read","projects:write"]}]}
      },async request=>invokeLocalTool("write",request));
    }

    // A reviewed public tool definition stays stable even when a device is
    // offline or has an older local MCP installation. Per-call verification
    // still checks the actual locally registered tool contract.
    if(directToolsEnabled&&genericMcpCatalog&&genericMcpCall){
      registerDirectCloudMcpTools(mcp,async(tool,raw)=>{
        const {project_id:requestedProjectId,...args}=raw;
        if(requestedProjectId!==undefined&&typeof requestedProjectId!=="string")
          return {...text({success:false,reason:"invalid_project_id"}),isError:true};
        const {project,selectionRequired}=await resolveScopedProject(
          inventory,actor,requestedProjectId as string|undefined);
        if(!project)return {...text({success:false,selectionRequired,
          reason:"project_not_granted"}),isError:true};
        const needsWrite=tool.accessMode==="write";
        if(!actor.scopes.has("projects:read"))
          return {...text({success:false,reason:"insufficient_scope_read_required"}),isError:true};
        if(needsWrite&&!actor.scopes.has("projects:write")){
          const denied={...text({success:false,reason:"insufficient_scope_write_required",
            guidance:"Reconnect and approve projects:write for this application."}),isError:true};
          if(protectedResourceMetadataUrl)return {...denied,_meta:{
            "mcp/www_authenticate":[
              'Bearer resource_metadata="'+protectedResourceMetadataUrl+'", '+
              'error="insufficient_scope", scope="projects:read projects:write"'
            ]
          }};
          return denied;
        }
        if(needsWrite&&project.maxMode!=="write")
          return {...text({success:false,reason:"project_edit_permission_required",
            guidance:"Choose Edit for this application's access to the project."}),isError:true};
        const execute=async()=>{
          try{
            const catalog=await genericMcpCatalog(project.deviceId,project.id,0,tool.name);
            const local=catalog?.tools.find(t=>t.name===tool.name);
            if(!local)return {...text({success:false,reason:"local_tool_unavailable",
              guidance:needsWrite
                ?"Connect or update the owner's Connector and enable signed native write for this project."
                :"Connect the owner device and open the selected project in KiCad; update the Connector if the tool remains unavailable."}),isError:true};
            if(local.accessMode!==tool.accessMode||
                stableJson(local.inputSchema)!==stableJson(tool.inputSchema))
              return {...text({success:false,reason:"local_tool_contract_mismatch",
                guidance:"Update the local KiCad MCP Pro installation to a compatible tool contract."}),
                isError:true};
            const result=await genericMcpCall(project.deviceId,project.id,tool.name,args,needsWrite);
            if(result===null)
              return {...text({success:false,reason:"local_mcp_operation_unconfirmed",
                outcomeUnknown:needsWrite,retrySafe:!needsWrite,
                guidance:needsWrite?"Inspect the local design before retrying.":"Reconnect the device."}),
                isError:true};
            const actual=result as {isError?:boolean;structuredContent?:{success?:boolean}};
            const success=actual.isError!==true&&actual.structuredContent?.success!==false;
            return {...text({success,tool_name:tool.name,local_result:result}),
              ...(success?{}:{isError:true})};
          }catch{
            return {...text({success:false,reason:"local_mcp_operation_unconfirmed",
              outcomeUnknown:needsWrite,retrySafe:!needsWrite}),isError:true};
          }
        };
        return needsWrite?execute():
          runSerializedCloudRead(inventory,actor.sub,project.deviceId,execute,
            ()=>({...text({success:false,reason:"owner_connector_mcp_busy",
              retrySafe:true,guidance:"The owner Connector is busy. Retry this READ after the current operation finishes; no local tool was dispatched."}),isError:true}));
      });
    }

    if(legacyOnly){
    if(projectWrite){
      mcp.registerTool("pcb_move_footprint",{
        description:"Move an owner-approved PCB footprint by reference designator with atomic local locking and optional disk persistence. Requires projects:write OAuth scope and active owner-connected device session.",
        inputSchema:z.object({
          project_id:z.string().uuid().optional(),
          reference:z.string().regex(/^[A-Z]{1,3}[1-9][0-9]{0,5}$/),
          x_mm:z.number().finite().min(-1000).max(1000),
          y_mm:z.number().finite().min(-1000).max(1000),
          rotation_deg:z.number().finite().min(-360).max(360).nullable().optional(),
          save_to_disk:z.boolean().optional()
        }),annotations:{readOnlyHint:false,destructiveHint:true,idempotentHint:false,openWorldHint:false},
        _meta:{securitySchemes:[{type:"oauth2",scopes:["projects:read","projects:write"]}]}
      },async ({project_id,reference,x_mm,y_mm,rotation_deg,save_to_disk})=>{
        if(!actor.scopes.has("projects:write")){
          const denied=text({success:false,reason:"insufficient_scope_write_required",
            guidance:"Reconnect this AI app and approve project editing, then choose Edit for this project in Cloud."});
          if(!protectedResourceMetadataUrl)return {...denied,isError:true};
          return {...denied,isError:true,_meta:{"mcp/www_authenticate":[
            'Bearer resource_metadata="'+protectedResourceMetadataUrl+'", '+
            'error="insufficient_scope", scope="projects:read projects:write", '+
            'error_description="Reconnect to allow KiCad project editing"'
          ]}};
        }
        const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({success:false,selectionRequired});
        // The OAuth write scope alone is not the owner's per-project Edit grant.
        // A known Read-only grant must fail before signing/dispatch, not as an
        // ambiguous native write result requiring the owner to inspect the board.
        if(project.maxMode==="readonly")return {...text({
          success:false,reason:"project_edit_permission_required",
          guidance:"Choose Edit for this AI app in the project's Cloud access settings."
        }),isError:true};
        let result:ProjectWriteResult|null=null;
        try{
          result=await projectWrite(project.deviceId,project.id,{
            reference,
            xMm:x_mm,
            yMm:y_mm,
            rotationDeg:rotation_deg??null,
            saveToDisk:save_to_disk??true
          });
        }catch{
          result=null;
        }
        // A relay failure or authorization change after dispatch cannot prove
        // whether KiCad already committed. Preserve the existing error code,
        // but explicitly prohibit blind retries until the board is inspected.
        return text(result?{...result}:{
          success:false,
          reason:"write_execution_failed",
          outcomeUnknown:true,
          retrySafe:false,
          guidance:"Write outcome is unconfirmed. Check the local board before retrying."
        });
      });
    }
    }
    return mcp;
  });
}
