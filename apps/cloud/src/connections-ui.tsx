import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";

export type DisplayConnection={id:string;name:string;scopes:string[];clientId:string;csrf:string};

const scopesInfo=new Map<string,string>([
  ["openid","Identify your account"],
  ["profile","View your basic profile"],
  ["offline_access","Keep connection without repeated login"],
  ["projects:read","List projects you explicitly allow"],
  ["projects:write","Request editing on projects you separately approve"]
]);

export function renderConnectionsPage(
  connections:DisplayConnection[],notice?:string,publicOrigin?:string
):string {
  const endpoint=publicOrigin?new URL("/mcp",publicOrigin):null;
  const publicEndpoint=endpoint?.protocol==="https:"?endpoint.href:null;

  return renderPage({title:"AI connections",kind:"connections",eyebrow:"Workspace / Connections",
    summary:"Review apps with access to your cloud account. A connection does not automatically share any KiCad project.",
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}

      {/* Connected Applications Card */}
      <section className="card detail-card" aria-labelledby="connected-clients">
        <div className="card-kicker">AUTHORIZED APPLICATIONS</div>
        <h2 id="connected-clients">{connections.length===1?"1 connected app":`${connections.length} connected apps`}</h2>
        <p className="section-description">
          Connected applications can identify your Cloud account and query explicitly granted projects. Project grants are managed separately on the <a href="/devices" className="text-link">Devices &amp; projects</a> page.
        </p>

        {connections.length===0?<div className="empty-state">
          <div className="empty-icon"><Icon name="connections" size={21}/></div>
          <div>
            <h3>No AI apps connected yet</h3>
            <p>Start a connection from your AI client (ChatGPT, Claude, or custom MCP) and authorize it below.</p>
            {publicEndpoint?<a className="text-link" href="#mcp-setup">Open the connection guide <Icon name="arrow" size={15}/></a>:null}
          </div>
        </div>:
          <ul className="connections-list">{connections.map(c=><li className="connection-item" key={c.id}>
            <div>
              <span className="status-pill ready"><span className="status-dot" aria-hidden="true"/> Authorized</span>
              <h3 className="connection-name">{c.name}</h3>
              <p>Account access is active. Project access is granted separately.</p>
              <div className="permission-tags" aria-label={`Permissions for ${c.name}`}>
                {c.scopes.map(scope=><span className="permission-tag" key={scope} title={scope}>{scopesInfo.get(scope)??scope}</span>)}
              </div>
            </div>
            <form method="post" action="/connections/revoke">
              <input type="hidden" name="id" value={c.id}/>
              <input type="hidden" name="client_id" value={c.clientId}/>
              <input type="hidden" name="csrf" value={c.csrf}/>
              <button className="button danger" type="submit">Remove access</button>
            </form>
          </li>)}</ul>}
        <div className="security-note">
          <Icon name="shield" size={17}/> Removing access disables the app's project grants. Previously issued tokens may persist until expiry, but revoked grants prevent project discovery.
        </div>
      </section>

      {/* Remote MCP Endpoint & Client Setup Guide */}
      {publicOrigin?<section className="card detail-card" aria-labelledby="mcp-setup">
        <div className="card-kicker">REMOTE MCP INTEGRATION</div>
        <h2 id="mcp-setup">Connect your AI client</h2>
        {publicEndpoint?<><p className="section-description">Use this HTTPS endpoint when adding a custom remote MCP server to ChatGPT or Claude:</p>
          <div className="mcp-endpoint-box">
            <code className="endpoint-url">{publicEndpoint}</code>
          </div>
          <p className="endpoint-subtext">The endpoint alone does not grant project access. Review permissions on the <a href="/devices" className="text-link">Devices</a> page. A connected Cloud account does not imply a running KiCad engine.</p>
          <div className="mcp-client-guides">
            <div className="client-guide-card">
              <h3>ChatGPT</h3>
              <p>Open Plugins, choose Add custom MCP server, enter the endpoint, configure OAuth, and inspect tools.</p>
              <a className="text-link" href="https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt"
                target="_blank" rel="noopener noreferrer">ChatGPT setup guide <Icon name="arrow" size={13}/></a>
            </div>
            <div className="client-guide-card">
              <h3>Claude</h3>
              <p>Open Customize / Connectors, add a custom remote connector with this endpoint, and authenticate.</p>
              <a className="text-link" href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp"
                target="_blank" rel="noopener noreferrer">Claude setup guide <Icon name="arrow" size={13}/></a>
            </div>
            <div className="client-guide-card">
              <h3>Google Gemini</h3>
              <p>Gemini CLI supports remote HTTPS MCP with OAuth authentication settings.</p>
              <a className="text-link" href="https://geminicli.com/docs/tools/mcp-server/"
                target="_blank" rel="noopener noreferrer">Gemini CLI guide <Icon name="arrow" size={13}/></a>
            </div>
          </div>
        </>:<p>This development endpoint is not public HTTPS. Configure a reachable HTTPS Cloud origin before using a remote AI-host connector. Local KiCad MCP remains available without a Cloud account.</p>}
      </section>:null}
    </div>});
}
