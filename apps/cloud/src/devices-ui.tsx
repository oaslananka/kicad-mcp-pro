import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import type {ManagedDevice} from "./device-management.js";
import type {BrowserGrantSummary} from "./grants.js";

export function renderDevicesPage(
  devices:ReadonlyArray<ManagedDevice & {csrf:string;deleteCsrf?:string;enableCsrf?:string;projectCsrf?:string;
    connectionState?:"connected"|"disconnected"}>,
  notice?:string,enrollmentAvailable=true,
  projects:ReadonlyArray<{id:string;deviceId:string;alias:string;enabled:boolean;grantCsrf?:string;
    managedEnabled?:boolean;managedCsrf?:string}>=[],
  ownerSub?:string,clients:ReadonlyArray<string>=[],
  savedGrants:ReadonlyArray<BrowserGrantSummary>=[]
):string {
  const deviceNames=new Map(devices.map(d=>[d.id,d.alias]));
  const hasDevices=devices.some(d=>d.enabled&&!d.revoked);
  const hasProjects=projects.some(p=>p.enabled);
  const hasClients=clients.length>0;
  const hasGrants=savedGrants.some(g=>projects.some(p=>p.id===g.projectId&&p.enabled)&&clients.includes(g.clientId));

  return renderPage({title:"Devices & projects",kind:"devices",eyebrow:"Workspace / Devices & projects",
    summary:"Computers your AI clients can reach, and the projects you choose to share.",
    actions:enrollmentAvailable?<a className="button primary" href="/devices/pairing"><span aria-hidden="true">+</span> Pair a device</a>:null,
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}

      {/* Guided 5-Stage Stepper with High-Contrast Statuses */}
      {enrollmentAvailable?<nav className="setup-progress" aria-label="Cloud setup progress">
        <div className="setup-progress-heading">
          <strong>Connection setup</strong>
          <span>Each layer requires its own approval. Nothing is shared by default.</span>
        </div>
        <ol>
          <li className="progress-complete">
            <span className="progress-number">01</span>
            <div><strong>Account</strong><small>Signed in</small></div>
          </li>
          <li className={hasDevices?"progress-complete":"progress-current"}>
            <span className="progress-number">02</span>
            <div><strong>Computer</strong><small>{hasDevices?"Device paired":"Pair your device"}</small></div>
          </li>
          <li className={hasProjects?"progress-complete":hasDevices?"progress-current":"progress-pending"}>
            <span className="progress-number">03</span>
            <div><strong>Project</strong><small>{hasProjects?"Project registered":"Choose a local folder"}</small></div>
          </li>
          <li className={hasClients?"progress-complete":hasProjects?"progress-current":"progress-pending"}>
            <span className="progress-number">04</span>
            <div><strong>AI client</strong><small>{hasClients?"Client connected":"Connect ChatGPT, Claude or another app"}</small></div>
          </li>
          <li className={hasGrants?"progress-complete":hasClients?"progress-current":"progress-pending"}>
            <span className="progress-number">05</span>
            <div><strong>Grant access</strong><small>{hasGrants?"Project permission saved":"Choose permissions per project and client"}</small></div>
          </li>
        </ol>
      </nav>:null}

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
      <section className="card device-card">
        <div className="card-header">
          <div>
            <span className="card-kicker">COMPUTERS</span>
            <h2>Your devices</h2>
          </div>
          <span className="list-count">{devices.length===1?"1 enrolled device":`${devices.length} enrolled devices`}</span>
        </div>
        {devices.length===0?<div className="empty-state">
          <div className="empty-icon"><Icon name="devices" size={21}/></div>
          <div>
            <h3>No enrolled devices</h3>
            <p>Run <code>kicad-mcp-pro cloud setup</code> on your computer to connect.</p>
          </div>
        </div>:
          <ul className="connections-list device-list">{devices.map(d=><li className="device-row" key={d.id}>
            <span className={d.enabled&&!d.revoked&&d.connectionState==="connected"?"device-dot connected":"device-dot"} aria-hidden="true"/>
            <div className="device-summary">
              <h3>{d.alias}</h3>
              <p>{d.revoked?"Revoked":!d.enabled?"Disabled":
                d.connectionState==="connected"?
                  "Connector connected now (temporary session; not proof of KiCad activity)":
                d.connectionState==="disconnected"?"Connector not connected now":
                  "Enabled (not proof of online status)"}</p>
            </div>
            <div className="device-actions">
              <span className={d.enabled&&!d.revoked&&d.connectionState==="connected"?"status-pill ready":"status-pill neutral"}>
                {d.revoked?"Revoked":!d.enabled?"Disabled":d.connectionState==="connected"?"Connected":d.connectionState==="disconnected"?"Offline":"Status unknown"}
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
                  <button className="button danger" type="submit"
                    title="Permanently delete this revoked device and its registered projects">
                    Remove device permanently
                  </button>
                </form>:null}
              {d.revoked?<span className="status-pill pending">Revoked</span>:
                <form action="/devices/revoke" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.csrf}/>
                  <button className="button danger" type="submit">Revoke device</button>
                </form>}
            </div>
            {enrollmentAvailable&&!d.revoked&&d.enabled&&d.projectCsrf?
              <details className="device-register">
                <summary>+ Register a project</summary>
                <form action="/devices/projects/create" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.projectCsrf}/>
                  <label>Project name or alias{" "}
                    <input name="alias" maxLength={64} required={true} autoComplete="off" placeholder="e.g. Feather-M4 or Motor-Driver"/>
                  </label>
                  <button className="button secondary" type="submit">Register read-only project</button>
                </form>
              </details>:null}
          </li>)}</ul>}
      </section>

      {/* Quickstart / Pairing Guidance */}
      {devices.length===0?<section className="card quickstart-card">
        <div className="card-kicker"><Icon name="cpu" size={15}/> PAIR YOUR COMPUTER</div>
        <h2>Connect your computer</h2>
        <p>Run Cloud setup in your terminal to pair this computer:</p>
        <div className="local-setup-command">
          <code>kicad-mcp-pro cloud setup</code>
        </div>
        <p className="field-help">Or run <code>kicad-mcp-pro cloud setup --browse</code> to choose a project folder directly.</p>
      </section>:
      <details className="card pair-another-card">
        <summary><Icon name="cpu" size={16}/> Connect another computer</summary>
        <div className="pair-another-content">
          <p>On your other computer, run:</p>
          <div className="local-setup-command">
            <code>kicad-mcp-pro cloud setup</code>
          </div>
          <p className="field-help">Follow the browser approval link to pair the new device.</p>
        </div>
      </details>}

          {/* Registered Projects Section */}
          <section className="card projects-card">
            <h2 id="registered-projects">Registered projects</h2>
            {projects.length>0?<>
              <ul className="connections-list">{projects.map(project=><li className="project-item" key={project.id}>
                <strong>{project.alias}</strong>
                <p>On device: {deviceNames.get(project.deviceId)??"Previously registered device"}.
                  {project.enabled?" Read-only metadata registered.":" Disabled."}{" "}
                  Local folder must be selected separately on the device. Per-client access is denied until granted.</p>

                {project.grantCsrf&&savedGrants.some(g=>g.projectId===project.id)?
                  <div className="project-grants">
                    <strong>Saved client permissions</strong>
                    <p>These are stored policies, not proof that a client is connected or that remote editing is available.</p>
                    <ul>{savedGrants.filter(g=>g.projectId===project.id).map(g=><li key={g.clientId}>
                      <span className="grant-client">{g.clientId}</span>{" "}
                      <span className="permission-tag">{g.maxMode==="readonly"?"Read only":
                        g.maxMode==="write"?"Edit configured (not active)":
                        "Other permission (not remote editing)"}</span>
                      <form method="post" action="/devices/projects/grant">
                        <input type="hidden" name="project_id" value={project.id}/>
                        <input type="hidden" name="client_id" value={g.clientId}/>
                        <input type="hidden" name="csrf" value={project.grantCsrf}/>
                        <button className="button danger" type="submit" name="enabled" value="false">
                          Revoke this client
                        </button>
                      </form>
                    </li>)}</ul>
                  </div>:null}

                {project.enabled&&project.managedCsrf?<>
                  <p>Managed Connector: {project.managedEnabled?"On (read-only project summary)":"Off"}. Per-client access is controlled separately.</p>
                  <form method="post" action="/devices/projects/managed">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="device_id" value={project.deviceId}/>
                    <input type="hidden" name="csrf" value={project.managedCsrf}/>
                    <button className="button secondary" name="enabled" value={project.managedEnabled?"false":"true"} type="submit">
                      {project.managedEnabled?"Turn Connector Off":"Turn Connector On"}
                    </button>
                  </form>
                </>:null}

                {project.enabled&&project.grantCsrf&&clients.length>0?
                  <form method="post" action="/devices/projects/grant">
                    <input type="hidden" name="project_id" value={project.id}/>
                    <input type="hidden" name="csrf" value={project.grantCsrf}/>
                    <label>AI client with existing OAuth consent{" "}
                      <select name="client_id" required={true}>
                        {clients.map(client=><option value={client} key={client}>{client}</option>)}
                      </select>
                    </label>
                    <div className="action-row">
                      <button className="button primary" name="enabled" value="true" type="submit">Allow read-only metadata</button>
                      <button className="button danger" name="enabled" value="false" type="submit">Revoke this project's access</button>
                    </div>
                  </form>:null}
              </li>)}</ul>
            </>:<div className="project-empty">
              <h3>No registered projects yet</h3>
              <p>Register a project under an enabled device above. Each AI client's access is granted separately.</p>
            </div>}
            <div className="security-note">
              <Icon name="shield" size={17}/>Revoked keys cannot authenticate, even if a device flag is later changed. No KiCad project files or paths are stored in Cloud.
            </div>
          </section>
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
      {enrollmentAvailable&&ownerSub?<details className="advanced-identity">
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
    </div>
  });
}
