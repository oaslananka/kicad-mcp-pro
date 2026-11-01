import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
export type DisplayConnection={id:string;name:string;scopes:string[];clientId:string;csrf:string};
const scopesInfo:Record<string,string>={
  "openid":"Identify your account",
  "profile":"View your basic profile",
  "offline_access":"Keep a connection without signing in each time",
  "projects:read":"List projects you separately allow"
};
export function renderConnectionsPage(connections:DisplayConnection[],notice?:string):string {
  return renderPage({title:"AI connections",kind:"connections",eyebrow:"Workspace / Connections",
    summary:"Review apps with access to your cloud account. A connection does not automatically share any KiCad project.",
    children:<div className="page-stack"><section className="card detail-card" aria-labelledby="connected-clients">
      <div className="card-kicker">AUTHORIZED APPLICATIONS</div>
      <h2 id="connected-clients">{connections.length===1?"1 connected app":`${connections.length} connected apps`}</h2>
      {notice?<output className="output-notice">{notice}</output>:null}
      {connections.length===0?<div className="empty-state"><div className="empty-icon"><Icon name="connections" size={21}/></div><div>
        <h3>No AI apps connected yet</h3><p>Start a connection from your AI client and review the permission request here.</p>
      </div></div>:
        <ul className="connections-list">{connections.map(c=><li className="connection-item" key={c.id}>
          <div><span className="status-pill ready"><span className="status-dot" aria-hidden="true"/> Authorized</span>
            <h3 className="connection-name">{c.name}</h3><p>Account access is active. Project access is granted separately.</p>
            <div className="permission-tags" aria-label={`Permissions for ${c.name}`}>
              {c.scopes.map(scope=><span className="permission-tag" key={scope} title={scope}>{scopesInfo[scope]??scope}</span>)}
            </div></div>
          <form method="post" action="/connections/revoke">
            <input type="hidden" name="id" value={c.id}/>
            <input type="hidden" name="client_id" value={c.clientId}/>
            <input type="hidden" name="csrf" value={c.csrf}/>
            <button className="button danger" type="submit">Remove access</button>
          </form>
        </li>)}</ul>}
      <div className="security-note"><Icon name="shield" size={17}/> Removing access disables the app's project grants. Previously issued tokens may persist until expiry, but revoked grants prevent project discovery.</div>
    </section><section className="card detail-card"><div className="card-kicker">PERMISSIONS</div>
      <h2>How access is controlled</h2><p>Signing in authorizes your account. Access to an individual KiCad project requires an additional explicit grant and a supported device connection.</p>
    </section></div>});
}
