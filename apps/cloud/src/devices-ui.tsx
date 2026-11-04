import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import type {ManagedDevice} from "./device-management.js";
export function renderDevicesPage(
  devices:ReadonlyArray<ManagedDevice & {csrf:string;deleteCsrf?:string;enableCsrf?:string;projectCsrf?:string;
    connectionState?:"connected"|"disconnected"}>,
  notice?:string,enrollmentAvailable=true,
  projects:ReadonlyArray<{id:string;deviceId:string;alias:string;enabled:boolean;grantCsrf?:string;
    managedEnabled?:boolean;managedCsrf?:string}>=[],
  ownerSub?:string,clients:ReadonlyArray<string>=[]
):string {
  // Opaque identifiers remain in form fields for the existing backend
  // contract; the owner-facing page uses human-readable aliases instead.
  const deviceNames=new Map(devices.map(d=>[d.id,d.alias]));
  return renderPage({title:"Devices & projects",kind:"devices",eyebrow:"Workspace / Devices & projects",
    summary:"Computers your AI clients can reach, and the projects you choose to share.",
    actions:enrollmentAvailable?<a className="button primary" href="/devices/pairing"><span aria-hidden="true">+</span> Pair a device</a>:null,
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}
      {enrollmentAvailable?<nav className="setup-progress" aria-label="Cloud setup progress">
        <div className="setup-progress-heading"><strong>Connection setup</strong>
          <span>Each layer requires its own approval. Nothing is shared by default.</span></div>
        <ol>
          <li className="progress-complete"><span className="progress-number">01</span>
            <div><strong>Account</strong><small>Signed in</small></div></li>
          <li className={devices.some(d=>d.enabled&&!d.revoked)?"progress-complete":"progress-current"}>
            <span className="progress-number">02</span><div><strong>Computer</strong>
              <small>{devices.some(d=>d.enabled&&!d.revoked)?"Device paired":"Pair your device"}</small></div></li>
          <li className={projects.some(p=>p.enabled)?"progress-complete":"progress-current"}>
            <span className="progress-number">03</span><div><strong>Project</strong>
              <small>{projects.some(p=>p.enabled)?"Project registered":"Choose a local folder"}</small></div></li>
          <li className={clients.length>0?"progress-complete":"progress-current"}>
            <span className="progress-number">04</span><div><strong>AI client</strong>
              <small>{clients.length>0?"Client connected":"Connect ChatGPT, Claude or another app"}</small></div></li>
          <li className="progress-current"><span className="progress-number">05</span>
            <div><strong>Grant access</strong><small>Choose permissions per project and client</small></div></li>
        </ol>
      </nav>:null}
      {!enrollmentAvailable && devices.length===0?<section className="card status-card" id="registered-projects"><div>
        <span className="status-pill pending">Not enabled</span>
        <h2>Local KiCad devices aren't available yet</h2>
        <p>Device enrollment and management are not enabled on this deployment. No pairing or local project control is available. The device schema and recovery checks must be approved before activation.</p>
        <div className="state-detail"><div><span>Cloud account</span><small>Available</small></div>
          <div><span>Device enrollment</span><small>Not enabled</small></div>
          <div><span>Remote KiCad execution</span><small>Not enabled</small></div></div>
      </div></section>:
        <>
          <section className="card quickstart-card">
            <div className="card-kicker"><Icon name="cpu" size={15}/> SINGLE COMMAND ONBOARDING</div>
            <h2>Connect your computer in seconds</h2>
            <p>Run this single command in your local terminal to pair your device, select a project, and establish secure read-only MCP access automatically:</p>
            <div className="local-setup-command">
              <code>kicad-mcp-pro cloud setup</code>
            </div>
            <p className="field-help">The terminal will open your browser for one-click approval. No technical IDs or manual keys required.</p>
            <div className="local-folder-browse"><strong>Prefer choosing a folder?</strong>
              <p>On your own computer, run <code>kicad-mcp-pro cloud setup --browse</code> to select your KiCad
                project directory using a native folder picker. Your local path is never sent to Cloud.
                A web browser cannot safely browse the server's local filesystem.</p>
            </div>
          </section>
          <section className="card device-card"><div className="card-header"><h2>Your devices</h2>
          <span className="list-count">{devices.length===1?"1 enrolled device":`${devices.length} enrolled devices`}</span></div>
          {devices.length===0?<div className="empty-state"><div className="empty-icon"><Icon name="devices" size={21}/></div><div>
            <h3>No enrolled devices</h3><p>No devices are currently registered to this account.</p>
          </div></div>:
            <ul className="connections-list device-list">{devices.map(d=><li className="device-row" key={d.id}>
              <span className={d.enabled&&!d.revoked&&d.connectionState==="connected"?"device-dot connected":"device-dot"} aria-hidden="true"/>
              <div className="device-summary"><h3>{d.alias}</h3>
                <p>{d.revoked?"Revoked":!d.enabled?"Disabled":
                  d.connectionState==="connected"?
                    "Connector connected now (temporary session; not proof of KiCad activity)":
                  d.connectionState==="disconnected"?"Connector not connected now":
                    "Enabled (not proof of online status)"}</p></div>
              <div className="device-actions"><span className={d.enabled&&!d.revoked&&d.connectionState==="connected"?"status-pill ready":"status-pill neutral"}>
                {d.revoked?"Revoked":!d.enabled?"Disabled":d.connectionState==="connected"?"Connected":d.connectionState==="disconnected"?"Offline":"Status unknown"}</span>
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
              {d.revoked?<span className="status-pill pending">Credential revoked</span>:
                <form action="/devices/revoke" method="post">
                  <input type="hidden" name="device_id" value={d.id}/><input type="hidden" name="csrf" value={d.csrf}/>
                  <button className="button danger" type="submit">Revoke device</button>
                </form>}
              </div>
              {enrollmentAvailable&&!d.revoked&&d.enabled&&d.projectCsrf?<details className="device-register"><summary>Register a project</summary>
                <form action="/devices/projects/create" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.projectCsrf}/>
                  <label>Project alias (no local paths){" "}
                    <input name="alias" maxLength={64} required={true} autoComplete="off"/>
                  </label>
                  <button className="button secondary" type="submit">Register read-only project</button>
                </form></details>:null}
            </li>)}</ul>}
          <div className="card-footnote"><Icon name="lock" size={14}/> A connected Connector does not by itself prove KiCad is ready.</div>
          </section>
          <section className="card projects-card"><h2 id="registered-projects">Registered projects</h2>
          {projects.length>0?<>
            <ul className="connections-list">{projects.map(project=><li className="project-item" key={project.id}>
              <strong>{project.alias}</strong>
              <p>On device: {deviceNames.get(project.deviceId)??"Previously registered device"}.
                {project.enabled?" Read-only metadata registered.":" Disabled."}{" "}
                Local folder must be selected separately on the device. Per-client access is denied until granted.</p>
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
                  <div className="action-row"><button className="button primary" name="enabled" value="true" type="submit">Allow read-only metadata</button>
                  <button className="button danger" name="enabled" value="false" type="submit">Revoke this project's access</button></div>
                </form>:null}
            </li>)}</ul></>:<div className="project-empty">
              <h3>No registered projects yet</h3>
              <p>Register a project under an enabled device above. Each AI client's access is granted separately.</p>
            </div>}
          <div className="security-note"><Icon name="shield" size={17}/>Revoked keys cannot authenticate, even if a device flag is later changed. No KiCad project files or paths are stored in Cloud.</div>
          </section>
        </>}
      <section className="card client-shortcuts"><h2>Where you use it</h2>
        <p>Connect your preferred AI client, then grant it access to a registered project.</p>
        <ul>
          <li><span className="client-icon"><Icon name="connections" size={20}/></span><div><h3>ChatGPT</h3><p>Review the remote MCP connection guide.</p></div><a className="text-link" href="/connections" aria-label="Set up ChatGPT">Set up <Icon name="arrow" size={14}/></a></li>
          <li><span className="client-icon"><Icon name="spark" size={20}/></span><div><h3>Claude</h3><p>Review connector setup and account permissions.</p></div><a className="text-link" href="/connections" aria-label="Set up Claude">Set up <Icon name="arrow" size={14}/></a></li>
          <li><span className="client-icon"><Icon name="cpu" size={20}/></span><div><h3>Other MCP clients</h3><p>Check endpoint details and authentication requirements.</p></div><a className="text-link" href="/connections" aria-label="Set up another MCP client">Details <Icon name="arrow" size={14}/></a></li>
        </ul>
      </section>
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
