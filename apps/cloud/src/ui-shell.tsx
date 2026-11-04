import type {ReactNode} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {Icon} from "./ui-icons.js";

export type PageKind="home"|"sign-in"|"account"|"consent"|"connections"|"devices"|"notice";
type Props={title:string;eyebrow?:string;summary?:string;kind:PageKind;children:ReactNode;navEnabled?:boolean;actions?:ReactNode};
const workspacePages=new Set<PageKind>(["account","connections","devices"]);
const publicDescription="KiCad MCP Cloud lets you pair your computer and grant selected AI assistants read-only access to approved KiCad project metadata.";
const publicSchema=JSON.stringify({
  "@context":"https://schema.org",
  "@type":"SoftwareApplication",
  name:"KiCad MCP Cloud",
  description:publicDescription,
  headline:"KiCad MCP Cloud — secure project access",
  dateModified:"2026-11-04",
  url:"https://kicad-mcp-pro.oaslananka.dev/",
  applicationCategory:"DeveloperApplication",
  operatingSystem:"Web",
  image:"https://kicad-mcp-pro.oaslananka.dev/assets/icon-512.png",
  author:{"@type":"Organization",name:"KiCad MCP Pro",url:"https://github.com/oaslananka/kicad-mcp-pro"}
});
function NavLink({href,current,children}:{href:string;current:boolean;children:ReactNode}){
  return <a href={href} aria-current={current?"page":undefined}>{children}</a>;
}
function Brand(){
  return <a href="/" className="brand" aria-label="KiCad MCP Cloud workspace home">
    <span className="brand-mark"><img src="/assets/icon.svg" alt="" width={30} height={30}/></span>
    <span className="brand-title">KiCad MCP <small>Cloud workspace</small></span>
  </a>;
}
function WorkspaceNav({kind}:{kind:PageKind}){
  return <aside className="workspace-sidebar" aria-label="Workspace navigation">
    <Brand/>
    <nav className="sidebar-links" aria-label="Workspace">
      <NavLink href="/devices" current={kind==="devices"}><Icon name="devices" size={18}/> Devices &amp; projects</NavLink>
      <NavLink href="/connections" current={kind==="connections"}><Icon name="connections" size={18}/> AI connections</NavLink>
      <NavLink href="/account" current={kind==="account"}><Icon name="overview" size={18}/> Overview</NavLink>
    </nav>
    <div className="sidebar-note"><strong>Connect your workspace</strong>
      <p>Set up your AI client and choose which projects it can access.</p>
      <a className="button secondary" href="/connections">Connection guide <Icon name="arrow" size={14}/></a>
    </div>
    <div className="sidebar-footer">
      <a href="/account"><Icon name="shield" size={16}/> Your account</a>
      <small>KiCad files stay on your computer.</small>
    </div>
  </aside>;
}
export function renderPage({title,eyebrow,summary,kind,children,navEnabled=true,actions}:Props):string{
  const workspace=workspacePages.has(kind);
  return "<!doctype html>"+renderToStaticMarkup(
    <html lang="en"><head>
      <meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
      <meta name="theme-color" content="#0b0b0d"/>
      <meta name="description" content={kind==="home"?publicDescription:"Manage KiCad MCP Cloud connections and access."}/>
      <meta name="robots" content={kind==="home"?"index, follow, max-snippet:-1, max-image-preview:large":"noindex, nofollow"}/>
      {kind==="home"?<>
        <link rel="canonical" href="https://kicad-mcp-pro.oaslananka.dev/"/>
        <meta property="og:type" content="website"/>
        <meta property="og:title" content="KiCad MCP Cloud — secure project access"/>
        <meta property="og:description" content={publicDescription}/>
        <meta property="og:image" content="https://kicad-mcp-pro.oaslananka.dev/assets/icon-512.png"/>
        <link rel="alternate" type="text/markdown" href="/index.md"/>
        <link rel="describedby" href="/llms.txt"/>
        <script type="application/ld+json" dangerouslySetInnerHTML={{__html:publicSchema}}/>
      </>:null}
      <link rel="icon" href="/favicon.ico" sizes="any"/>
      <link rel="icon" type="image/svg+xml" href="/favicon.svg"/>
      <link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png"/>
      <link rel="icon" type="image/png" sizes="16x16" href="/assets/favicon-16.png"/>
      <link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180"/>
      <link rel="manifest" href="/site.webmanifest"/>
      <link rel="stylesheet" href="/assets/ui.css"/><title>{title+" — KiCad MCP Cloud"}</title>
    </head><body><div className={workspace?"app-shell workspace-app":"app-shell"}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      {workspace?<WorkspaceNav kind={kind}/>:<header className="site-header"><div className="header-inner">
        <Brand/>
        <div className="header-right">
          <span className="release-label"><Icon name="shield" size={15}/> Your projects. Your permissions.</span>
          <nav className="public-nav" aria-label="Primary"><NavLink href="/" current={kind==="home"}>Overview</NavLink>
            {navEnabled?<NavLink href="/account" current={false}>Workspace</NavLink>:null}</nav>
        </div>
      </div></header>}
      <main id="main-content" className={"site-main page-"+kind}>
        <div className={workspace?"workspace-layout":"content-wrap"}>
          <div className="main-content">
            <div className="page-heading"><div><div className="eyebrow">{eyebrow??"KiCad MCP Cloud"}</div>
              <h1>{title}</h1>{summary?<p className="summary">{summary}</p>:null}</div>{actions}</div>
            {children}
          </div>
        </div>
      </main>
      {workspace?null:<footer className="site-footer"><div className="footer-inner"><span>© KiCad MCP Cloud <span className="footer-separator">/</span> <a href="https://oaslananka.github.io/kicad-mcp-pro/glossary/">Glossary</a></span>
        <span>Local files <span className="footer-separator">/</span> Explicit project access <span className="footer-separator">/</span> Your control</span></div></footer>}
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
          <span><strong>KiCad on your computer</strong><small>Available only after owner pairing and project approval</small></span>
          <span className="topology-tag">Owner pairing required</span>
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
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="devices" size={19}/></span><span>02</span></div><h3>Pair your computer</h3><p>Pair from the local Connector and approve the request in your Cloud workspace. Pairing alone never shares projects.</p><span className="step-state">Your approval required</span></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="connections" size={19}/></span><span>03</span></div><h3>Connect your AI client</h3><p>Follow the connection guide and review the app's account permissions.</p></div>
        <div className="step"><div className="step-index"><span className="step-icon"><Icon name="cpu" size={19}/></span><span>04</span></div><h3>Choose project access</h3><p>Select a project on your own computer, then explicitly grant each connected AI client access.</p></div>
      </div>
    </section>
  </div>;
}
export function Notice({message}:{readonly message:string}){
  return <section className="card detail-card"><div className="notice-icon"><Icon name="warning" size={22}/></div>
    <h2>We couldn't complete that action</h2><p>{message}</p><a href="/" className="text-link">Return to overview <Icon name="arrow" size={16}/></a></section>;
}
export function SignIn({query,providers,pairing=false}:{readonly query:string;readonly providers:ReadonlyArray<"google"|"github">;readonly pairing?:boolean}){
  return <section className="card auth-card">
    <div className="panel-heading"><div className="panel-icon"><Icon name="lock" size={21}/></div>
      <div><h2>Your workspace starts here</h2><p>Choose an available account to continue.</p></div></div>
    {pairing?<p>Sign in or create an account to approve the device connection you just started from the CLI. This does not grant project access.</p>:null}
    <div className="providers">{providers.includes("google")&&<form action="/auth/start/google" method="post">
      <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
        <span className="provider-logo">G</span> Continue with Google <Icon name="arrow" size={17} className="provider-arrow"/></button>
    </form>}{providers.includes("github")&&<form action="/auth/start/github" method="post">
      <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
        <span className="provider-logo github"><Icon name="github" size={21}/></span> Continue with GitHub <Icon name="arrow" size={17} className="provider-arrow"/></button>
    </form>}</div>
    {pairing?<script defer={true} src="/assets/pairing-login-continuation.js"></script>:null}
    <div className="auth-footnote"><Icon name="shield" size={19}/><p>Signing in doesn't share your KiCad projects. AI client permissions and project access require separate approval.</p></div>
  </section>;
}
export function Account({name,providers=["google","github"],linked=[]}:{
  readonly name:string;
  readonly providers?:ReadonlyArray<"google"|"github">;
  readonly linked?:ReadonlyArray<"google"|"github">;
}){
  return <div className="page-stack">
    <script defer={true} src="/assets/pairing-login-continuation.js"></script>
    <section className="account-welcome" aria-label="Account status"><div className="account-banner">
      <span className="avatar" aria-hidden="true">{name.trim().slice(0,1).toUpperCase()||"U"}</span>
      <div><div className="card-kicker">YOUR ACCOUNT</div>
        <h2>{name}</h2><p>Review your computers, project access and AI connections below.</p></div>
    </div><span className="status-pill ready"><Icon name="check" size={14}/> Signed in</span></section>
    <section className="card" aria-labelledby="sign-in-methods">
      <div className="section-head"><div><div className="card-kicker">ACCOUNT SECURITY</div>
        <h2 id="sign-in-methods">Sign-in methods</h2></div></div>
      <p>Link another sign-in provider only after signing in to this account.
        Accounts are never merged automatically just because emails match.</p>
      <div className="providers">{providers.map(provider=><div key={provider}>
        {linked.includes(provider)
          ? <p><strong>{provider==="google"?"Google":"GitHub"}</strong> — Connected</p>
          : <form action={"/auth/link/"+provider} method="post">
            <button className="button provider" type="submit">
              Connect {provider==="google"?"Google":"GitHub"} to this account
            </button></form>}
      </div>)}</div>
    </section>
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
