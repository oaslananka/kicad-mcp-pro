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
    <div className="sidebar-label">WORKSPACE</div>
    <nav className="sidebar-links" aria-label="Workspace">
      <NavLink href="/account" current={kind==="account"}><Icon name="overview" size={18}/> Overview</NavLink>
      <NavLink href="/connections" current={kind==="connections"}><Icon name="connections" size={18}/> Connections</NavLink>
      <NavLink href="/devices" current={kind==="devices"}><Icon name="devices" size={18}/> Devices</NavLink>
    </nav>
    <div className="sidebar-footer"><span className="status-dot" aria-hidden="true"/>
      <strong>Cloud account ready</strong><small>Local KiCad connection not enabled</small>
    </div>
  </aside>;
}
export function renderPage({title,eyebrow,summary,kind,children,navEnabled=true}:Props):string{
  const workspace=workspacePages.has(kind);
  return "<!doctype html>"+renderToStaticMarkup(
    <html lang="en"><head>
      <meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
      <meta name="theme-color" content="#0a0e15"/>
      <meta name="description" content="Manage KiCad MCP Cloud connections and access."/>
      <link rel="stylesheet" href="/assets/ui.css"/><title>{title+" — KiCad MCP Cloud"}</title>
    </head><body><div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="site-header"><div className="header-inner">
        <a href="/" className="brand" aria-label="KiCad MCP Cloud home">
          <span className="brand-mark"><Icon name="logo" size={27}/></span>
          <span className="brand-title">KiCad <b>MCP</b><small>Cloud</small></span>
        </a>
        <div className="header-right">
          <span className="release-label"><span className="status-dot" aria-hidden="true"/> Access control console</span>
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
        <span>Cloud access available <span className="footer-separator">·</span> Local KiCad control not enabled</span></div></footer>
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
        <h2>Bring clarity to every connection.</h2>
        <p>One considered workspace for AI client access, approvals, and the devices you choose to connect. Your KiCad projects stay under your control.</p>
        <div className="action-row">{identityEnabled?
          <a className="button primary" href="/sign-in">Open workspace <Icon name="arrow" size={17}/></a>:
          <span className="button disabled">Account access pending</span>}
        </div>
        <p className="hero-note"><Icon name="shield" size={16}/> Project access always requires separate approval.</p>
      </div>
      <div className="topology-panel" aria-label="Current connection availability">
        <div className="topology-eyebrow">ACCESS ARCHITECTURE <span className="topology-eyebrow-dot"/></div>
        <div className="topology-node topology-node-client"><span className="topology-icon"><Icon name="connections" size={21}/></span>
          <span><strong>AI client</strong><small>{identityEnabled?"Account authorization available":"Account access pending"}</small></span>
          <span className={identityEnabled?"topology-indicator on":"topology-indicator"}/>
        </div>
        <div className="topology-link active"><span/><small>EXPLICIT PERMISSIONS</small></div>
        <div className="topology-node topology-node-cloud"><span className="topology-icon"><Icon name="cloud" size={21}/></span>
          <span><strong>KiCad MCP Cloud</strong><small>Identity &amp; access controls</small></span>
          <span className="topology-indicator on"/>
        </div>
        <div className="topology-link inactive"><span/><small>SEPARATE DEVICE APPROVAL</small></div>
        <div className="topology-node topology-node-device"><span className="topology-icon"><Icon name="cpu" size={21}/></span>
          <span><strong>Local KiCad</strong><small>Connection not enabled</small></span>
          <span className="topology-tag">Not enabled</span>
        </div>
        <div className="topology-foot"><Icon name="lock" size={15}/> No project files are shared by signing in.</div>
      </div>
    </section>
    <section className="next-section" aria-labelledby="how-it-works">
      <div className="section-head"><div><div className="card-kicker">HOW IT WORKS</div>
        <h2 id="how-it-works">Access, on your terms.</h2></div>
        <p>Three distinct steps. No implicit device access.</p></div>
      <div className="steps-grid">
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="key" size={19}/></span><span>01</span></div><h3>Sign in securely</h3><p>Use your account to access the Cloud workspace.</p></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="shield" size={19}/></span><span>02</span></div><h3>Review permissions</h3><p>Authorize the AI applications you trust. Project grants are separate.</p></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="cpu" size={19}/></span><span>03</span></div><h3>Connect KiCad</h3><p>Device pairing and local project actions aren't available yet.</p><span className="step-state">Planned capability</span></div>
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
      <div><h2>Welcome back</h2><p>Choose your account to continue to KiCad MCP Cloud.</p></div></div>
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
    <section className="card account-card" aria-label="Account status"><div className="account-banner">
      <span className="avatar" aria-hidden="true">{name.trim().slice(0,1).toUpperCase()||"U"}</span>
      <div><span className="status-pill ready"><span className="status-dot" aria-hidden="true"/> Signed in</span>
        <h2>{name}</h2><p>Your workspace for authorized connections and device access.</p></div>
    </div></section>
    <section className="dashboard-grid" aria-label="Workspace features">
      <article className="card dashboard-card"><div className="dashboard-card-top"><span className="feature-icon"><Icon name="connections" size={23}/></span><span className="status-pill ready">Available</span></div>
        <div className="card-kicker">APPLICATION ACCESS</div><h2>AI connections</h2><p>See the apps you've authorized, inspect their permissions, and revoke access when needed.</p>
        <a className="button secondary" href="/connections">Manage connections <Icon name="arrow" size={16}/></a>
      </article>
      <article className="card dashboard-card"><div className="dashboard-card-top"><span className="feature-icon"><Icon name="devices" size={23}/></span><span className="status-pill pending">Not enabled</span></div>
        <div className="card-kicker">LOCAL HARDWARE</div><h2>Devices</h2><p>Device enrollment and local KiCad execution are not available on this deployment.</p>
        <a className="button secondary" href="/devices">View device status <Icon name="arrow" size={16}/></a>
      </article>
    </section>
    <section className="card next-steps"><div><div className="card-kicker">WORKSPACE STATUS</div>
      <h2>Built around explicit control.</h2><p>Account access is separate from project permission. Your local KiCad projects aren't exposed by signing in.</p></div>
      <div className="status-list"><div><span className="status-dot" aria-hidden="true"/><span>Cloud account</span><b>Ready</b></div>
        <div><span className="status-dot" aria-hidden="true"/><span>AI client authorization</span><b>Available</b></div>
        <div className="pending"><span className="status-dot" aria-hidden="true"/><span>KiCad device execution</span><b>Not enabled</b></div></div>
    </section>
  </div>;
}
