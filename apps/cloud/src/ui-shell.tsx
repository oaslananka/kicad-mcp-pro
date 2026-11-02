import type {ReactNode} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {Icon} from "./ui-icons.js";

export type PageKind="home"|"sign-in"|"account"|"consent"|"connections"|"devices"|"notice";
type Props={title:string;eyebrow?:string;summary?:string;kind:PageKind;children:ReactNode;navEnabled?:boolean};
const workspacePages=new Set<PageKind>(["account","connections","devices"]);
function NavLink({href,current,children}:{href:string;current:boolean;children:ReactNode}){
  return <a href={href} aria-current={current?"page":undefined}>{children}</a>;
}
function WorkspaceNav({kind}:{kind:PageKind}){
  return <aside className="workspace-sidebar" aria-label="Workspace navigation">
    <div className="sidebar-label">YOUR WORKSPACE</div>
    <nav className="sidebar-links" aria-label="Workspace">
      <NavLink href="/account" current={kind==="account"}><Icon name="overview" size={18}/> Overview</NavLink>
      <NavLink href="/devices" current={kind==="devices"}><Icon name="devices" size={18}/> Devices &amp; projects</NavLink>
      <NavLink href="/connections" current={kind==="connections"}><Icon name="connections" size={18}/> AI connections</NavLink>
    </nav>
    <div className="sidebar-note"><Icon name="shield" size={20}/><strong>Local by design</strong>
      <p>Your KiCad files stay on your computer. You choose each project's access.</p>
    </div>
    <div className="sidebar-footer"><span>NEED A HAND?</span>
      <a href="/connections">Connection setup <Icon name="arrow" size={15}/></a>
      <small>Live device status is shown under Devices &amp; projects.</small>
    </div>
  </aside>;
}
export function renderPage({title,eyebrow,summary,kind,children,navEnabled=true}:Props):string{
  const workspace=workspacePages.has(kind);
  return "<!doctype html>"+renderToStaticMarkup(
    <html lang="en"><head>
      <meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
      <meta name="theme-color" content="#f4f6f3"/>
      <meta name="description" content="Manage KiCad MCP Cloud connections and access."/>
      <link rel="stylesheet" href="/assets/ui.css"/><title>{title+" — KiCad MCP Cloud"}</title>
    </head><body><div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="site-header"><div className="header-inner">
        <a href="/" className="brand" aria-label="KiCad MCP Cloud home">
          <span className="brand-mark"><Icon name="logo" size={27}/></span>
          <span className="brand-title">KiCad <b>MCP</b><small>Cloud workspace</small></span>
        </a>
        <div className="header-right">
          <span className="release-label"><Icon name="shield" size={15}/> Your projects. Your permissions.</span>
          {workspace?<a className="header-account" href="/account">My workspace <Icon name="arrow" size={15}/></a>:
            <nav className="public-nav" aria-label="Primary"><NavLink href="/" current={kind==="home"}>Overview</NavLink>
              {navEnabled?<NavLink href="/account" current={false}>Workspace</NavLink>:null}</nav>}
        </div>
      </div></header>
      <main id="main-content" className={"site-main page-"+kind}>
        <div className={workspace?"workspace-layout":"content-wrap"}>
          {workspace?<WorkspaceNav kind={kind}/>:null}
          <div className="main-content">
            <div className="page-heading"><div className="eyebrow">{eyebrow??"KiCad MCP Cloud"}</div>
              <h1>{title}</h1>{summary?<p className="summary">{summary}</p>:null}</div>
            {children}
          </div>
        </div>
      </main>
      <footer className="site-footer"><div className="footer-inner"><span>© KiCad MCP Cloud</span>
        <span>Local files <span className="footer-separator">/</span> Explicit project access <span className="footer-separator">/</span> Your control</span></div></footer>
    </div></body></html>
  );
}
export function Landing({identityEnabled}:{readonly identityEnabled:boolean}){
  return <div className="page-stack">
    <section className="card landing-panel" aria-label="Cloud capabilities">
      <div className="landing-intro">
        <span className={identityEnabled?"status-pill ready":"status-pill pending"}>
          {identityEnabled?<span className="status-dot" aria-hidden="true"/>:null}
          {identityEnabled?"Cloud access available":"Account access pending"}
        </span>
        <h2>Manage your AI tools.<br/>Keep KiCad local.</h2>
        <p>A single place for your AI connections, registered computers and project permissions. Start with your account, then choose what to connect.</p>
        <div className="action-row">{identityEnabled?
          <a className="button primary" href="/sign-in">Open workspace <Icon name="arrow" size={17}/></a>:
          <span className="button disabled" aria-disabled="true">Account access pending</span>}
          <a className="text-link" href="#how-it-works">See the setup steps <Icon name="arrow" size={15}/></a>
        </div>
        <p className="hero-note"><Icon name="shield" size={16}/> Project access always requires separate approval.</p>
      </div>
      <div className="topology-panel" aria-label="Current connection availability">
        <div className="topology-eyebrow">ACCESS ARCHITECTURE <span className="topology-eyebrow-dot"/></div>
        <div className="topology-node topology-node-client"><span className="topology-icon"><Icon name="connections" size={21}/></span>
          <span><strong>Your AI assistant</strong><small>{identityEnabled?"Account authorization available":"Account access pending"}</small></span>
          <span className={identityEnabled?"topology-indicator on":"topology-indicator"}/>
        </div>
        <div className="topology-link active"><span/><small>EXPLICIT PERMISSIONS</small></div>
        <div className="topology-node topology-node-cloud"><span className="topology-icon"><Icon name="cloud" size={21}/></span>
          <span><strong>KiCad MCP Cloud</strong><small>Account &amp; project access</small></span>
          <span className={identityEnabled?"topology-indicator on":"topology-indicator"}/>
        </div>
        <div className="topology-link inactive"><span/><small>SEPARATE DEVICE APPROVAL</small></div>
        <div className="topology-node topology-node-device"><span className="topology-icon"><Icon name="cpu" size={21}/></span>
          <span><strong>KiCad on your computer</strong><small>Connection not enabled</small></span>
          <span className="topology-tag">Not enabled</span>
        </div>
        <div className="topology-foot"><Icon name="lock" size={15}/> No project files are shared by signing in.</div>
      </div>
    </section>
    <section className="next-section" aria-labelledby="how-it-works">
      <div className="section-head"><div><div className="card-kicker">A CLEAR SETUP PATH</div>
        <h2 id="how-it-works">One step at a time.</h2></div>
        <p>Account access, device access and project permissions remain separate.</p></div>
      <div className="steps-grid">
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="key" size={19}/></span><span>01</span></div><h3>Sign in securely</h3><p>Use your account to access the Cloud workspace.</p></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="devices" size={19}/></span><span>02</span></div><h3>Review your computer</h3><p>Device pairing and local project actions aren't available yet.</p><span className="step-state">Deployment-dependent</span></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="connections" size={19}/></span><span>03</span></div><h3>Connect your AI client</h3><p>Follow the connection guide and review the app's account permissions.</p></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="cpu" size={19}/></span><span>04</span></div><h3>Choose project access</h3><p>When available, grant your authorized AI client access to a registered project.</p></div>
      </div>
    </section>
  </div>;
}
export function Notice({message}:{readonly message:string}){
  return <section className="card detail-card"><div className="notice-icon"><Icon name="warning" size={22}/></div>
    <h2>We couldn't complete that action</h2><p>{message}</p><a href="/" className="text-link">Return to overview <Icon name="arrow" size={16}/></a></section>;
}
export function SignIn({query,providers}:{readonly query:string;readonly providers:ReadonlyArray<"google"|"github">}){
  return <section className="card auth-card">
    <div className="panel-heading"><div className="panel-icon"><Icon name="lock" size={21}/></div>
      <div><h2>Your workspace starts here</h2><p>Choose an available account to continue.</p></div></div>
    <div className="providers">{providers.includes("google")&&<form action="/auth/start/google" method="post">
      <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
        <span className="provider-logo">G</span> Continue with Google <Icon name="arrow" size={17} className="provider-arrow"/></button>
    </form>}{providers.includes("github")&&<form action="/auth/start/github" method="post">
      <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
        <span className="provider-logo github"><Icon name="github" size={21}/></span> Continue with GitHub <Icon name="arrow" size={17} className="provider-arrow"/></button>
    </form>}</div>
    <div className="auth-footnote"><Icon name="shield" size={19}/><p>Signing in doesn't share your KiCad projects. AI client permissions and project access require separate approval.</p></div>
  </section>;
}
export function Account({name}:{readonly name:string}){
  return <div className="page-stack">
    <section className="account-welcome" aria-label="Account status"><div className="account-banner">
      <span className="avatar" aria-hidden="true">{name.trim().slice(0,1).toUpperCase()||"U"}</span>
      <div><div className="card-kicker">YOUR ACCOUNT</div>
        <h2>{name}</h2><p>Review your computers, project access and AI connections below.</p></div>
    </div><span className="status-pill ready"><Icon name="check" size={14}/> Signed in</span></section>
    <section className="card setup-checklist" aria-labelledby="connection-checklist">
      <div className="section-head"><div><div className="card-kicker">GET CONNECTED</div>
        <h2 id="connection-checklist">Your connection checklist</h2></div><span className="section-note">Review each layer independently</span></div>
      <ol className="checklist-list">
        <li><span className="checklist-number complete"><Icon name="check" size={16}/></span><div><h3>Cloud account</h3><p>You're signed in to your workspace.</p></div><span className="status-pill ready">Signed in</span></li>
        <li><span className="checklist-number">02</span><div><h3>Computer &amp; project</h3><p>Check your device's connection and register a project when available.</p></div><a className="text-link" href="/devices">Review devices <Icon name="arrow" size={15}/></a></li>
        <li><span className="checklist-number">03</span><div><h3>AI connection</h3><p>Follow your client's setup guide and review its account permissions.</p></div><a className="text-link" href="/connections">Manage connections <Icon name="arrow" size={15}/></a></li>
        <li><span className="checklist-number">04</span><div><h3>Project permissions</h3><p>Grant your authorized AI client access to a specific registered project.</p></div><a className="text-link" href="/devices#registered-projects">Review projects <Icon name="arrow" size={15}/></a></li>
      </ol>
    </section>
    <aside className="workspace-reminder"><Icon name="lock" size={18}/><p>An authorized AI app does not automatically have project access. A connected device does not by itself prove that KiCad is ready.</p></aside>
  </div>;
}
