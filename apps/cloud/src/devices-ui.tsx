import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import {CopyValue} from "./copy-value.js";
import type {ManagedDevice} from "./device-management.js";
import type {BrowserGrantSummary} from "./grants.js";

function clientDisplayName(clientId:string):string {
  try{
    const host=new URL(clientId).hostname.toLowerCase();
    if(host==="chatgpt.com")return "ChatGPT";
    if(host==="claude.ai")return "Claude";
    return host;
  }catch{
    return clientId;
  }
}

const NATIVE_DIAGNOSTICS=[
  {id:"run_drc",label:"PCB DRC counts",detail:"Issue and unconnected-item totals from the local board"}
] as const;

type Device=ManagedDevice & {csrf:string;deleteCsrf?:string;enableCsrf?:string;projectCsrf?:string;browseCsrf?:string;
  connectionState?:"connected"|"disconnected";browseNeedsUpgrade?:boolean};
type Project={id:string;deviceId:string;alias:string;enabled:boolean;localPath?:string;deleteCsrf?:string;renameCsrf?:string;grantCsrf?:string;
  managedEnabled?:boolean;managedCsrf?:string;nativeEnabled?:ReadonlyArray<string>;nativeCsrf?:string};
export type DevicePageOptions=Readonly<{
  projects?:ReadonlyArray<Project>;ownerSub?:string;clients?:ReadonlyArray<string>;
  savedGrants?:ReadonlyArray<BrowserGrantSummary>;sandboxMode?:boolean;browseEnabled?:boolean;
  writeClients?:ReadonlyArray<string>;userEmail?:string;
}>;
type ViewContext=Readonly<{
  devices:ReadonlyArray<Device>;projects:ReadonlyArray<Project>;enrollmentAvailable:boolean;
  ownerSub?:string;clients:ReadonlyArray<string>;savedGrants:ReadonlyArray<BrowserGrantSummary>;
  sandboxMode:boolean;browseEnabled:boolean;writeClients:ReadonlyArray<string>;
}>;

function grantModeLabel(mode:BrowserGrantSummary["maxMode"]):string{
  if(mode==="readonly")return "Read only";
  if(mode==="write")return "Edit permission saved ? remote editing not active";
  return "Other permission (not remote editing)";
}
function SavedProjectGrants({project,grants,writeClients}:Readonly<{
  project:Project;grants:ReadonlyArray<BrowserGrantSummary>;writeClients:ReadonlyArray<string>;
}>){
  if(!project.grantCsrf||grants.length===0)return null;
  return (                  <div className="project-grants">
                    <strong>Applications with access</strong>
                    <ul>{grants.map(g=><li key={g.clientId}>
                      <span className="grant-client">{clientDisplayName(g.clientId)}</span>{" "}
                      <span className="permission-tag">{grantModeLabel(g.maxMode)}</span>
                      {project.grantCsrf&&g.maxMode==="readonly"&&writeClients.includes(g.clientId)?
                        <form method="post" action="/devices/projects/grant">
                          <input type="hidden" name="project_id" value={project.id}/>
                          <input type="hidden" name="client_id" value={g.clientId}/>
                          <input type="hidden" name="csrf" value={project.grantCsrf}/>
                          <input type="hidden" name="mode" value="write"/>
                          <button className="button secondary" type="submit"
                            name="enabled" value="true">Allow editing</button>
                        </form>:null}
                      {project.grantCsrf&&g.maxMode==="write"?
                        <form method="post" action="/devices/projects/grant">
                          <input type="hidden" name="project_id" value={project.id}/>
                          <input type="hidden" name="client_id" value={g.clientId}/>
                          <input type="hidden" name="csrf" value={project.grantCsrf}/>
                          <input type="hidden" name="mode" value="readonly"/>
                          <button className="button secondary" type="submit"
                            name="enabled" value="true">Keep read only</button>
                        </form>:null}
                      <form method="post" action="/devices/projects/grant">
                        <input type="hidden" name="project_id" value={project.id}/>
                        <input type="hidden" name="client_id" value={g.clientId}/>
                        <input type="hidden" name="csrf" value={project.grantCsrf}/>
                        <button className="button danger" type="submit" name="enabled" value="false">
                          Remove this app access
                        </button>
                      </form>
                    </li>)}</ul>
                  </div>);
}
function ProjectDiagnostics({project}:Readonly<{project:Project}>){
  if(!project.enabled||!project.managedEnabled||!project.nativeCsrf)return null;
  return (                  <details className="project-native-access">
                    <summary>Read-only KiCad diagnostics</summary>
                    <p className="field-help">Only the bounded PCB DRC totals pilot is available here. The installed
                      Connector must be started by the device owner with native DRC explicitly
                      allowed, and the AI application needs its own read grant. Other KiCad
                      diagnostics are not available through managed Cloud yet. No edits or raw
                      KiCad project contents are permitted.</p>
                    <div className="project-native-operations">
                      {NATIVE_DIAGNOSTICS.map(item=>{
                        const enabled=project.nativeEnabled?.includes(item.id)===true;
                        return <form action="/devices/projects/native" method="post"
                          className="project-native-operation" key={item.id}>
                          <input type="hidden" name="project_id" value={project.id}/>
                          <input type="hidden" name="device_id" value={project.deviceId}/>
                          <input type="hidden" name="operation" value={item.id}/>
                          <input type="hidden" name="csrf" value={project.nativeCsrf}/>
                          <div><strong>{item.label}</strong>
                            <small className="field-help">{item.detail}</small></div>
                          <button className="button secondary" type="submit" name="enabled"
                            value={enabled?"false":"true"}>
                            {enabled?"Disable":"Enable"}
                          </button>
                        </form>;
                      })}
                    </div>
                  </details>);
}

