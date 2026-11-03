import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import type { Actor } from "./auth.js";
import type { Inventory, Project } from "./store.js";

const text = (value: object) => ({
  content: [{ type: "text" as const, text: JSON.stringify(value) }],
  structuredContent: value
});
const readonly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };

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
  isDeviceConnected?:(ownerSub:string,deviceId:string)=>boolean
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
    const describeProject=(project:Project)=>{
      const connectorConnected=connected(project.deviceId);
      return {
        ...project,available:false,
        reason:!localReadEnabled?"cloud_read_not_enabled":
          !connectorConnected?"device_not_connected":"owner_operation_required",
        connectorConnected
      };
    };
    mcp.registerTool("get_service_status", {
      description: "Describe current Cloud read features without claiming a local KiCad action or GUI session.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({
      status: projectInspection ? "local_engine_inspection_pilot" :
        boardCounts||schematicCounts ? "local_project_read_pilot" :
        projectDrc ? "local_native_drc_pilot" :
        projectPresence ? "local_presence_pilot" : "foundation_only",
      remoteKiCadExecution: nativeReadEnabled,
      devicePairing: localReadEnabled,
      projectManagementWrites: false,
      message: localReadEnabled
        ? "Only enabled, project-granted owner-foreground read operations are available. Device connection is not proof of KiCad GUI, project contents or permission to execute."
        : "Cloud inventory is read-only. No owner-operated remote reads are enabled."
    }));
    mcp.registerTool("list_devices", {
      description: "List only the authenticated client's granted device metadata, with current signed Connector session state; never infer KiCad GUI readiness.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({ devices: (await inventory.listDevices(actor.sub,actor.clientId))
      .map(d=>({...d,connected:connected(d.id)})) }));
    mcp.registerTool("list_projects", {
      description: "List only enabled granted project aliases and current owner-session readiness. No local paths or design contents.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({ projects: (await inventory.listProjects(actor.sub,actor.clientId))
      .map(describeProject) }));
    mcp.registerTool("get_project", {
      description: "Find an enabled granted project by opaque UUID with session status, never local paths or KiCad data.",
      inputSchema: z.object({ project_id: z.string().uuid() }), annotations: readonly
    }, async ({ project_id }) => {
      const project = await inventory.getProject(actor.sub,actor.clientId,project_id);
      return text(project ? { project:describeProject(project) }
        : { found:false, message:"Project not found or not accessible" });
    });
    // Task-first discovery describes the CURRENT Cloud MCP surface, not
    // the much broader local KiCad tool registry. Never claim availability
    // for a feature that was not explicitly enabled on this Cloud instance.
    const workflows = {
      inspect_engine: {
        tool: "get_project_engine_status",
        enabled: Boolean(projectInspection)
      },
      check_board_drc: {
        tool: "get_project_drc_counts",
        enabled: Boolean(projectDrc)
      },
      check_project_files: {
        tool: "get_project_presence",
        enabled: Boolean(projectPresence)
      },
      inspect_board: {
        tool: "get_project_board_counts",
        enabled: Boolean(boardCounts)
      },
      inspect_schematic: {
        tool: "get_project_schematic_counts",
        enabled: Boolean(schematicCounts)
      }
    } as const;
    mcp.registerTool("discover_project_workflow",{
      description:"Find the currently enabled, project-authorized Cloud MCP tool for a read-only KiCad task. Reports missing capabilities without executing KiCad, switching projects or revealing local paths.",
      inputSchema:z.object({
        task:z.enum(["inspect_engine","check_board_drc", "check_project_files","inspect_board","inspect_schematic"]),
        project_id:z.string().uuid().optional()
      }),annotations:readonly
    },async ({task,project_id})=>{
      const {project,selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
      if(!project)return text({available:false,selectionRequired,tools:[]});
      const chosen=workflows[task];
      return text(chosen.enabled ? {
        available:true,selectionRequired:false,
        tools:[chosen.tool],requiresOwnerSession:true
      } : {
        available:false,selectionRequired:false,tools:[],
        reason:"cloud_operation_not_enabled"
      });
    });
    // Pilot presence read is an opt-in Cloud capability. No native commands,
    // file contents, local paths, or editing tools are exposed over MCP.
    if(projectPresence){
      mcp.registerTool("get_project_presence",{
        description:"Read project presence from one granted local KiCad project. When only one project is accessible its ID is optional; otherwise use list_projects and provide project_id. Requires one active owner-started session.",
        inputSchema:z.object({project_id:z.string().uuid().optional()}),annotations:readonly
      },async ({project_id})=>{
        const {project, selectionRequired}=await resolveScopedProject(inventory,actor,project_id);
        if(!project)return text({available:false,selectionRequired});
        // A disconnected device or failed authorization is unavailable.
        // Do not leak backend diagnostics through a public MCP tool.
        let files:ProjectPresenceFiles|null=null;
        try{files=await projectPresence(project.deviceId,project.id);}
        catch{files=null;}
        return text(files?{available:true,files}:{available:false});
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
    return mcp;
  });
}
