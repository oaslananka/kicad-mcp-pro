import { App } from "@modelcontextprotocol/ext-apps";

type ToolSnapshot={structuredContent?:unknown};

const app=new App({name:"KiCad Project Review",version:"1.0.0"});
const status=document.getElementById("status") as HTMLParagraphElement;
const details=document.getElementById("details") as HTMLElement;
const refresh=document.getElementById("refresh") as HTMLButtonElement;
const checkEditor=document.getElementById("check-editor") as HTMLButtonElement;
const editorStatus=document.getElementById("editor-status") as HTMLParagraphElement;
const name=document.getElementById("project-name") as HTMLElement;
const connection=document.getElementById("project-connection") as HTMLElement;
const identifier=document.getElementById("project-id") as HTMLElement;
let projectId:string|undefined;
let projectGeneration=0;
let nativeWriteAdvertised=false;

function show(result:ToolSnapshot):void {
  projectGeneration++;
  editorStatus.hidden=true;
  editorStatus.textContent="";
  checkEditor.disabled=true;
  nativeWriteAdvertised=false;
  // Server-owned structuredContent is authoritative; never infer a grant
  // from cached iframe state or render tool-supplied HTML.
  const content=result.structuredContent;
  const project=content&&typeof content==="object"&&"project" in content
    ? content.project : undefined;
  if(!project||typeof project!=="object"||!("id" in project)||
     typeof project.id!=="string"||!project.id){
    projectId=undefined;
    details.hidden=true;
    refresh.disabled=true;
    name.textContent="";
    connection.textContent="";
    identifier.textContent="";
    status.textContent="Project unavailable. Your access may have been removed.";
    return;
  }
  projectId=project.id;
  name.textContent=("alias" in project&&typeof project.alias==="string"&&project.alias.trim())||"Unnamed project";
  identifier.textContent=project.id;
  const online=("connectorConnected" in project&&project.connectorConnected===true);
  connection.textContent=online?"Signed Connector online":"Connector offline";
  connection.className="value "+(online?"connected":"disconnected");
  details.hidden=false;
  refresh.disabled=false;
  const mcp=("localMcp" in project&&project.localMcp&&
    typeof project.localMcp==="object")?project.localMcp:null;
  const canAttemptRead=mcp&&"readAttemptReady" in mcp&&mcp.readAttemptReady===true;
  const writeNotAdvertised=mcp&&"sessionNativeWriteMode" in mcp&&
    mcp.sessionNativeWriteMode==="not_advertised";
  const writeAdvertised=mcp&&"sessionNativeWriteMode" in mcp&&
    mcp.sessionNativeWriteMode==="advertised";
  const bridgeUnavailable=mcp&&"state" in mcp&&mcp.state==="connector_mcp_unavailable";
  nativeWriteAdvertised=Boolean(writeAdvertised);
  checkEditor.disabled=!canAttemptRead;
  status.textContent=canAttemptRead
    ?writeNotAdvertised
      ?"MCP read tools can be requested. Native editing is not advertised by this Connector session. In the owner's terminal use kicad-mcp-pro cloud remote --enable-native-write. Cloud Edit and OAuth permissions are separate."
      :writeAdvertised
      ?"MCP read tools can be requested. Connector advertises native editing but does not prove authorization, KiCad readiness or a completed write."
      :"MCP read tools can be requested. This does not confirm native editing or KiCad readiness."
    :bridgeUnavailable
    ?"Connector is online, but its reported capabilities do not include the MCP bridge. Update the local Connector."
    :online
    ?"Project metadata is available. KiCad engine status has not been verified."
    :"Project metadata is saved. Start your local Connector to read it.";
}
app.ontoolresult=show;
checkEditor.addEventListener("click",async()=>{
  const requestedProject=projectId;
  if(!requestedProject||checkEditor.disabled)return;
  const generation=projectGeneration;
  checkEditor.disabled=true;
  editorStatus.hidden=false;
  editorStatus.textContent="Checking KiCad PCB Editor (read-only)...";
  try{
    const probe=await app.callServerTool({
      name:"local_mcp_call",
      arguments:{project_id:requestedProject,tool_name:"kicad_get_server_info",arguments:{}}
    });
    if(projectGeneration!==generation||projectId!==requestedProject)return;
    const data=probe.structuredContent;
    const local=data&&typeof data==="object"&&"local_result" in data
      ?data.local_result:undefined;
    const info=local&&typeof local==="object"&&"structuredContent" in local
      ?local.structuredContent:undefined;
    const kicad=info&&typeof info==="object"&&"kicad" in info
      ?info.kicad:undefined;
    if(data&&typeof data==="object"&&"success" in data&&data.success===true&&
      local&&typeof local==="object"&&"isError" in local&&local.isError===true&&
      info&&typeof info==="object"&&"reason" in info&&
      info.reason==="local_mcp_read_timeout"){
      editorStatus.textContent="KiCad status check timed out. The editor may still be starting or busy; retry when it responds. This does not indicate a pairing failure.";
      return;
    }
    if(!data||typeof data!=="object"||!("success" in data)||data.success!==true||
      !local||typeof local!=="object"||("isError" in local&&local.isError===true)||
      !kicad||typeof kicad!=="object"||
      !("ipcAvailable" in kicad)||typeof kicad.ipcAvailable!=="boolean"||
      !("livePcbContext" in kicad)||typeof kicad.livePcbContext!=="boolean"){
      editorStatus.textContent="Could not verify PCB Editor. Check the Connector and project access.";
      return;
    }
    if(!kicad.ipcAvailable||!kicad.livePcbContext){
      editorStatus.textContent="PCB Editor IPC is unavailable. Open this project's board in KiCad PCB Editor, then check again.";
      return;
    }
    if(!nativeWriteAdvertised){
      editorStatus.textContent="PCB Editor IPC reports an open board, but the linked project identity is unverified and native editing is not advertised by this Connector session. Open the approved board and enable native write in the owner terminal.";
      return;
    }
    const response=await app.callServerTool({
      name:"local_mcp_catalog",
      arguments:{project_id:requestedProject,tool_name:"pcb_move_footprint"}
    });
    if(projectGeneration!==generation||projectId!==requestedProject)return;
    const toolsData=response.structuredContent;
    const tools=toolsData&&typeof toolsData==="object"&&"tools" in toolsData
      ?toolsData.tools:undefined;
    const available=toolsData&&typeof toolsData==="object"&&"available" in toolsData
      &&toolsData.available===true;
    if(!available||!Array.isArray(tools)){
      editorStatus.textContent="Could not verify PCB Editor tools. Check the Connector and project access.";
      return;
    }
    const move=tools.some(tool=>tool&&typeof tool==="object"&&
      "name" in tool&&tool.name==="pcb_move_footprint"&&
      "accessMode" in tool&&tool.accessMode==="write");
    editorStatus.textContent=move
      ?"PCB move tool is listed, but the linked project identity is unverified. This does not authorize editing or prove save/reopen."
      :"PCB move tool is not listed. Confirm the linked board in KiCad PCB Editor, then check again.";
  }catch{
    if(projectGeneration===generation&&projectId===requestedProject)
      editorStatus.textContent="Could not verify PCB Editor. Check the Connector and project access.";
  }finally{
    if(projectGeneration===generation&&projectId===requestedProject)
      checkEditor.disabled=false;
  }
});
refresh.addEventListener("click",async()=>{
  if(!projectId)return;
  projectGeneration++;
  refresh.disabled=true;
  checkEditor.disabled=true;
  editorStatus.hidden=true;
  status.textContent="Checking current project access?";
  try{show(await app.callServerTool({name:"get_project",arguments:{project_id:projectId}}));}
  catch{
    projectId=undefined;
    projectGeneration++;
    refresh.disabled=true;
    checkEditor.disabled=true;
    editorStatus.hidden=true;
    details.hidden=true;
    status.textContent="Could not refresh. Check your connection and project permissions.";
  }
});
app.connect().catch(()=>{
  projectGeneration++;
  projectId=undefined;
  refresh.disabled=true;
  checkEditor.disabled=true;
  editorStatus.hidden=true;
  details.hidden=true;
  status.textContent="This host cannot display the interactive view. Use the text tool result instead.";
});