function ProjectAccess({project,context}:Readonly<{project:Project;context:ViewContext}>){
  const {clients,writeClients,savedGrants}=context;
  const projectGrants=savedGrants.filter(grant=>grant.projectId===project.id);
  const grantedClients=new Set(projectGrants.map(grant=>grant.clientId));
  const availableClients=clients.filter(client=>!grantedClients.has(client));
  const availableWriters=writeClients.filter(client=>!grantedClients.has(client));
  return (                <details className="project-access-details">
                  <summary>Manage access</summary>
                  <p className="field-help">Choose exactly which AI clients may read or edit
                    this project. New access is read-only; editing requires a separate
                    OAuth write consent and an explicit per-app grant. Cloud editing is
                    not active until a compatible Connector and the write service are available.</p>
                <SavedProjectGrants project={project} grants={projectGrants} writeClients={writeClients}/>

                {project.enabled&&project.managedCsrf?<>
                  <p>Project summary access: {project.managedEnabled?"Enabled":"Paused"}</p>
                  <form method="post" action="/devices/projects/managed">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="device_id" value={project.deviceId}/>
                    <input type="hidden" name="csrf" value={project.managedCsrf}/>
                    <button className="button secondary" name="enabled" value={project.managedEnabled?"false":"true"} type="submit">
                      {project.managedEnabled?"Pause project reads":"Enable project reads"}
                    </button>
                  </form>
                </>:null}

                <ProjectDiagnostics project={project}/>

                {project.enabled&&project.grantCsrf&&availableClients.length>0?
                  <form method="post" action="/devices/projects/grant">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="csrf" value={project.grantCsrf}/>
                    <label>AI application{" "}
                      <select name="client_id" required={true}>
                        {availableClients.map(client=><option value={client} key={client}>{clientDisplayName(client)}</option>)}
                      </select>
                    </label>
                    <div className="action-row">
                      <button className="button primary" name="enabled" value="true"
                        type="submit">Allow reading</button>
                    </div>
                  </form>:null}
                {project.enabled&&project.grantCsrf&&availableWriters.length>0?
                  <form method="post" action="/devices/projects/grant">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="csrf" value={project.grantCsrf}/>
                    <input type="hidden" name="mode" value="write"/>
                    <label>AI application approved for editing{" "}
                      <select name="client_id" required={true}>
                        {availableWriters.map(client=><option value={client} key={client}>{clientDisplayName(client)}</option>)}
                      </select>
                    </label>
                    <p className="field-help">This saves a separate write permission.
                      It does not enable remote editing until the Connector supports it.</p>
                    <button className="button secondary" name="enabled" value="true"
                      type="submit">Allow reading and editing</button>
                  </form>:null}
                </details>);
}

