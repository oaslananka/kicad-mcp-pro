import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import type {renderDevicesPage,DevicePageOptions} from "./devices-ui.js";
import type {BrowserGrantSummary} from "./grants.js";

type Device=Parameters<typeof renderDevicesPage>[0][number];
type Project=NonNullable<DevicePageOptions["projects"]>[number];

function projectState(project:Project,device:Device|undefined,clients:readonly string[],grants:readonly BrowserGrantSummary[]){
  const manage="/devices#project-"+project.id;
  if(device?.revoked)return {id:"device-revoked",label:"Device access revoked",detail:"Reconnect this computer before sharing its projects again.",href:"/devices#connect-computer",action:"Reconnect computer",tone:"pending"};
  if(!device||!device.enabled||!project.enabled)return {id:"device-paused",label:"Project access paused",detail:"Review the computer and project permissions to continue.",href:manage,action:"Review access",tone:"neutral"};
  if(device.connectionState==="disconnected")return {id:"device-offline",label:"Computer offline",detail:"Sign in to this computer and check that its Connector is running.",href:"/devices",action:"Check computer",tone:"neutral"};
  if(!device.connectionState)return {id:"status-unknown",label:"Connection not verified",detail:"Check the computer's connection before requesting a project operation.",href:"/devices",action:"Check connection",tone:"neutral"};
  if(clients.length===0)return {id:"connect-ai",label:"Connect an AI app",detail:"Add the Cloud endpoint to your AI app, then approve its project access.",href:"/connections#mcp-setup",action:"Connect AI app",tone:"pending"};
  if(!grants.length)return {id:"grant-access",label:"Choose AI access",detail:"Choose which connected AI app can use this project.",href:manage,action:"Set project access",tone:"pending"};
  if(project.managedEnabled!==true)return {id:"reads-paused",label:"Project reads paused",detail:"Review project reads on the computer's project card.",href:manage,action:"Review project reads",tone:"pending"};
  return {id:"read-access-enabled",label:"Read access enabled",detail:"Computer connected. Available operations depend on the installed Connector and project permissions.",href:manage,action:"Manage project",tone:"ready"};
}

function projectAccessLabel(grants:readonly BrowserGrantSummary[]):string{
  if(grants.some(grant=>grant.maxMode==="write"))return "Read & edit permission saved";
  if(grants.length)return "Read permission saved";
  return "No AI app has project access";
}

function EmptyProjects({hasComputer}:Readonly<{hasComputer:boolean}>){
  return (<div className="card project-empty">
            <span className="project-emblem"><Icon name="projects" size={32}/></span>
            <span className="card-kicker">YOUR NEXT PROJECT STARTS HERE</span>
            <h2>{hasComputer?"Add your first KiCad project":"Connect your first computer"}</h2>
            <p>{hasComputer?"Choose a KiCad project folder on a connected computer. You decide which AI apps can access it.":
              "Pair the computer where you use KiCad, then choose the projects you want to work on with AI."}</p>
            <a className="button primary" href={hasComputer?"/devices#registered-projects":"/devices#connect-computer"}>
              {hasComputer?"Choose project":"Connect computer"}<Icon name="arrow" size={16}/></a>
            <span className="project-empty-note"><Icon name="lock" size={14}/> Signing in never shares your files.</span>
          </div>);
}

