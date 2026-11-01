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
  projectDrc?:ProjectDrcReader
) {
  return createMcpHandler(() => {
    const mcp = new McpServer({ name: "kicad-mcp-pro-cloud", version: "0.1.0" });
    mcp.registerTool("get_service_status", {
      description: "Describe Cloud connectivity limits and current feature availability. No local KiCad operation is performed.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({
      status: projectDrc ? "local_native_drc_pilot" :
        projectPresence ? "local_presence_pilot" : "foundation_only",
      remoteKiCadExecution: Boolean(projectDrc),
      devicePairing: Boolean(projectPresence),
      projectManagementWrites: false,
      message: projectDrc
        ? "Owner-operated one-shot native DRC counts only; no board contents, file paths or arbitrary commands."
        : projectPresence
          ? "Only one-shot, owner-granted project presence flags are available; no KiCad commands or file contents."
          : "Cloud inventory is read-only. A local connector is not yet available."
    }));
    mcp.registerTool("list_devices", {
      description: "List the authenticated user's registered device metadata. Connected always false until a verified device relay exists.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({ devices: await inventory.listDevices(actor.sub,actor.clientId) }));
    mcp.registerTool("list_projects", {
      description: "List only enabled KiCad project aliases owned by the authenticated user. No local paths or design contents.",
      inputSchema: z.object({}), annotations: readonly
    }, async () => text({ projects: await inventory.listProjects(actor.sub,actor.clientId) }));
    mcp.registerTool("get_project", {
      description: "Find an enabled project by opaque UUID within the authenticated user's inventory; never returns paths or KiCad data.",
      inputSchema: z.object({ project_id: z.string().uuid() }), annotations: readonly
    }, async ({ project_id }) => {
      const project = await inventory.getProject(actor.sub,actor.clientId,project_id);
      return text(project ? { project } : { found: false, message: "Project not found or not accessible" });
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
    return mcp;
  });
}