function deviceStatus(device:Device,sandboxMode:boolean){
  if(device.revoked)return {label:"Revoked",description:"Revoked",ariaLabel:"Revoked",tone:"danger",online:false};
  if(!device.enabled)return {label:"Disabled",description:"Disabled",ariaLabel:"Disabled",tone:"neutral",online:false};
  if(device.connectionState==="connected")return {label:"Online",description:"Cloud session active",ariaLabel:"Connected",tone:"ready",online:true};
  if(device.connectionState==="disconnected"){
    const description=sandboxMode?"Local Connector disconnected":"Run kicad-mcp-pro cloud reconnect to restore the background connection";
    return {label:"Offline",description,ariaLabel:"Offline",tone:"neutral",online:false};
  }
  return {label:"Status unknown",description:"Cloud status unknown",ariaLabel:"Status unknown",tone:"neutral",online:false};
}
function DeviceActions({device:d,enrollmentAvailable,state}:Readonly<{
  device:Device;enrollmentAvailable:boolean;state:ReturnType<typeof deviceStatus>;
}>){
  return <div className="device-actions">
    <output aria-label={state.ariaLabel} className={"status-pill "+state.tone}>{state.label}</output>
              {enrollmentAvailable&&!d.revoked&&!d.enabled&&d.enableCsrf?
                <form action="/devices/enable" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.enableCsrf}/>
                  <button className="button secondary" type="submit">Enable my device</button>
                </form>:null}
              {d.revoked&&d.deleteCsrf?
                <form action="/devices/delete" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.deleteCsrf}/>
                  <button className="button device-remove-button" type="submit"
                    title="Permanently remove this revoked device and its Cloud project records">
                    Remove device permanently
                  </button>
                </form>:null}
              {!d.revoked&&d.enabled&&d.connectionState==="disconnected"?
                <a className="button device-reconnect-button" href="#connect-computer"
                  title="View instructions to reconnect this computer">Reconnect</a>:null}
              {!d.revoked?
                <form action="/devices/revoke" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.csrf}/>
                  <button className="button device-revoke-button" type="submit"
                    title="Revoke this device and disable its project access">Revoke</button>
                </form>:null}
  </div>;
}