export function renderProjectsPage(
  devices:readonly Device[],projects:readonly Project[],clients:readonly string[]=[],
  savedGrants:readonly BrowserGrantSummary[]=[],enrollmentAvailable=true,
  sandboxMode=false,userEmail?:string
):string{
  const enabledDevices=devices.filter(d=>d.enabled&&!d.revoked);
  const activeProjects=projects.filter(p=>p.enabled&&enabledDevices.some(d=>d.id===p.deviceId));
  const currentGrants=savedGrants.filter(g=>clients.includes(g.clientId)&&activeProjects.some(p=>p.id===g.projectId));
  const steps=[
    {label:"Connect computer",done:enabledDevices.length>0,href:"/devices#connect-computer"},
    {label:"Choose project",done:activeProjects.length>0,href:"/devices#registered-projects"},
    {label:"Connect AI app",done:clients.length>0,href:"/connections#mcp-setup"},
    {label:"Approve access",done:currentGrants.length>0,href:"/devices#registered-projects"}
  ];
  return renderPage({title:"Projects",kind:"projects",eyebrow:"Your workspace",
    summary:"Your KiCad projects, connected computers and AI access. Pick up where you left off.",
    userEmail,actions:enrollmentAvailable?<a className="button primary" href={enabledDevices.length?"/devices#registered-projects":"/devices#connect-computer"}>
      <Icon name={enabledDevices.length?"projects":"devices"} size={17}/> {enabledDevices.length?"Add project":"Connect computer"}</a>:undefined,
    children:<div className="page-stack project-workspace">
      <script defer={true} src="/assets/pairing-login-continuation.js"></script>
      {sandboxMode?<output className="setup-next-step"><strong>Local development workspace</strong>
        <span>Sandbox account on this computer only. Real Cloud login and remote access are not active.</span></output>:null}
      {!enrollmentAvailable?<section className="card project-empty">
        <span className="project-emblem"><Icon name="lock" size={28}/></span>
        <h2>Project access is unavailable</h2><output>Device enrollment is not enabled on this deployment. Your local KiCad projects are unaffected.</output>
      </section>:<>
        <details className="workspace-setup" open={currentGrants.length===0}>
          <summary className="workspace-setup-summary"><span><Icon name="connections" size={17}/> Workspace setup</span>
            <span className="workspace-setup-progress">{steps.filter(step=>step.done).length} of 4 steps saved <Icon name="arrow" size={15}/></span></summary>
          <div className="setup-heading"><p>Connect your computer and AI app, then approve project access. Each permission stays in your control.</p></div>
          <ol className="workspace-steps">{steps.map((step,index)=><li key={step.label}>
            <a href={step.href} className={step.done?"workspace-step complete":"workspace-step"}>
              <span className="workspace-step-number" aria-label={step.done?"Saved":undefined}>
                {step.done?<Icon name="check" size={15}/>:String(index+1).padStart(2,"0")}</span>
              <span>{step.label}</span><Icon name="arrow" size={14}/>
            </a></li>)}</ol>
        </details>
        <section aria-labelledby="project-collection-title">
          <div className="project-collection-heading"><div><span className="card-kicker">PROJECT LIBRARY</span>
            <h2 id="project-collection-title">Your projects <span className="project-count">{projects.length}</span></h2></div>
            <a className="text-link" href="/devices">Manage computers <Icon name="arrow" size={15}/></a></div>
          {projects.length?<ul className="project-collection">{projects.map(project=>{
            const device=devices.find(d=>d.id===project.deviceId);
            const grants=currentGrants.filter(g=>g.projectId===project.id);
            const state=projectState(project,device,clients,grants);
            return <li key={project.id} className="project-work-card" data-project-state={state.id}>
              <div className="project-card-top"><span className="project-emblem"><Icon name="cpu" size={24}/></span>
                <span className={"status-pill "+state.tone}>{state.label}</span></div>
              <h3>{project.alias}</h3>
              <p className="project-computer"><Icon name="devices" size={14}/>{device?.alias??"Computer unavailable"}</p>
              <p className="project-next-step">{state.detail}</p>
              <div className="project-access-summary"><Icon name="shield" size={15}/>
                <span>{projectAccessLabel(grants)}</span></div>
              <div className="project-card-actions"><a className="button secondary" href={state.href}>
                {state.action}<Icon name="arrow" size={15}/></a>
                {state.href!=="/devices#project-"+project.id?<a className="text-link" href={"/devices#project-"+project.id}>Manage project</a>:null}</div>
            </li>;
          })}</ul>:<EmptyProjects hasComputer={enabledDevices.length>0}/>}
        </section>
        <aside className="project-workspace-note"><Icon name="shield" size={18}/><p>
          Saving edit permission does not enable Cloud editing by itself. Your AI app shows the operations available for each project.
          You can review or remove an app's access at any time.</p></aside>
      </>}
    </div>});
}
