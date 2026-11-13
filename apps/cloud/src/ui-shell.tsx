import type {ReactNode} from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {Icon} from "./ui-icons.js";

export type PageKind="home"|"sign-in"|"account"|"projects"|"consent"|"connections"|"devices"|"notice"|"usage"|"settings";
type Props=Readonly<{title:string;eyebrow?:string;summary?:string;kind:PageKind;children:ReactNode;navEnabled?:boolean;actions?:ReactNode;userEmail?:string}>;
const workspacePages=new Set<PageKind>(["account","projects","connections","devices","usage","settings"]);
// The Python Streamable HTTP transport stays; no Tauri desktop binary is required.
const httpGuideUrl="https://oaslananka.github.io/kicad-mcp-pro/installation/";
const localHttpCommand="uvx kicad-mcp-pro --transport streamable-http --host 127.0.0.1 --port 3334";
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
function NavLink({href,current,children}:Readonly<{href:string;current:boolean;children:ReactNode}>){
  return <a href={href} aria-current={current?"page":undefined}>{children}</a>;
}
function Brand({workspace=false}:Readonly<{workspace?:boolean}>){
  return <a href={workspace?"/projects":"/"} className="brand" aria-label="KiCad MCP Cloud workspace home">
    <span className="brand-mark"><img className="brand-logo" src="/assets/icon-32.png" alt="" width={24} height={24} srcSet="/assets/icon-32.png 1x, /assets/icon-64.png 2x" decoding="async"/></span>
    <span className="brand-title">KiCad MCP <small>Cloud workspace</small></span>
  </a>;
}
function WorkspaceNav({kind,userEmail}:Readonly<{kind:PageKind;userEmail?:string}>){
  const cleanEmail=userEmail?.trim();
  const initials=cleanEmail?.includes("@")
    ? cleanEmail.slice(0,2).toUpperCase()
    : "OA";
  const displayEmail=cleanEmail||"Account";

  return <aside className="workspace-sidebar" aria-label="Workspace navigation">
    <Brand workspace/>
    <div className="sidebar-section-label">WORKSPACE</div>
    <nav className="sidebar-links" aria-label="Workspace">
      <NavLink href="/projects" current={kind==="projects"}><Icon name="projects" size={17}/> Projects</NavLink>
      <NavLink href="/devices" current={kind==="devices"}><Icon name="devices" size={17}/> Devices</NavLink>
      <NavLink href="/connections" current={kind==="connections"}><Icon name="connections" size={17}/> AI connections</NavLink>
      <NavLink href="/usage" current={kind==="usage"}><Icon name="usage" size={17}/> Usage</NavLink>
      <NavLink href="/account" current={kind==="account"}><Icon name="overview" size={17}/> Overview</NavLink>
      <NavLink href="/settings" current={kind==="settings"}><Icon name="settings" size={17}/> Settings</NavLink>
    </nav>
    <a href="/settings" className="sidebar-profile" aria-label="Account and security settings" title={displayEmail}>
      <span className="profile-avatar" aria-hidden="true">{initials}</span>
      <span className="profile-identity">{displayEmail}</span>
    </a>
    <div className="sidebar-footer-links">
      <a href="https://oaslananka.github.io/kicad-mcp-pro/" target="_blank" rel="noopener noreferrer">Docs</a>
      <span className="footer-dot" aria-hidden="true">·</span>
      <a href="https://github.com/oaslananka/kicad-mcp-pro" target="_blank" rel="noopener noreferrer">GitHub</a>
      <span className="footer-dot" aria-hidden="true">·</span>
      <a href="/connections">Privacy</a>
      <span className="footer-dot" aria-hidden="true">·</span>
      <a href="/settings">Security</a>
    </div>
  </aside>;
}
function PublicHeader({kind,navEnabled}:Pick<Props,"kind"|"navEnabled">){
  const home=kind==="home";
  return <header className="site-header"><div className="header-inner">
    <Brand/>
    <div className="header-right">
      <span className="release-label"><Icon name="shield" size={15}/> Your projects. Your permissions.</span>
      <nav className="public-nav" aria-label="Primary"><NavLink href="/" current={home}>Overview</NavLink>
        <a href={home?"#http-setup":httpGuideUrl} target={home?undefined:"_blank"} rel={home?undefined:"noopener noreferrer"}>HTTP setup</a>
        {navEnabled?<NavLink href="/projects" current={false}>Workspace</NavLink>:null}</nav>
    </div>
  </div></header>;
}
export function renderPage({title,eyebrow,summary,kind,children,navEnabled=true,actions,userEmail}:Props):string{
  const workspace=workspacePages.has(kind);
  return "<!doctype html>"+renderToStaticMarkup(
    <html lang="en"><head>
      <meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
      <meta name="theme-color" content="#0c0f10"/>
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
      <link rel="icon" type="image/png" sizes="32x32" href="/assets/favicon-32.png"/>
      <link rel="icon" type="image/png" sizes="16x16" href="/assets/favicon-16.png"/>
      <link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180"/>
      <link rel="manifest" href="/site.webmanifest"/>
      <link rel="stylesheet" href="/assets/ui.css"/><title>{title+" — KiCad MCP Cloud"}</title>
    </head><body><div className={workspace?("app-shell workspace-app"):"app-shell"}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      {workspace?<WorkspaceNav kind={kind} userEmail={userEmail}/>:<PublicHeader kind={kind} navEnabled={navEnabled}/>}
      <main id="main-content" className={"site-main page-"+kind}>
        {workspace?<div className="workspace-topbar"><span className="workspace-breadcrumb"><a href="/projects">Workspace</a> <span aria-hidden="true">/</span> {title}</span>
          <div className="workspace-topbar-actions"><span><Icon name="lock" size={15}/> Local files stay private</span>
            <a href="https://oaslananka.github.io/kicad-mcp-pro/" target="_blank" rel="noopener noreferrer">Documentation <Icon name="arrow" size={14}/></a>
          </div></div>:null}
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
export function SettingsHome({identity}:{readonly identity?:string}){
  return <div className="page-stack settings-workspace">
    <section className="card detail-card" aria-label="Account security">
      <div className="card-kicker"><Icon name="shield" size={15}/> ACCOUNT &amp; SECURITY</div>
      <h2>You're in control of every connection.</h2>
      <p>Your account sign-in, AI permissions and paired computers are separate.
         A connected app never automatically receives access to a KiCad project.</p>
      {identity?<p className="settings-signed-in"><Icon name="check" size={15}/>
        Signed in as <strong>{identity}</strong></p>:null}
      <a className="button secondary" href="/account#security">Manage sign-in methods <Icon name="arrow" size={15}/></a>
    </section>
    <div className="overview-tiles" aria-label="Security controls">
      <a className="overview-tile" href="/devices">
        <span className="tile-icon"><Icon name="devices" size={20}/></span>
        <span className="tile-body"><strong>Paired computers</strong>
          <small>Check connection status and revoke a device if necessary.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
      <a className="overview-tile" href="/devices#registered-projects">
        <span className="tile-icon"><Icon name="projects" size={20}/></span>
        <span className="tile-body"><strong>Project permissions</strong>
          <small>Pause reads or remove an AI client's access to a project.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
      <a className="overview-tile" href="/connections">
        <span className="tile-icon"><Icon name="connections" size={20}/></span>
        <span className="tile-body"><strong>Authorized AI apps</strong>
          <small>Review and revoke OAuth connections.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
    </div>
    <p className="card-footnote-inline"><Icon name="lock" size={14}/>
      Native remote project editing is not enabled. Changes require explicit local owner approval.</p>
    <nav className="settings-support-links" aria-label="Help and policies">
      <a href="https://oaslananka.github.io/kicad-mcp-pro/" target="_blank" rel="noopener noreferrer">Documentation</a>
      <a href="https://oaslananka.github.io/kicad-mcp-pro/privacy/" target="_blank" rel="noopener noreferrer">Privacy policy</a>
      <a href="https://github.com/oaslananka/kicad-mcp-pro" target="_blank" rel="noopener noreferrer">GitHub</a>
    </nav>
  </div>;
}

export function Landing({identityEnabled}:{readonly identityEnabled:boolean}){
  const cloudChoice=<>
    <span className="entry-choice-icon"><Icon name="connections" size={23}/></span>
    <span className="entry-choice-copy"><small>CLOUD WORKSPACE</small><strong>Connect through Cloud</strong>
      <span>{identityEnabled?"Sign in. Pair your computer. Approve each project and AI client separately.":
        "Cloud sign-in is unavailable on this deployment. Pair your computer after account access is enabled."}</span>
      <b>{identityEnabled?"Open Cloud setup":"Cloud sign-in unavailable"} {identityEnabled?<Icon name="arrow" size={15}/>:null}</b></span>
    {identityEnabled?<Icon name="arrow" size={19} className="entry-choice-arrow"/>:null}
  </>;
  return <div className="page-stack">
    <section className="card landing-panel" aria-label="Cloud capabilities">
      <div className="landing-intro">
        <span className={identityEnabled?"status-pill neutral":"status-pill pending"}>
          {identityEnabled?"Account sign-in available":"Account access pending"}
        </span>
        <div className="landing-product-label"><Icon name="shield" size={15}/> YOUR COMPUTER · YOUR PROJECTS</div>
        <h2>Connect KiCad to AI.<br/><span className="landing-accent">Stay in control.</span></h2>
        <p>Connect your computer, choose a KiCad project and bring your AI assistant. Your files stay local. You decide which apps have access.</p>
        <div className="action-row">
          {identityEnabled?<a className="button primary" href="/sign-in">Connect your computer <Icon name="arrow" size={16}/></a>
            :<span className="button disabled" aria-disabled="true">Cloud sign-in pending</span>}
          <a className="button secondary" href="#http-setup">Start local HTTP <Icon name="arrow" size={17}/></a>
        </div>
        <p className="hero-note"><Icon name="shield" size={16}/> Local HTTP requires no Cloud account. Remote project access needs explicit approval.</p>
      </div>
      <div className="topology-panel" aria-label="Current connection availability">
        <div className="topology-eyebrow">ACCESS ARCHITECTURE <span className="topology-eyebrow-dot"/></div>
        <div className="topology-node topology-node-client"><span className="topology-icon"><Icon name="connections" size={21}/></span>
          <span><strong>Your AI assistant</strong><small>{identityEnabled?"Client consent required":"Account access pending"}</small></span>
          <span className="topology-indicator"/>
        </div>
        <div className="topology-link inactive"><span/><small>EXPLICIT PERMISSIONS</small></div>
        <div className="topology-node topology-node-cloud"><span className="topology-icon"><Icon name="cloud" size={21}/></span>
          <span><strong>KiCad MCP Cloud</strong><small>Account &amp; project access</small></span>
          <span className="topology-indicator"/>
        </div>
        <div className="topology-link inactive"><span/><small>SEPARATE DEVICE APPROVAL</small></div>
        <div className="topology-node topology-node-device"><span className="topology-icon"><Icon name="cpu" size={21}/></span>
          <span><strong>KiCad on your computer</strong><small>Available only after owner pairing and project approval</small></span>
          <span className="topology-tag">Owner pairing required</span>
        </div>
        <div className="topology-foot"><Icon name="lock" size={15}/> No project files are shared by signing in.</div>
      </div>
    </section>
    <section className="entry-choices" aria-label="Choose how to start">
      {identityEnabled?
        <a className="entry-choice entry-choice-cloud" href="/sign-in">{cloudChoice}</a>:
        <div className="entry-choice entry-choice-cloud unavailable" aria-disabled="true">{cloudChoice}</div>}
      <a className="entry-choice entry-choice-primary" href="#http-setup">
        <span className="entry-choice-icon"><Icon name="cpu" size={23}/></span>
        <span className="entry-choice-copy"><small>LOCAL · NO ACCOUNT NEEDED</small><strong>Use KiCad MCP locally</strong>
          <span>Keep KiCad projects on your computer. Connect an AI client.</span><b>View the command <Icon name="arrow" size={15}/></b></span>
        <Icon name="arrow" size={19} className="entry-choice-arrow"/>
      </a>
    </section>
    <section className="card http-setup-callout" id="http-setup" aria-labelledby="http-start-title">
      <div className="http-setup-heading">
        <span className="http-setup-icon"><Icon name="cpu" size={22}/></span>
        <div><span className="card-kicker">LOCAL · STREAMABLE HTTP</span>
          <h2 id="http-start-title">Start in your terminal</h2>
          <p>Use the existing Python HTTP server on your machine. Run the Python service directly.</p></div>
      </div>
      <code className="http-command">{localHttpCommand}</code>
      <div className="http-setup-footer"><span>Local endpoint: <code>http://127.0.0.1:3334/mcp</code></span>
        <a className="text-link" href={httpGuideUrl} target="_blank" rel="noopener noreferrer">Setup guide <Icon name="arrow" size={15}/></a></div>
    </section>
    <section className="next-section" aria-labelledby="how-it-works">
      <div className="section-head"><div><div className="card-kicker">ONLY WHEN NEEDED</div>
        <h2 id="how-it-works">Need remote AI access?</h2></div>
        <p>Each permission is independent.</p></div>
      <details className="home-setup-guide"><summary>See Cloud connection steps <Icon name="arrow" size={15}/></summary>
        <div className="steps-grid">
          <div className="step"><div className="step-index"><span className="step-icon"><Icon name="key" size={19}/></span><span>01</span></div><h3>Sign in</h3><p>Use Cloud only if you need remote MCP access.</p></div>
          <div className="step"><div className="step-index"><span className="step-icon"><Icon name="devices" size={19}/></span><span>02</span></div><h3>Pair a computer</h3><p>Approve a Connector device in your browser. Pairing does not share projects.</p></div>
          <div className="step"><div className="step-index"><span className="step-icon"><Icon name="connections" size={19}/></span><span>03</span></div><h3>Authorize your AI</h3><p>Review OAuth consent for your client.</p></div>
          <div className="step"><div className="step-index"><span className="step-icon"><Icon name="shield" size={19}/></span><span>04</span></div><h3>Grant project access</h3><p>Choose exactly which registered project metadata your AI can read.</p></div>
        </div>
      </details>
      <details className="setup-faq"><summary>Troubleshooting &amp; permissions <Icon name="arrow" size={15}/></summary>
        <div className="setup-help">
          <p><strong>No projects listed?</strong> Check that your local Connector is running and that your paired computer appears under <a href="/devices">Devices &amp; projects</a>; then authorize a project for your AI client.</p>
          <p><strong>Want to stop sharing?</strong> Open <a href="/connections">AI connections</a> to revoke authorization. Signing in never shares files by itself.</p>
        </div>
      </details>
    </section>
  </div>;
}
export function Notice({message}:{readonly message:string}){
  return <section className="card detail-card"><div className="notice-icon"><Icon name="warning" size={22}/></div>
    <h2>We couldn't complete that action</h2><p>{message}</p><a href="/" className="text-link">Return to overview <Icon name="arrow" size={16}/></a></section>;
}
export function SignIn({query,providers,pairing=false}:{
  readonly query:string;readonly providers:ReadonlyArray<"google"|"github">;readonly pairing?:boolean
}){
  return <section className="auth-stage" aria-label="KiCad MCP Cloud sign in">
    <div className="auth-intro">
      <div className="card-kicker">KICAD MCP CLOUD</div>
      <h2>Your projects. Your control.</h2>
      <p className="auth-lead">Connect your AI tools to the KiCad projects you choose. Your design files remain on your own computer.</p>
      <div className="auth-journey" aria-label="How Cloud access works">
        <div className="auth-journey-step"><span>01</span><div><strong>Sign in</strong><p>Continue with an available account.</p></div></div>
        <div className="auth-journey-step"><span>02</span><div><strong>Pair your computer</strong><p>Approve the matching device code in your browser.</p></div></div>
        <div className="auth-journey-step"><span>03</span><div><strong>Choose project access</strong><p>Grant each AI client access separately. Nothing is shared automatically.</p></div></div>
      </div>
      <p className="auth-mobile-journey">Next: sign in → pair your computer → approve project access.</p>
      <div className="auth-local-note"><Icon name="lock" size={17}/><span>Using KiCad locally never requires a Cloud account.</span></div>
    </div>
    <div className="card auth-card">
      <div className="panel-heading"><div className="panel-icon"><Icon name="shield" size={21}/></div>
        <div><div className="card-kicker">{pairing?"DEVICE APPROVAL":"SECURE ACCOUNT ACCESS"}</div>
          <h2>{pairing?"Approve your computer":"Welcome back"}</h2>
          <p>{pairing?"Sign in to continue the device approval you started locally.":"Choose a provider to open your Cloud workspace."}</p></div>
      </div>
      <div className="providers">{providers.includes("google")&&<form action="/auth/start/google" method="post">
        <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
          <span className="provider-logo">G</span> Continue with Google <Icon name="arrow" size={17} className="provider-arrow"/></button>
      </form>}{providers.includes("github")&&<form action="/auth/start/github" method="post">
        <input type="hidden" name="oauth_query" value={query}/><button className="button provider" type="submit">
          <span className="provider-logo github"><Icon name="github" size={21}/></span> Continue with GitHub <Icon name="arrow" size={17} className="provider-arrow"/></button>
      </form>}</div>
      {providers.length===0?<output className="auth-unavailable">Account sign-in is temporarily unavailable. Your local KiCad workspace continues to work without Cloud.</output>:null}
      {pairing?<script defer={true} src="/assets/pairing-login-continuation.js"></script>:null}
      <div className="auth-footnote"><Icon name="shield" size={19}/><p>Signing in does not pair a device or share a project. Access requires independent, explicit approval.</p></div>
      <a className="auth-download-link" href={httpGuideUrl} target="_blank" rel="noopener noreferrer">Prefer local use? Set up HTTP without Cloud <Icon name="arrow" size={15}/></a>
    </div>
  </section>;
}
type WorkspaceSnapshot={devices:number;projects:number;clients:number;grants:number};
function workspaceNextAction(snapshot?:WorkspaceSnapshot){
  if(!snapshot)return {id:"review-devices",title:"See what's connected",detail:"Review your computers and project access.",href:"/devices",label:"Open devices"};
  if(snapshot.devices===0)return {id:"pair-device",title:"Connect your first computer",detail:"Start with your KiCad device. Signing in shares nothing.",href:"/devices",label:"Review devices"};
  if(snapshot.projects===0)return {id:"add-project",title:"Choose a KiCad project",detail:"Register only a project you wish to authorize.",href:"/devices#registered-projects",label:"Review projects"};
  if(snapshot.clients===0)return {id:"connect-client",title:"Connect an AI tool",detail:"Choose an assistant and review its access request.",href:"/connections",label:"Manage AI connections"};
  if(snapshot.grants===0)return {id:"grant-access",title:"Decide what AI can see",detail:"Project access is separate from account consent.",href:"/devices#registered-projects",label:"Review permissions"};
  return {id:"review-access",title:"Review your connections",detail:"Saved permissions and current device status are separate.",href:"/devices",label:"Review access"};
}
export function Account({name,providers=["google","github"],linked=[],snapshot}:{
  readonly name:string;
  readonly providers?:ReadonlyArray<"google"|"github">;
  readonly linked?:ReadonlyArray<"google"|"github">;
  readonly snapshot?:WorkspaceSnapshot;
}){
  const nextAction=workspaceNextAction(snapshot);
  return <div className="page-stack account-dashboard">
    <script defer={true} src="/assets/pairing-login-continuation.js"></script>
    <section className="account-welcome" aria-label="Account status">
      <div className="account-banner">
        <span className="avatar" aria-hidden="true">{name.trim().slice(0,1).toUpperCase()||"U"}</span>
        <div><div className="card-kicker">SIGNED-IN WORKSPACE</div>
          <h2>{name}</h2><p>Your devices, AI connections and project access.</p></div>
      </div>
      <span className="status-pill ready"><Icon name="check" size={14}/> Signed in</span>
    </section>
    <section className="premium-focus-panel" aria-label="Workspace next action" data-next-action={nextAction.id}>
      <div><span className="focus-eyebrow"><Icon name="spark" size={16}/> YOUR NEXT STEP</span>
        <h2>{nextAction.title}</h2><p>{nextAction.detail}</p></div>
      <a className="button primary" href={nextAction.href}>{nextAction.label} <Icon name="arrow" size={18}/></a>
    </section>
    {snapshot?<section className="card detail-card workspace-snapshot-card" aria-label="Workspace snapshot">
      <div className="card-kicker">WORKSPACE SNAPSHOT</div>
      <h2>Workspace snapshot</h2>
      <div className="snapshot-grid">
        {([
          {value:snapshot.devices,label:"Paired devices",href:"/devices",icon:"devices"},
          {value:snapshot.projects,label:"Enabled projects",href:"/devices#registered-projects",icon:"cpu"},
          {value:snapshot.clients,label:"AI clients",href:"/connections",icon:"connections"},
          {value:snapshot.grants,label:"Project grants",href:"/devices#registered-projects",icon:"shield"}
        ] as const).map(item=><a className="snapshot-card" href={item.href} key={item.label}>
          <span className="snapshot-icon"><Icon name={item.icon} size={19}/></span>
          <div className="metric">{item.value}</div><div className="metric-label">{item.label}</div>
          <Icon name="arrow" size={16} className="snapshot-link-arrow"/>
        </a>)}
      </div>
      <p className="card-footnote-inline"><Icon name="lock" size={13}/> Saved permissions do not guarantee a connected device or an active KiCad session.</p>
    </section>:<output>Workspace snapshot unavailable. Review devices and connections below.</output>}
    <section className="overview-tiles" aria-label="Workspace areas">
      <a className="overview-tile" href="/devices">
        <span className="tile-icon"><Icon name="devices" size={20}/></span>
        <span className="tile-body"><strong>Devices &amp; projects</strong><small>Check registered computers, availability and approved project access.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
      <a className="overview-tile" href="/connections">
        <span className="tile-icon"><Icon name="connections" size={20}/></span>
        <span className="tile-body"><strong>AI connections</strong><small>Review actual authorized applications and revoke access.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
      <a className="overview-tile" href="/devices#registered-projects">
        <span className="tile-icon"><Icon name="shield" size={20}/></span>
        <span className="tile-body"><strong>Project permissions</strong><small>Manage client-specific read-only grants on registered projects.</small></span>
        <Icon name="arrow" size={17} className="tile-arrow"/>
      </a>
    </section>
    <div className="account-columns">
      <section className="card setup-checklist" aria-labelledby="connection-checklist">
        <div className="section-head"><div><div className="card-kicker">GET CONNECTED</div>
          <h2 id="connection-checklist">Your connection checklist</h2></div>
          <span className="section-note">Each approval is independent</span>
        </div>
        <details className="checklist-disclosure"><summary>Show detailed checklist <Icon name="arrow" size={15}/></summary><ol className="checklist-list">
          <li><span className="checklist-number complete"><Icon name="check" size={16}/></span><div><h3>Cloud account</h3><p>You're signed in to your workspace.</p></div><span className="status-pill ready">Signed in</span></li>
          <li><span className="checklist-number">02</span><div><h3>Computer &amp; project</h3><p>Review actual device status and register projects on your computer.</p></div><a className="text-link" href="/devices">Review devices <Icon name="arrow" size={15}/></a></li>
          <li><span className="checklist-number">03</span><div><h3>AI connection</h3><p>Connect a compatible AI client and review its account permissions.</p></div><a className="text-link" href="/connections">Manage connections <Icon name="arrow" size={15}/></a></li>
          <li><span className="checklist-number">04</span><div><h3>Project permissions</h3><p>Grant your authorized AI client access to a specific registered project.</p></div><a className="text-link" href="/devices#registered-projects">Review projects <Icon name="arrow" size={15}/></a></li>
        </ol></details>
      </section>
      <aside className="account-side">
        <section className="card account-security" aria-labelledby="sign-in-methods">
          <div className="section-head"><div><div className="card-kicker">ACCOUNT SECURITY</div>
            <h2 id="sign-in-methods">Sign-in methods</h2></div></div>
          <p>Only link providers after signing in. Matching email addresses do not automatically merge accounts.</p>
          <div className="providers">{providers.map(provider=><div key={provider} className="identity-row">
            {linked.includes(provider)
              ? <><span className="identity-name">{provider==="google"?"Google":"GitHub"}</span>
                <span className="status-pill ready"><Icon name="check" size={14}/> Connected</span></>
              : <form action={"/auth/link/"+provider} method="post">
                <button className="button provider" type="submit">
                  Connect {provider==="google"?"Google":"GitHub"} to this account
                </button></form>}
          </div>)}</div>
        </section>
        <aside className="workspace-reminder"><Icon name="lock" size={18}/>
          <p>An authorized AI app does not automatically have project access.
             A connected device does not by itself prove that KiCad is ready.</p></aside>
      </aside>
    </div>
  </div>;
}
