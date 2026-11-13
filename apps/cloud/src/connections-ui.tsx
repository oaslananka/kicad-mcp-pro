import {renderPage} from "./ui-shell.js";
import {Icon} from "./ui-icons.js";
import {CopyValue} from "./copy-value.js";

export type DisplayConnection={id:string;name:string;scopes:string[];clientId:string;csrf:string};

const scopesInfo=new Map<string,string>([
  ["openid","Identify your account"],
  ["profile","View your basic profile"],
  ["offline_access","Keep connection without repeated login"],
  ["projects:read","List projects you explicitly allow"],
  ["projects:write","Request editing on projects you separately approve"]
]);

function ConnectionSetup({endpoint}:Readonly<{endpoint:string|null}>){
  return <section className="card detail-card" aria-labelledby="mcp-setup">
    <div className="card-kicker">CONNECT AN AI APP</div>
    <h2 id="mcp-setup">Connect your AI client</h2>
    {endpoint?<>
      <ol className="connection-setup-steps">
        <li><h3>Add the Cloud endpoint</h3>
          <p>In your AI app, add a custom remote MCP connection using this URL.</p>
          <CopyValue value={endpoint} label="MCP endpoint"/></li>
        <li><h3>Authorize your account</h3>
          <p>Start the connection in your AI app. Sign in to KiCad MCP Cloud and review the requested account permissions.</p></li>
        <li><h3>Choose project access</h3>
          <p>Return here after authorizing. Choose a project and approve the AI app in its access settings.</p>
          <a className="button secondary" href="/projects">Choose projects <Icon name="arrow" size={15}/></a></li>
      </ol>
      <p className="endpoint-subtext">The endpoint alone does not grant project access. Review permissions on the <a href="/devices" className="text-link">Devices</a> page. A connected Cloud account does not imply a running KiCad engine.</p>
      <details className="mcp-client-help"><summary>Setup guides by app</summary>
        <div className="mcp-client-guides">
          <div className="client-guide-card">
            <h3>ChatGPT</h3>
            <p>Use the official guide to add a custom MCP connection and authorize your Cloud account.</p>
            <a className="text-link" href="https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt"
              target="_blank" rel="noopener noreferrer">ChatGPT setup guide <Icon name="arrow" size={13}/></a>
          </div>
          <div className="client-guide-card">
            <h3>Claude</h3>
            <p>Add a custom remote connector with this endpoint and authenticate with your Cloud account.</p>
            <a className="text-link" href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp"
              target="_blank" rel="noopener noreferrer">Claude setup guide <Icon name="arrow" size={13}/></a>
          </div>
          <div className="client-guide-card">
            <h3>Google Gemini</h3>
            <p>Use the Gemini CLI guide for remote HTTPS MCP and OAuth configuration.</p>
            <a className="text-link" href="https://geminicli.com/docs/tools/mcp-server/"
              target="_blank" rel="noopener noreferrer">Gemini CLI guide <Icon name="arrow" size={13}/></a>
          </div>
        </div>
      </details>
      <script src="/assets/copy-value.js" defer={true}/>
    </>:<p>This development endpoint is not public HTTPS. Configure a reachable HTTPS Cloud origin before using a remote AI-host connector. Local KiCad MCP remains available without a Cloud account.</p>}
  </section>;
}

export function renderConnectionsPage(
  connections:DisplayConnection[],notice?:string,publicOrigin?:string
):string {
  const endpoint=publicOrigin?new URL("/mcp",publicOrigin):null;
  const publicEndpoint=endpoint?.protocol==="https:"?endpoint.href:null;
  const setup=publicOrigin?<ConnectionSetup endpoint={publicEndpoint}/>:null;

  return renderPage({title:"AI connections",kind:"connections",eyebrow:"Workspace / Connections",
    summary:"Review apps with access to your cloud account. A connection does not automatically share any KiCad project.",
    children:<div className="page-stack">
      {notice?<output className="output-notice">{notice}</output>:null}
      {connections.length===0?setup:null}

      {/* Connected Applications Card */}
      <section className="card detail-card" aria-labelledby="connected-clients">
        <div className="card-kicker">AUTHORIZED APPLICATIONS</div>
        <h2 id="connected-clients">{connections.length===1?"1 connected app":`${connections.length} connected apps`}</h2>
        <p className="section-description">
          Connected applications can identify your Cloud account and query explicitly granted projects. Choose what to share from your <a href="/projects" className="text-link">Projects</a> page.
        </p>

        {connections.length===0?<div className="empty-state">
          <div className="empty-icon"><Icon name="connections" size={21}/></div>
          <div>
            <h3>No AI apps connected yet</h3>
            <p>Apps appear here after you authorize a connection from your AI client.</p>
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
      {connections.length>0?setup:null}
    </div>});
}