function LinkedProject({project:p,device:d,context}:Readonly<{project:Project;device:Device;context:ViewContext}>){
  return (<div className="device-linked-project" id={"project-"+p.id}>
                      <div className="device-project-main">
                        <div className="device-project-title">
                          <Icon name="projects" size={17}/>
                          <strong>{p.alias}</strong>
                        </div>
                        <div className="device-project-location">
                          <span>On this computer</span>
                          {p.localPath?<code className="device-project-path" title={p.localPath}>
                            {p.localPath}</code>:
                            <small>{d.connectionState!=="connected"?
                              "Device offline · path unavailable":
                              "Local path unavailable · reconnect or reselect project"}</small>}
                        </div>
                      </div>
                      <div className="device-project-toolbar">
                        {p.renameCsrf?<button type="button"
                          className="button project-rename-trigger"
                          data-open-project-dialog={"project-rename-"+p.id}>Rename</button>:null}
                        {p.deleteCsrf?<button type="button"
                          className="button project-remove-trigger"
                          data-open-project-dialog={"project-remove-"+p.id}>Remove</button>:null}
                      </div>
                      <div className="device-project-permissions">
                        <ProjectAccess project={p} context={context}/>
                      </div>
                      {p.renameCsrf?<dialog className="project-action-dialog project-rename-dialog"
                        id={"project-rename-"+p.id} aria-labelledby={"project-rename-title-"+p.id}>
                        <h3 id={"project-rename-title-"+p.id}>Rename project</h3>
                        <p>Change the name in Cloud. The local KiCad files stay unchanged.</p>
                        <form action="/devices/projects/rename" method="post">
                          <input type="hidden" name="project_id" value={p.id}/>
                          <input type="hidden" name="csrf" value={p.renameCsrf}/>
                          <label>Project name{" "}
                            <input name="alias" required={true} maxLength={64}
                              defaultValue={p.alias}/>
                          </label>
                          <div className="project-dialog-actions">
                            <button className="button secondary" type="button"
                              data-close-project-dialog={true}>Cancel</button>
                            <button className="button primary" type="submit">Save name</button>
                          </div>
                        </form>
                      </dialog>:null}
                      {p.deleteCsrf?<dialog className="project-action-dialog project-remove-dialog"
                        id={"project-remove-"+p.id} aria-labelledby={"project-remove-title-"+p.id}>
                        <h3 id={"project-remove-title-"+p.id}>Remove project?</h3>
                        <p><strong>{p.alias}</strong> will be removed from Cloud
                          together with its access permissions. The KiCad files
                          on your computer will not be deleted.</p>
                        <form action="/devices/projects/delete" method="post">
                          <input type="hidden" name="project_id" value={p.id}/>
                          <input type="hidden" name="csrf" value={p.deleteCsrf}/>
                          <div className="project-dialog-actions">
                            <button className="button secondary" type="button"
                              data-close-project-dialog={true}>Cancel</button>
                            <button className="button danger" type="submit">
                              Remove project
                            </button>
                          </div>
                        </form>
                      </dialog>:null}
                    </div>);
}
function DeviceProjects({device:d,context}:Readonly<{device:Device;context:ViewContext}>){
  const {projects,browseEnabled}=context;
  if(!d.enabled||d.revoked||!browseEnabled)return null;
  const localProjects=projects.filter(project=>project.deviceId===d.id);
  return (<details className="device-projects-menu" data-device-id={d.id} open={true}>
                <summary><Icon name="projects" size={15}/> Projects
                  <span>{localProjects.length}</span>
                </summary>
                <div className="device-projects-content">
                  {localProjects.map(project=><LinkedProject key={project.id} project={project} device={d} context={context}/>)}
                  {d.browseCsrf?<form action="/devices/projects/browse" method="post"
                    className="device-native-browse-form">
                    <input type="hidden" name="device_id" value={d.id}/>
                    <input type="hidden" name="csrf" value={d.browseCsrf}/>
                    <button className="button project-browse-link" type="submit">
                      <span aria-hidden="true">+</span> Add project · Browse
                      <Icon name="arrow" size={15}/>
                    </button>
                  </form>:null}
                  {d.browseNeedsUpgrade?<p className="field-help">
                    Update the KiCad MCP Pro Connector on this computer to
                    add projects by browsing local folders. This device is Online,
                    but its current Connector does not support remote Browse.
                  </p>:null}
                </div>
              </details>);
}
function DeviceRow({device,context}:Readonly<{device:Device;context:ViewContext}>){
  const state=deviceStatus(device,context.sandboxMode);
  return <li className="device-row">
    <span className={state.online?"device-dot connected":"device-dot"} aria-hidden="true"/>
    <div className="device-summary"><h3>{device.alias}</h3><p>{state.description}</p></div>
    <DeviceActions device={device} enrollmentAvailable={context.enrollmentAvailable} state={state}/>
    <DeviceProjects device={device} context={context}/>
  </li>;
}

function DeviceList({context}:Readonly<{context:ViewContext}>){
  const {devices,browseEnabled,sandboxMode}=context;
  return (      <section className="card device-card device-list-card"
        id={browseEnabled?"registered-projects":undefined} aria-labelledby="device-list-title">
        <div className="card-header">
          <h2 id="device-list-title">Your devices</h2>
          <span className="list-count">{devices.length===1?"1 device":String(devices.length)+" devices"}</span>
        </div>
        {devices.length===0?<div className="empty-state">
          <div className="empty-icon"><Icon name="devices" size={21}/></div>
          <div>
            <h3>No devices yet</h3>
            <p>{sandboxMode?"Connect this computer with the local development Connector.":
              "Run kicad-mcp-pro cloud setup --browse on your computer to connect."}</p>
          </div>
        </div>:
          <ul className="connections-list device-list">{devices.map(device=><DeviceRow key={device.id} device={device} context={context}/>)}</ul>}
        <div className="device-list-footer">
          Your projects and permissions are managed under each device.
        </div>
      </section>);
}

