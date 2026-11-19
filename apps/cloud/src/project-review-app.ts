import { App } from "@modelcontextprotocol/ext-apps";

type ToolSnapshot={structuredContent?:unknown};

const app=new App({name:"KiCad Project Review",version:"1.0.0"});
const status=document.getElementById("status") as HTMLParagraphElement;
const details=document.getElementById("details") as HTMLElement;
const refresh=document.getElementById("refresh") as HTMLButtonElement;
const name=document.getElementById("project-name") as HTMLElement;
const connection=document.getElementById("project-connection") as HTMLElement;
const identifier=document.getElementById("project-id") as HTMLElement;
let projectId:string|undefined;

function show(result:ToolSnapshot):void {
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
refresh.addEventListener("click",async()=>{
  if(!projectId)return;
  refresh.disabled=true;
  status.textContent="Checking current project access?";
  try{show(await app.callServerTool({name:"get_project",arguments:{project_id:projectId}}));}
  catch{
    projectId=undefined;
    refresh.disabled=true;
    details.hidden=true;
    status.textContent="Could not refresh. Check your connection and project permissions.";
  }
});
app.connect().catch(()=>{
  projectId=undefined;
  refresh.disabled=true;
  details.hidden=true;
  status.textContent="This host cannot display the interactive view. Use the text tool result instead.";
});
