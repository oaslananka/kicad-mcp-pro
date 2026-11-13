import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
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

export function renderDevicesPage(
  devices:ReadonlyArray<ManagedDevice & {csrf:string;deleteCsrf?:string;enableCsrf?:string;projectCsrf?:string;browseCsrf?:string;
    connectionState?:"connected"|"disconnected"}>,
  notice?:string,enrollmentAvailable=true,
  projects:ReadonlyArray<{id:string;deviceId:string;alias:string;enabled:boolean;localPath?:string;deleteCsrf?:string;renameCsrf?:string;grantCsrf?:string;
    managedEnabled?:boolean;managedCsrf?:string}>=[],
  ownerSub?:string,clients:ReadonlyArray<string>=[],
  savedGrants:ReadonlyArray<BrowserGrantSummary>=[],sandboxMode=false,browseEnabled=false
):string {
  const deviceNames=new Map(devices.map(d=>[d.id,d.alias]));
  const renderProjectAccess=(project:(typeof projects)[number])=><>
                <details className="project-access-details">
                  <summary>Manage access</summary>
                  <p className="field-help">Choose which AI apps may read this project's summary.
                    Remote editing is not available in this Cloud version.</p>
                {project.grantCsrf&&savedGrants.some(g=>g.projectId===project.id)?
                  <div className="project-grants">
                    <strong>Applications with access</strong>
                    <ul>{savedGrants.filter(g=>g.projectId===project.id).map(g=><li key={g.clientId}>
                      <span className="grant-client">{clientDisplayName(g.clientId)}</span>{" "}
                      <span className="permission-tag">{g.maxMode==="readonly"?"Read only":
                        g.maxMode==="write"?"Edit configured (not active)":
                        "Other permission (not remote editing)"}</span>
                      <form method="post" action="/devices/projects/grant">
                        <input type="hidden" name="project_id" value={project.id}/>
                        <input type="hidden" name="client_id" value={g.clientId}/>
                        <input type="hidden" name="csrf" value={project.grantCsrf}/>
                        <button className="button danger" type="submit" name="enabled" value="false">
                          Remove this app access
                        </button>
                      </form>
                    </li>)}</ul>
                  </div>:null}

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

                {project.enabled&&project.grantCsrf&&clients.some(client=>!savedGrants.some(
                  g=>g.projectId===project.id&&g.clientId===client))?
                  <form method="post" action="/devices/projects/grant">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="csrf" value={project.grantCsrf}/>
                    <label>AI application{" "}
                      <select name="client_id" required={true}>
                        {clients.filter(client=>!savedGrants.some(g=>
                          g.projectId===project.id&&g.clientId===client)).map(
                            client=><option value={client} key={client}>{clientDisplayName(client)}</option>)}
                      </select>
                    </label>
                    <div className="action-row">
                      <button className="button primary" name="enabled" value="true" type="submit">Allow project summary</button>
                    </div>
                  </form>:null}
                </details>
  </>;

  return renderPage({title:"Devices",kind:"devices",eyebrow:"Workspace / Devices",
    summary:"Machines your AI clients can reach through KiCad MCP Cloud.",
    actions:enrollmentAvailable?<a className="button primary device-add-button" href="#connect-computer">
      <span className="device-add-plus" aria-hidden="true">+</span> Add a device
    </a>:null,
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}

      {!enrollmentAvailable && devices.length===0?<section className="card status-card" id="registered-projects"><div className="status-message">
        <span className="status-pill pending">Not enabled</span>
        <h2>Local KiCad devices aren't available yet</h2>
        <p>Device enrollment and management are not enabled on this deployment. No pairing or local project control is available. The device schema and recovery checks must be approved before activation.</p>
        <div className="state-detail">
          <div><span>Cloud account</span><small>Available</small></div>
          <div><span>Device enrollment</span><small>Not enabled</small></div>
          <div><span>Remote KiCad execution</span><small>Not enabled</small></div>
        </div>
      </div></section>:
        <>
      {/* Enrolled Devices Section */}
      <section className="card device-card device-list-card" aria-labelledby="device-list-title">
        <div className="card-header">
          <h2 id="device-list-title">Your devices</h2>
          <span className="list-count">{devices.length===1?"1 device":String(devices.length)+" devices"}</span>
        </div>
        {devices.length===0?<div className="empty-state">
          <div className="empty-icon"><Icon name="devices" size={21}/></div>
          <div>
            <h3>No devices yet</h3>
            <p>{sandboxMode?"Connect this computer with the local development Connector.":
              "Run kicad-mcp-pro remote on your computer to connect."}</p>
          </div>
        </div>:
          <ul className="connections-list device-list">{devices.map(d=><li className="device-row" key={d.id}>
            <span className={d.enabled&&!d.revoked&&d.connectionState==="connected"?"device-dot connected":"device-dot"} aria-hidden="true"/>
            <div className="device-summary">
              <h3>{d.alias}</h3>
              <p>{d.revoked?"Revoked":!d.enabled?"Disabled":
                d.connectionState==="connected"?"Cloud session active":
                d.connectionState==="disconnected"?
                  (sandboxMode?"Local Connector disconnected":"Run kicad-mcp-pro remote to connect"):
                "Cloud status unknown"}</p>
            </div>
            <div className="device-actions">
              <span role="status" aria-label={d.revoked?"Revoked":!d.enabled?"Disabled":
                d.connectionState==="connected"?"Connected":d.connectionState==="disconnected"?"Offline":"Status unknown"}
                className={d.revoked?"status-pill danger":d.enabled&&d.connectionState==="connected"?
                  "status-pill ready":"status-pill neutral"}>
                {d.revoked?"Revoked":!d.enabled?"Disabled":d.connectionState==="connected"?"Online":d.connectionState==="disconnected"?"Offline":"Status unknown"}
              </span>
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
            </div>
            {d.enabled&&!d.revoked&&browseEnabled?
              <details className="device-projects-menu" data-device-id={d.id} open={true}>
                <summary><Icon name="projects" size={15}/> Projects
                  <span>{projects.filter(p=>p.deviceId===d.id).length}</span>
                </summary>
                <div className="device-projects-content">
                  {projects.filter(p=>p.deviceId===d.id).map(p=>
                    <div className="device-linked-project" key={p.id}>
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
                        {renderProjectAccess(p)}
                      </div>
                      {p.renameCsrf?<dialog className="project-action-dialog project-rename-dialog"
                        id={"project-rename-"+p.id} aria-labelledby={"project-rename-title-"+p.id}>
                        <h3 id={"project-rename-title-"+p.id}>Rename project</h3>
                        <p>Change the name in Cloud. The local KiCad files stay unchanged.</p>
                        <form action="/devices/projects/rename" method="post">
                          <input type="hidden" name="project_id" value={p.id}/>
                          <input type="hidden" name="csrf" value={p.renameCsrf}/>
                          <label>Project name
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
                    </div>)}
                  {d.browseCsrf?<form action="/devices/projects/browse" method="post"
                    className="device-native-browse-form">
                    <input type="hidden" name="device_id" value={d.id}/>
                    <input type="hidden" name="csrf" value={d.browseCsrf}/>
                    <button className="button project-browse-link" type="submit">
                      <span aria-hidden="true">+</span> Add project · Browse
                      <Icon name="arrow" size={15}/>
                    </button>
                  </form>:null}
                </div>
              </details>:null}
          </li>)}</ul>}
        <div className="device-list-footer">
          Your projects and permissions are managed under each device.
        </div>
      </section>

      {/* Quickstart / Pairing Guidance */}
      {devices.length===0?<section className="card quickstart-card" id="connect-computer">
        <div className="card-kicker"><Icon name="cpu" size={15}/> PAIR YOUR COMPUTER</div>
        <h2>Connect your computer</h2>
        {sandboxMode?<><p>Local development only. This workspace only accepts
          connections from this computer. Its existing Connector is configured locally.</p>
          <a className="text-link" href="/devices">Review connected devices</a></>:
          <><p>Run this once to pair your computer and keep the Cloud session open:</p>
            <div className="local-setup-command"><code>kicad-mcp-pro remote</code></div>
            <p className="field-help">Choose your KiCad folder in the native picker when prompted.</p></>}
      </section>:
      <section className="card pair-another-card" id="connect-computer">
        <h2><Icon name="cpu" size={16}/> Connect another computer</h2>
        <div className="pair-another-content">
          {sandboxMode?<p>Local development only. This Cloud instance accepts connections
            from this computer (127.0.0.1). Additional computers need a separate
            network-enabled Cloud setup; remote pairing is unavailable here.</p>:
          <><p>On your other computer, run:</p>
            <div className="local-setup-command"><code>kicad-mcp-pro remote</code></div>
            <p className="field-help">Approve the browser pairing once; future connections reuse it.</p></>}
        </div>
      </section>}

                {/* Registered Projects Section */}
          {!sandboxMode?<section className={projects.length>0?"card projects-card":"card projects-card empty-projects-card"} id="registered-projects">
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
            {projects.length>0?<>
              <ul className="connections-list">{projects.map(project=><li className="project-item" key={project.id}>
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

                {renderProjectAccess(project)}
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
            </>:<div className="project-empty">
              <h3>No KiCad projects yet</h3>
              <p>{sandboxMode?"Project selection comes next. No local project is shared yet.":
                <>Run <code>kicad-mcp-pro remote</code> on your computer to choose a project.</>}</p>
            </div>}

          </section>:null}
        </>}

      {/* Where you use it: Application Shortcuts */}
      <section className="card client-shortcuts">
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
      </section>

      {/* Advanced Identity Inspection */}
      {enrollmentAvailable&&ownerSub&&!sandboxMode?<details className="advanced-identity">
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
      </details>:null}
       {sandboxMode?<script src="/assets/device-projects.js" defer={true}/>:null}
    </div>
  });
}