function PairingSetup({context}:Readonly<{context:ViewContext}>){
  const {devices,sandboxMode}=context;
  return (devices.length===0?<section className="card quickstart-card" id="connect-computer">
        <div className="card-kicker"><Icon name="cpu" size={15}/> PAIR YOUR COMPUTER</div>
        <h2>Connect your computer</h2>
        {sandboxMode?<><p>Local development only. This workspace only accepts
          connections from this computer. Its existing Connector is configured locally.</p>
          <a className="text-link" href="/devices">Review connected devices</a></>:
          <><p>Run this once on your Windows computer. Choose your KiCad folder,
              then sign-in and approve pairing in the browser.</p>
            <CopyValue value="kicad-mcp-pro cloud setup --browse" label="setup command"/>
            <p className="field-help">The read-only Connector reconnects when you sign in to Windows.
              You do not need to keep a terminal open. AI app access is granted separately.</p></>}
      </section>:
      <section className="card pair-another-card" id="connect-computer">
        <h2><Icon name="cpu" size={16}/> Connect another computer</h2>
        <div className="pair-another-content">
          {sandboxMode?<p>Local development only. This Cloud instance accepts connections
            from this computer (127.0.0.1). Additional computers need a separate
            network-enabled Cloud setup; remote pairing is unavailable here.</p>:
          <><p>On your other Windows computer, select its KiCad folder,
              then sign-in and approve pairing in the browser:</p>
            <CopyValue value="kicad-mcp-pro cloud setup --browse" label="setup command"/>
            <p className="field-help">The Connector reconnects at Windows sign-in.
              Existing paired devices can use <code>kicad-mcp-pro cloud reconnect</code>{" "}
              if their background connection stops.</p></>}
        </div>
      </section>);
}
function RegisteredProjects({context}:Readonly<{context:ViewContext}>){
  const {devices,projects,enrollmentAvailable,sandboxMode,browseEnabled}=context;
  if(sandboxMode||browseEnabled)return null;
  const deviceNames=new Map(devices.map(device=>[device.id,device.alias]));
  return (<section className={projects.length>0?"card projects-card":"card projects-card empty-projects-card"} id="registered-projects">
            <h2>Your projects</h2>
            {enrollmentAvailable&&!sandboxMode?devices.filter(d=>!d.revoked&&d.enabled&&d.projectCsrf).map(d=>
              <details className="device-register" key={d.id}>
                <summary>Advanced: register a project name</summary>
                <p className="field-help">This registers a Cloud name only;
                  it does not select a folder on your computer.</p>
                <form action="/devices/projects/create" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.projectCsrf}/>
                  <label>Project name or alias{" "}
                    <input name="alias" maxLength={64} required={true} autoComplete="off"
                      placeholder="e.g. Feather-M4 or Motor-Driver"/>
                  </label>
                  <button className="button secondary" type="submit">Register project name</button>
                </form>
              </details>):null}
            {projects.length>0?
              <ul className="connections-list">{projects.map(project=><li className="project-item" id={"project-"+project.id} key={project.id}>
                <strong>{project.alias}</strong>
                {project.renameCsrf?<details className="project-rename">
                  <summary>Rename project</summary>
                  <form action="/devices/projects/rename" method="post">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="csrf" value={project.renameCsrf}/>
                    <label>Project name <input name="alias" required={true} maxLength={64}
                      defaultValue={project.alias}/></label>
                    <button className="button secondary" type="submit">Save name</button>
                  </form>
                </details>:null}
                <p>On device: {deviceNames.get(project.deviceId)??"Previously registered device"}.
                  {project.enabled?" Registered.":" Disabled."}</p>

                <ProjectAccess project={project} context={context}/>
                {project.deleteCsrf?
                  <details className="device-advanced project-delete">
                    <summary>Remove project from Cloud</summary>
                    <p className="field-help">This removes the project and its AI app permissions from Cloud.
                      It does not delete files on your computer.</p>
                    <form action="/devices/projects/delete" method="post">
                      <input type="hidden" name="project_id" value={project.id}/>
                      <input type="hidden" name="csrf" value={project.deleteCsrf}/>
                      <button type="submit" className="button danger">Remove project from Cloud</button>
                    </form>
                  </details>:null}
              </li>)}</ul>
            :<div className="project-empty">
              <h3>No KiCad projects yet</h3>
              <p>{sandboxMode?"Project selection comes next. No local project is shared yet.":
                <>Use <code>kicad-mcp-pro cloud setup --browse</code> on your
                  computer to pair it. Then choose a project using Browse on its Online card.</>}</p>
            </div>}

          </section>);
}
function UnavailableDevices(){
  return (<section className="card status-card" id="registered-projects"><div className="status-message">
        <span className="status-pill pending">Not enabled</span>
        <h2>Local KiCad devices aren't available yet</h2>
        <p>Device enrollment and management are not enabled on this deployment. No pairing or local project control is available. The device schema and recovery checks must be approved before activation.</p>
        <div className="state-detail">
          <div><span>Cloud account</span><small>Available</small></div>
          <div><span>Device enrollment</span><small>Not enabled</small></div>
          <div><span>Remote KiCad execution</span><small>Not enabled</small></div>
        </div>
      </div></section>);
}
function DeviceContents({context}:Readonly<{context:ViewContext}>){
  if(!context.enrollmentAvailable&&context.devices.length===0)return <UnavailableDevices/>;
  return <><DeviceList context={context}/><PairingSetup context={context}/><RegisteredProjects context={context}/></>;
}
function ClientShortcuts(){
  return (      <section className="card client-shortcuts">
        <h2>Where you use it</h2>
        <p>Connect your preferred AI client, then grant it access to a registered project.</p>
        <ul>
          <li><a className="client-shortcut-link" href="/connections" aria-label="Set up ChatGPT">
            <span className="client-icon"><Icon name="connections" size={20}/></span>
            <span><strong>ChatGPT</strong><small>Review remote MCP connection settings.</small></span>
            <b>Set up <Icon name="arrow" size={14}/></b></a></li>
          <li><a className="client-shortcut-link" href="/connections" aria-label="Set up Claude">
            <span className="client-icon"><Icon name="spark" size={20}/></span>
            <span><strong>Claude</strong><small>Review connector permissions and setup.</small></span>
            <b>Set up <Icon name="arrow" size={14}/></b></a></li>
          <li><a className="client-shortcut-link" href="/connections" aria-label="Set up another MCP client">
            <span className="client-icon"><Icon name="cpu" size={20}/></span>
            <span><strong>Other MCP clients</strong><small>Check endpoint details and authentication.</small></span>
            <b>Details <Icon name="arrow" size={14}/></b></a></li>
        </ul>
      </section>);
}

