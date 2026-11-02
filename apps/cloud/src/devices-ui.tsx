import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import type {ManagedDevice} from "./device-management.js";
export function renderDevicesPage(
  devices:ReadonlyArray<ManagedDevice & {csrf:string;enableCsrf?:string;projectCsrf?:string;
    connectionState?:"connected"|"disconnected"}>,
  notice?:string,enrollmentAvailable=true,
  projects:ReadonlyArray<{id:string;deviceId:string;alias:string;enabled:boolean;grantCsrf?:string}>=[],
  ownerSub?:string,clients:ReadonlyArray<string>=[]
):string {
  // Opaque identifiers remain in form fields for the existing backend
  // contract; the owner-facing page uses human-readable aliases instead.
  const deviceNames=new Map(devices.map(d=>[d.id,d.alias]));
  return renderPage({title:"Devices",kind:"devices",eyebrow:"Workspace / Devices",
    summary:"Device availability and access management for local KiCad integrations.",
    children:<div className="page-stack"><section className="card detail-card">
      {enrollmentAvailable&&ownerSub?<details className="advanced-identity">
        <summary>Advanced: local Connector account ID</summary>
        <p>Only needed when configuring the local Connector manually: <code>{ownerSub}</code></p>
      </details>:null}
      {notice?<output className="output-notice">{notice}</output>:null}
      {!enrollmentAvailable && devices.length===0?<div className="status-card"><div>
        <span className="status-pill pending">Not enabled</span>
        <h2>Local KiCad devices aren't available yet</h2>
        <p>Device enrollment and management are not enabled on this deployment. No pairing or local project control is available. The device schema and recovery checks must be approved before activation.</p>
        <div className="state-detail"><div><span>Cloud account</span><small>Available</small></div>
          <div><span>Device enrollment</span><small>Not enabled</small></div>
          <div><span>Remote KiCad execution</span><small>Not enabled</small></div></div>
      </div></div>:
        <><div className="card-kicker">ENROLLED DEVICES</div>
          <h2>{devices.length===1?"1 enrolled device":`${devices.length} enrolled devices`}</h2>
          {devices.length===0?<div className="empty-state"><div className="empty-icon"><Icon name="devices" size={21}/></div><div>
            <h3>No enrolled devices</h3><p>No devices are currently registered to this account.</p>
          </div></div>:
            <ul className="connections-list">{devices.map(d=><li className="connection-item" key={d.id}>
              <div><h3>{d.alias}</h3>
                <p>{d.revoked?"Revoked":!d.enabled?"Disabled":
                  d.connectionState==="connected"?
                    "Connector connected now (temporary session; not proof of KiCad activity)":
                  d.connectionState==="disconnected"?"Connector not connected now":
                    "Enabled (not proof of online status)"}</p></div>
              {enrollmentAvailable&&!d.revoked&&!d.enabled&&d.enableCsrf?
                <form action="/devices/enable" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.enableCsrf}/>
                  <button className="button secondary" type="submit">Enable my device</button>
                </form>:null}
              {enrollmentAvailable&&!d.revoked&&d.enabled&&d.projectCsrf?
                <form action="/devices/projects/create" method="post">
                  <input type="hidden" name="device_id" value={d.id}/>
                  <input type="hidden" name="csrf" value={d.projectCsrf}/>
                  <label>Project alias (no local paths){" "}
                    <input name="alias" maxLength={64} required={true} autoComplete="off"/>
                  </label>
                  <button className="button secondary" type="submit">Register read-only project</button>
                </form>:null}
              {d.revoked?<span className="status-pill pending">Credential revoked</span>:
                <form action="/devices/revoke" method="post">
                  <input type="hidden" name="device_id" value={d.id}/><input type="hidden" name="csrf" value={d.csrf}/>
                  <button className="button danger" type="submit">Revoke device</button>
                </form>}
            </li>)}</ul>}
          {projects.length>0?<><h3>Registered projects</h3>
            <ul className="connections-list">{projects.map(project=><li key={project.id}>
              <strong>{project.alias}</strong>
              <p>On device: {deviceNames.get(project.deviceId)??"Previously registered device"}.
                {project.enabled?" Read-only metadata registered.":" Disabled."}{" "}
                Local folder must be selected separately on the device. Per-client access is denied until granted.</p>
              {project.enabled&&project.grantCsrf&&clients.length>0?
                <form method="post" action="/devices/projects/grant">
                  <input type="hidden" name="project_id" value={project.id}/>
                  <input type="hidden" name="csrf" value={project.grantCsrf}/>
                  <label>AI client with existing OAuth consent{" "}
                    <select name="client_id" required={true}>
                      {clients.map(client=><option value={client} key={client}>{client}</option>)}
                    </select>
                  </label>
                  <button name="enabled" value="true" type="submit">Allow read-only metadata</button>
                  <button name="enabled" value="false" type="submit">Revoke this project's access</button>
                </form>:null}
            </li>)}</ul></>:null}
          <div className="security-note"><Icon name="shield" size={17}/>Revoked keys cannot authenticate, even if a device flag is later changed. No KiCad project files or paths are stored in Cloud.</div>
          {enrollmentAvailable?<div className="action-row"><a className="button secondary" href="/devices/pairing">Review device pairing →</a></div>:null}
        </>}
    </section></div>
  });
}
