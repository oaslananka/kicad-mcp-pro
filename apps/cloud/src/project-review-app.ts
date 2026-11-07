import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({name:"KiCad Project Review",version:"1.0.0"});
const status = document.getElementById("status")!;
const details = document.getElementById("details")!;
const refresh = document.getElementById("refresh") as HTMLButtonElement;
let projectId: string | undefined;
function show(result: {structuredContent?: unknown}) {
  const content = result.structuredContent as {project?:unknown} | undefined;
  const project = content?.project as {id?:string;alias?:string;connectorConnected?:boolean} | undefined;
  details.replaceChildren();
  if (!project?.id) {
    projectId = undefined;
    refresh.disabled = true;
    status.textContent = "Project is unavailable or access was revoked.";
    return;
  }
  projectId = project.id;
  refresh.disabled = false;
  status.textContent = "Project access is read-only.";
  for (const [label,value] of [["Project",project.alias ?? ""],["Project ID",project.id],["Device",project.connectorConnected ? "Connected" : "Disconnected"]]) {
    const row = document.createElement("p");
    row.textContent = `${label}: ${value}`;
    details.append(row);
  }
}
app.ontoolresult = show;
refresh.addEventListener("click", async () => {
  if (!projectId) return;
  refresh.disabled = true;
  try { show(await app.callServerTool({name:"get_project",arguments:{project_id:projectId}})); }
  catch { projectId = undefined; details.replaceChildren(); status.textContent = "Could not refresh project access."; }
});
app.connect().catch(() => { status.textContent = "Host connection unavailable. Use the text result instead."; });