function AdvancedIdentity({context}:Readonly<{context:ViewContext}>){
  const {enrollmentAvailable,ownerSub,sandboxMode,projects,devices}=context;
  if(!enrollmentAvailable||!ownerSub||sandboxMode)return null;
  return (<details className="advanced-identity">
        <summary>Advanced: local Connector account ID</summary>
        <p>Only needed when configuring the local Connector manually: <code>{ownerSub}</code></p>
        {(/^[A-Za-z0-9_.:@-]{1,256}$/.test(ownerSub))?
          projects.filter(project=>/^[0-9a-f-]{36}$/i.test(project.id)&&
            /^[0-9a-f-]{36}$/i.test(project.deviceId)&&
            devices.some(d=>d.id===project.deviceId&&d.enabled&&!d.revoked)).map(project=>
            <div key={project.id} className="local-setup-command">
              <strong>{project.alias}</strong>
              <p>Run on your own computer from a terminal using the latest CLI.
                This only updates which local folder belongs to the paired device.
                It preserves the old record and asks before changing anything.</p>
              <code>{`kicad-mcp-pro cloud register-project --owner-sub '${ownerSub}' --device-id ${project.deviceId} --project-id ${project.id}`}</code>
              <p>Registration does not enable the Connector or grant client access.</p>
            </div>
          ):null}
      </details>);
}
export function renderDevicesPage(devices:ReadonlyArray<Device>,notice?:string,enrollmentAvailable=true,
  {projects=[],ownerSub,clients=[],savedGrants=[],sandboxMode=false,browseEnabled=false,writeClients=[],userEmail}:DevicePageOptions={}
):string{
  const context={devices,projects,enrollmentAvailable,ownerSub,clients,savedGrants,sandboxMode,browseEnabled,writeClients};
  return renderPage({title:"Devices",kind:"devices",eyebrow:"Workspace / Devices",userEmail,
    summary:"Machines your AI clients can reach through KiCad MCP Cloud.",
    actions:enrollmentAvailable?<a className="button primary device-add-button" href="#connect-computer">
      <span className="device-add-plus" aria-hidden="true">+</span> Add a device
    </a>:null,
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}
      <DeviceContents context={context}/>
      <ClientShortcuts/>
      <AdvancedIdentity context={context}/>
      {sandboxMode||browseEnabled?<script src="/assets/device-projects.js" defer={true}/>:null}
      {enrollmentAvailable&&!sandboxMode?<script src="/assets/copy-value.js" defer={true}/>:null}
    </div>});
}
