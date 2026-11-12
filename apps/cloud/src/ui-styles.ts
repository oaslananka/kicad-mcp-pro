// Shared first-party design tokens. No font, script or image CDN is required.
export const uiCss = String.raw`
:root{
  color-scheme:dark;
  --bg:#090a0d;
  --surface:#191b20;
  --surface-raised:#24272e;
  --surface-soft:#12151a;
  --surface-glass:rgba(18,20,24,0.96);
  --line:rgba(173,185,203,0.14);
  --line-strong:rgba(173,185,203,0.28);
  --text:#f4f7fa;
  --text-secondary:#d3d9e5;
  --muted:#a5afbf;
  --muted-soft:#8794a8;
  --accent:#279fff;
  --accent-hover:#73c0ff;
  --accent-soft:rgba(39,159,255,0.12);
  --accent-border:rgba(39,159,255,0.26);
  --primary:#0876cb;
  --primary-hover:#0a67b5;
  --on-accent:#fff;
  --blue:var(--accent);
  --blue-strong:var(--accent-hover);
  --green:#10b981;
  --green-soft:rgba(16,185,129,0.12);
  --green-border:rgba(16,185,129,0.25);
  --amber:#f59e0b;
  --amber-soft:rgba(245,158,11,0.12);
  --amber-border:rgba(245,158,11,0.25);
  --danger:#ef4444;
  --danger-soft:rgba(239,68,68,0.12);
  --danger-border:rgba(239,68,68,0.28);
  --positive-bg:rgba(16,185,129,0.12);
  --warning-bg:rgba(245,158,11,0.12);
  --danger-bg:rgba(239,68,68,0.12);
  --radius:10px;
  --radius-sm:7px;
  --radius-lg:14px;
  --shadow:0 10px 25px -5px rgba(0,0,0,0.4),0 8px 10px -6px rgba(0,0,0,0.4);
  --shadow-sm:0 2px 8px rgba(0,0,0,0.25);
  --transition:160ms cubic-bezier(0.16,1,0.3,1);
  --font-sans:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --font-mono:'JetBrains Mono','Fira Code',ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
}

/* ── Reset & Core ── */
*{box-sizing:border-box}
html{min-height:100%;background:var(--bg);scroll-behavior:smooth;scroll-padding-top:90px}
body{min-height:100vh;margin:0;background:var(--bg);color:var(--text);font-family:var(--font-sans);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
button,input,select,textarea{font:inherit}
button{cursor:pointer}
a,button,input,select,summary{touch-action:manipulation}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--accent)}
a:hover{text-decoration:none}
.text-link:hover,.mini-link:hover{text-decoration:underline;text-underline-offset:4px}
[hidden]{display:none!important}
code,.checklist-number,.device-summary h3{font-family:var(--font-mono)}
h1,h2,h3,p{overflow-wrap:anywhere}

/* ── Accessibility ── */
.skip-link{position:fixed;left:16px;top:-80px;background:var(--accent);color:var(--on-accent);font-weight:700;padding:12px 18px;z-index:100;border-radius:var(--radius-sm);transition:top var(--transition)}
.skip-link:focus{top:12px}

/* ── Shell & Navigation ── */
.app-shell{min-height:100vh;display:flex;flex-direction:column}
.site-main{flex:1;min-width:0;background:radial-gradient(ellipse 85% 35% at 65% -30%,rgba(39,159,255,0.06),transparent),var(--bg)}
.site-header{background:var(--surface-glass);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:30}
.header-inner{max-width:1600px;min-height:70px;margin:auto;padding:0 36px;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:inline-flex;align-items:center;gap:11px;font-size:15px;font-weight:650;white-space:nowrap;letter-spacing:-.025em;min-width:0}
.brand-mark{width:38px;height:38px;min-width:38px;max-width:38px;aspect-ratio:1;display:grid;place-items:center;overflow:hidden;border:1px solid rgba(39,159,255,.19);border-radius:10px;background:rgba(39,159,255,.06)}
.brand-mark .brand-logo{width:24px;height:24px;min-width:24px;max-width:24px;max-height:24px;aspect-ratio:1;object-fit:contain;object-position:center;display:block;flex:none}
.brand-title{display:flex;flex-direction:column;align-items:flex-start;gap:1px;line-height:1.25}
.brand-title small{font-size:11px;letter-spacing:0;color:var(--muted);font-weight:400}
.header-right,.public-nav{display:flex;align-items:center;gap:24px}
.release-label{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.public-nav a,.header-account{display:inline-flex;align-items:center;gap:8px;min-height:44px;font-size:13px;font-weight:600;color:var(--text-secondary);transition:color var(--transition)}
.public-nav a:hover{color:var(--accent)}
.public-nav a[aria-current=page]{color:var(--accent)}
.header-account{padding:0 14px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--surface-soft)}

/* ── Workspace App ── */
.workspace-app>.site-main{margin-left:246px}
.workspace-layout{width:100%;max-width:1800px;padding:32px clamp(22px,3.2vw,56px) 65px;margin:0}
.workspace-sidebar{position:fixed;inset:0 auto 0 0;width:246px;overflow-y:auto;z-index:20;padding:22px 12px 16px;border-right:1px solid var(--line);background:#0e1015;display:flex;flex-direction:column}
.workspace-sidebar>.brand{padding:0 9px;margin-bottom:32px;min-height:36px}
.sidebar-section-label{font-size:11px;letter-spacing:.12em;font-weight:750;color:var(--muted-soft);margin:0 12px 10px}
.workspace-sidebar .sidebar-links{display:grid;gap:4px;margin-bottom:26px}
.sidebar-links a{display:flex;align-items:center;gap:10px;min-height:44px;padding:10px 12px;color:var(--muted);font-size:13px;font-weight:550;border-radius:var(--radius-sm);border:1px solid transparent;transition:all var(--transition)}
.sidebar-links a svg{flex:none}
.sidebar-links a:hover{background:var(--surface-soft);color:var(--text);border-color:var(--line)}
.sidebar-links a[aria-current=page]{background:rgba(39,159,255,.1);border-color:rgba(39,159,255,.17);color:var(--accent);font-weight:650}
.sidebar-quick-usage{margin-top:auto;padding:14px;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface-soft);display:flex;flex-direction:column;gap:8px}
.usage-meter-header{display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:600;color:var(--text)}
.usage-meter-percent{color:var(--accent);font-family:var(--font-mono);font-size:11px}
.usage-meter-bar{width:100%;height:5px;border-radius:3px;background:rgba(255,255,255,0.08);overflow:hidden}
.usage-meter-fill{height:100%;background:linear-gradient(90deg,var(--accent),#729fe8);border-radius:3px;transition:width 0.3s ease}
.usage-meter-meta{display:flex;flex-direction:column;gap:2px;font-size:11px;color:var(--muted)}
.usage-reset-note{font-size:10px;color:var(--muted-soft)}
.plan-active-btn{min-height:30px;padding:4px 10px;font-size:11px;font-weight:600;background:rgba(39,159,255,0.08);border:1px solid rgba(39,159,255,0.22);color:var(--accent);border-radius:6px;margin-top:4px;justify-content:center}
.plan-active-btn:hover{background:rgba(39,159,255,0.16);border-color:var(--accent);color:#fff}
.sidebar-profile{display:flex;align-items:center;gap:10px;padding:12px 10px;margin:8px 0 4px;border-radius:var(--radius-sm);background:rgba(255,255,255,0.02)}
.profile-avatar{width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,rgba(39,159,255,0.3),rgba(101,150,223,0.3));border:1px solid rgba(39,159,255,0.4);display:grid;place-items:center;font-size:11px;font-weight:700;color:var(--text);flex:none}
.profile-identity{font-size:12px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:550}
.sidebar-footer-links{display:flex;align-items:center;justify-content:center;gap:6px;padding:8px 0;font-size:11px;color:var(--muted-soft)}
.sidebar-footer-links a{color:var(--muted-soft);transition:color var(--transition)}
.sidebar-footer-links a:hover{color:var(--accent)}
.footer-dot{color:rgba(255,255,255,0.15)}

/* ── Workspace Topbar ── */
.workspace-topbar{min-height:56px;padding:0 clamp(22px,3.2vw,56px);background:#14171d;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:18px;margin-left:0}
.workspace-breadcrumb{font-size:13px;color:var(--muted);font-weight:600}
.workspace-breadcrumb span{color:var(--muted-soft);margin:0 9px}
.workspace-topbar-actions{display:flex;align-items:center;gap:22px}
.workspace-topbar-actions span,.workspace-topbar-actions a{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}
.workspace-topbar-actions a:hover{color:var(--accent)}

/* ── Content Layout & Headings ── */
.content-wrap{max-width:1560px;margin:0 auto;padding:35px clamp(20px,3vw,48px) 66px}
.content-wrap>.main-content{width:100%}.main-content{min-width:0}
.page-sign-in .content-wrap,.page-consent .content-wrap,.page-notice .content-wrap{max-width:1260px;padding-top:38px}
.page-heading{margin-bottom:28px}
.workspace-app .page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin-bottom:24px}
.workspace-app .page-heading>.button{flex:none}
.workspace-app .eyebrow{display:none}
.eyebrow,.card-kicker{font-size:11px;letter-spacing:.12em;text-transform:uppercase;font-weight:750;color:var(--accent);margin:0 0 8px}
h1{font-size:clamp(28px,3vw,38px);line-height:1.18;letter-spacing:-.045em;font-weight:700;margin:0 0 10px}
.workspace-app h1{font-size:clamp(25px,2.25vw,34px);letter-spacing:-.04em;margin-bottom:6px}
h2{font-size:21px;line-height:1.3;font-weight:680;letter-spacing:-.03em;margin:0 0 10px}
.workspace-app .card h2{font-size:17px}
h3{font-size:15px;line-height:1.4;font-weight:650;margin:0 0 5px}
.summary{max-width:760px;color:var(--muted);font-size:14px;line-height:1.75;margin:0}
.workspace-app .summary{max-width:760px;font-size:13px}
.page-stack{display:grid;gap:22px}
.workspace-app .page-stack{gap:20px}

/* ── Cards ── */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:24px;min-width:0;box-shadow:var(--shadow-sm);transition:border-color var(--transition)}
.card:hover{border-color:rgba(151,177,207,0.22)}
.card p{color:var(--muted);font-size:13px;line-height:1.7;margin:0}
.card-kicker:has(svg){display:flex;align-items:center;gap:8px}

/* ── Status Indicators ── */
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);flex-shrink:0}
.status-pill{display:inline-flex;align-items:center;gap:7px;align-self:flex-start;padding:6px 11px;border-radius:6px;font-size:12px;line-height:1.3;font-weight:600;background:var(--surface-raised);color:var(--muted);border:1px solid var(--line)}
.status-pill.ready{background:var(--positive-bg);color:var(--green);border-color:var(--green-border)}
.status-pill.pending{background:var(--warning-bg);color:var(--amber);border-color:var(--amber-border)}
.status-pill.neutral{background:var(--surface-raised);color:var(--muted);border-color:var(--line)}
.status-pill.danger{background:var(--danger-bg);color:var(--danger);border-color:var(--danger-border)}

/* ── Buttons & Links ── */
.button,button:not(.button){display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;max-width:100%;padding:10px 18px;border:1px solid var(--line-strong);border-radius:8px;color:var(--text);font-size:13px;font-weight:600;background:var(--surface-raised);line-height:1.5;transition:all var(--transition)}
.button:hover,button:not(.button):hover{background:#293c54;border-color:var(--accent-border);color:#fff}
.button.primary{background:var(--primary);border-color:var(--primary);color:var(--on-accent);box-shadow:0 2px 10px rgba(39,159,255,0.3);font-weight:700}
.button.primary:hover{background:var(--accent-hover);border-color:var(--accent-hover);color:var(--on-accent);box-shadow:0 4px 16px rgba(39,159,255,0.4)}
.button.secondary{background:var(--surface-soft);border-color:var(--line)}
.button.secondary:hover{background:var(--surface-raised);border-color:var(--line-strong)}
.button.reject{background:var(--surface-soft);border-color:var(--line)}
.button.reject:hover{background:var(--surface-raised);border-color:var(--line-strong)}
.button.disabled{color:var(--muted);background:var(--surface-soft);border-color:var(--line);cursor:not-allowed;opacity:.6}
.button.danger{background:var(--danger-bg);color:var(--danger);border-color:var(--danger-border);font-weight:600}
.button.danger:hover{background:rgba(239,68,68,0.22);border-color:var(--danger)}
.action-row,.form-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:22px}
.text-link,.mini-link{display:inline-flex;align-items:center;gap:7px;min-height:44px;font-size:13px;font-weight:650;color:var(--accent)}

/* ── Landing Page ── */
.landing-panel{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(330px,.92fr);padding:0;overflow:hidden;border:1px solid var(--line);border-radius:var(--radius);box-shadow:none;background:var(--surface)}
.landing-intro{padding:42px;background:linear-gradient(130deg,rgba(39,159,255,.06),transparent 60%)}
.landing-intro h2{font-size:clamp(30px,3.2vw,44px);line-height:1.15;letter-spacing:-.05em;margin:18px 0;font-weight:720}
.landing-intro>p:not(.hero-note){max-width:500px;font-size:14px;line-height:1.8}
.landing-accent{color:var(--accent)}
.landing-product-label{display:inline-flex;gap:8px;align-items:center;color:var(--accent);font-size:11px;font-weight:750;letter-spacing:.11em;margin:0 0 16px}
.landing-intro .action-row .button{min-height:48px;padding:11px 20px;font-size:13px}
.hero-note{display:flex;align-items:center;gap:8px;margin-top:24px!important;font-size:12px!important;color:var(--muted)!important}
.hero-note svg{flex:none;color:var(--accent)}
.landing-platforms{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-top:18px;font-size:12px;line-height:1.5}
.landing-platforms>span{color:var(--muted);width:100%}
.landing-platforms>a{display:inline-flex;align-items:center;min-height:36px;padding:7px 12px;border:1px solid var(--line-strong);border-radius:7px;color:var(--accent);font-weight:650;background:var(--surface-soft);font-size:12px}
.landing-platforms>a:hover{background:var(--surface-raised);border-color:var(--accent)}

/* ── Topology Panel ── */
.topology-panel{display:flex;flex-direction:column;justify-content:center;background:#13161b;padding:28px;border-left:1px solid var(--line)}
.topology-eyebrow{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:20px;color:var(--muted);font-size:10px;letter-spacing:.12em;font-weight:700}
.topology-eyebrow-dot{width:6px;height:6px;border-radius:50%;background:var(--line-strong)}
.topology-node{display:flex;align-items:center;gap:12px;min-width:0;padding:14px;background:#1a2636;border:1px solid var(--line);border-radius:8px;transition:border-color var(--transition)}
.topology-node>span:nth-child(2){display:grid;gap:3px;min-width:0}
.topology-node strong{font-size:13px;font-weight:650}
.topology-node small{font-size:11px;color:var(--muted);line-height:1.5}
.topology-icon{display:grid;place-items:center;flex:none;width:36px;height:36px;border-radius:8px;background:var(--surface-raised);color:var(--accent);border:1px solid var(--line)}
.topology-node-cloud{border-color:rgba(39,159,255,0.35);background:#1d3046}
.topology-node-device{border-style:dashed}
.topology-node-device .topology-icon{color:var(--muted)}
.topology-indicator{margin-left:auto;width:8px;height:8px;border-radius:50%;background:var(--line-strong);flex:none}
.topology-indicator.on{background:var(--green);box-shadow:0 0 8px rgba(16,185,129,.6)}
.topology-tag{margin-left:auto;font-size:10px;color:var(--amber);white-space:nowrap}
.topology-link{position:relative;height:34px;display:flex;align-items:center;justify-content:center}
.topology-link>span{position:absolute;inset-block:0;left:50%;border-left:1px solid var(--line-strong)}
.topology-link.inactive>span{border-left-style:dashed}
.topology-link small{position:relative;background:#13161b;color:var(--muted);padding:3px 9px;font-size:9px;letter-spacing:.09em;border-radius:4px;border:1px solid var(--line);font-weight:650}
.topology-foot{display:flex;align-items:center;justify-content:center;gap:8px;margin-top:20px;color:var(--muted);font-size:11px}

/* ── Entry Choices ── */
.entry-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.entry-choice{display:flex;align-items:flex-start;gap:18px;min-width:0;padding:24px;background:var(--surface);border:1px solid var(--line-strong);border-radius:12px;transition:all var(--transition)}
.entry-choice:hover{border-color:rgba(39,159,255,0.5);background:var(--surface-raised);transform:translateY(-2px);box-shadow:var(--shadow)}
.entry-choice-icon{display:grid;place-items:center;flex:none;width:48px;height:48px;border:1px solid rgba(39,159,255,0.2);border-radius:10px;color:var(--accent);background:rgba(39,159,255,0.08)}
.entry-choice>span:nth-child(2){display:grid;gap:6px;min-width:0}
.entry-choice small{font-size:11px;font-weight:750;letter-spacing:.1em;color:var(--accent)}
.entry-choice strong{font-size:16px;line-height:1.3;font-weight:690}
.entry-choice>span:nth-child(2)>span{color:var(--muted);font-size:13px;line-height:1.6}
.entry-choice-arrow{margin-left:auto;align-self:center;flex:none;color:var(--accent)}

/* ── Step Guides ── */
.next-section{padding-top:8px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:20px}
.section-head h2{margin:0}
.section-head p{max-width:320px;font-size:13px;color:var(--muted);line-height:1.7;text-align:right;margin:0}
.section-note{font-size:12px;color:var(--muted)}
.home-setup-guide{margin-top:18px;border:1px solid var(--line);border-radius:10px;background:var(--surface-soft);overflow:hidden}
.home-setup-guide>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 20px;min-height:50px;list-style:none;color:var(--text);font-size:14px;font-weight:650;cursor:pointer}
.home-setup-guide>summary::-webkit-details-marker{display:none}
.home-setup-guide>summary svg{flex:none;color:var(--accent);transition:transform var(--transition)}
.home-setup-guide[open]>summary svg{transform:rotate(90deg)}
.home-setup-guide[open]>summary{border-bottom:1px solid var(--line)}
.home-setup-guide>.steps-grid{padding:0 14px 14px}
.home-setup-guide .step{background:#172131}
.steps-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.step{padding:22px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}
.step-index{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:11px;color:var(--muted);font-weight:650;margin-bottom:16px}
.step-icon{display:grid;place-items:center;color:var(--accent)}
.step-index>span:last-child{font-size:15px;font-weight:760;color:var(--accent)}
.step h3{font-size:14px;margin-bottom:8px}
.step p{font-size:13px;color:var(--muted);line-height:1.7;margin:0}
.step-state{display:inline-block;font-size:11px;color:var(--amber);margin-top:12px}
.setup-help{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin-top:20px;padding:20px 2px 0;border-top:1px solid var(--line)}
.setup-help p{margin:0;color:var(--muted);font-size:13px;line-height:1.75}
.setup-help strong{color:var(--text)}.setup-help a{color:var(--accent);text-decoration:underline;text-underline-offset:3px}

/* ── Account Dashboard ── */
.account-welcome{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:20px 24px;border:1px solid var(--line);border-radius:10px;background:#172231}
.account-banner{display:flex;align-items:center;gap:15px;min-width:0}
.account-banner h2{font-size:20px;font-weight:700;margin:0 0 4px}
.account-banner p{font-size:13px;color:var(--muted);margin:0}
.avatar{display:grid;place-items:center;width:48px;height:48px;flex:none;background:rgba(39,159,255,.1);color:var(--accent);border:1px solid rgba(39,159,255,.24);border-radius:12px;font-size:20px;font-weight:700}

/* ── KPI Stat Cards ── */
.snapshot-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}
.snapshot-card{padding:18px 16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft);text-align:center;transition:border-color var(--transition)}
.snapshot-card:hover{border-color:var(--accent-border)}
.snapshot-card .metric{font-size:28px;font-weight:750;color:var(--accent);line-height:1.2;font-family:var(--font-mono);margin-bottom:4px}
.snapshot-card .metric-label{font-size:12px;color:var(--muted);font-weight:550}
.snapshot-summary-text{font-size:13px;color:var(--muted);margin:12px 0 6px!important}
.snapshot-next-action{margin:14px 0 8px;padding:12px 16px;border:1px solid rgba(39,159,255,.18);border-radius:7px;background:rgba(39,159,255,.04);font-size:13px;color:var(--text)}
.snapshot-next-action .next-label{font-weight:600;color:var(--muted)}
.card-footnote-inline{font-size:12px;color:var(--muted-soft);margin-top:10px!important;display:flex;align-items:center;gap:6px}

/* ── Overview Tiles ── */
.overview-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.overview-tile{display:flex;align-items:flex-start;min-height:136px;gap:14px;min-width:0;padding:22px 18px;border:1px solid var(--line);border-radius:10px;background:var(--surface);transition:all var(--transition)}
.overview-tile:hover{border-color:rgba(39,159,255,.5);background:#1a2b3c;transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.tile-icon{display:grid;place-items:center;width:40px;height:40px;flex:none;border-radius:9px;color:var(--accent);background:rgba(39,159,255,.09);border:1px solid rgba(39,159,255,.17)}
.tile-body{display:grid;gap:6px;min-width:0}
.tile-body strong{font-size:14px;line-height:1.4}
.tile-body small{font-size:13px;line-height:1.6;color:var(--muted)}
.tile-arrow{margin-left:auto;flex:none;color:var(--muted-soft)}

/* ── Account Columns & Checklist ── */
.account-columns{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:20px;align-items:start}
.account-side{display:grid;gap:18px;min-width:0}
.checklist-list{list-style:none;padding:0;margin:0}
.checklist-list>li{display:grid;grid-template-columns:32px minmax(0,1fr) auto;align-items:center;gap:14px;padding:16px 0;border-top:1px solid var(--line)}
.checklist-list>li:last-child{padding-bottom:0}
.checklist-list h3{font-size:14px;margin:0 0 3px}
.checklist-list p{font-size:13px}
.checklist-list .status-pill{align-self:center}
.checklist-list .text-link{font-size:12px;white-space:nowrap}
.checklist-number{display:grid;place-items:center;width:30px;height:30px;border:1px solid var(--line);border-radius:50%;font:11px var(--font-mono);color:var(--muted)}
.checklist-number.complete{color:var(--green);background:var(--positive-bg);border-color:transparent}
.account-security .providers{margin-top:18px;gap:0}
.identity-row{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:58px;padding:10px 0;border-top:1px solid var(--line)}
.identity-row form{width:100%}.identity-row .provider{min-height:42px;font-size:13px}
.identity-name{font-size:14px;font-weight:650}
.account-side .workspace-reminder{padding:18px;background:#141c24;border:1px solid var(--line);border-radius:10px}
.account-side .workspace-reminder svg{color:var(--accent);flex:none;margin-top:2px}
.account-side .workspace-reminder p{font-size:12px;line-height:1.7}

/* ── Sign In Page ── */
.auth-stage{display:grid;grid-template-columns:minmax(0,1.04fr) minmax(350px,.86fr);align-items:stretch;max-width:1160px;margin:0 auto;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:#131820}
.auth-intro{padding:clamp(28px,4vw,55px);background:radial-gradient(ellipse 85% 55% at 15% 2%,rgba(39,159,255,.12),transparent),#0d121a;display:flex;flex-direction:column}
.auth-intro h2{font-size:clamp(29px,2.8vw,43px);line-height:1.18;letter-spacing:-.05em;margin:17px 0 13px}
.auth-intro .auth-lead{max-width:490px;font-size:15px;line-height:1.65;color:var(--muted);margin-bottom:29px}
.auth-journey{display:grid;gap:18px;margin:6px 0 26px}
.auth-journey-step{display:flex;gap:14px;align-items:start}
.auth-journey-step>span{flex:none;display:grid;place-items:center;width:34px;height:34px;border:1px solid rgba(39,159,255,.25);border-radius:8px;color:var(--accent);font-size:12px;font-family:var(--font-mono)}
.auth-journey-step strong{display:block;font-size:14px;line-height:1.35}
.auth-journey-step p{font-size:13px;line-height:1.55;margin-top:4px;color:var(--muted)}
.auth-mobile-journey{display:none}
.auth-local-note{display:flex;align-items:center;gap:10px;margin-top:auto;padding-top:22px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
.auth-local-note svg{flex:none;color:var(--accent)}
.auth-stage .auth-card{display:flex;flex-direction:column;justify-content:center;padding:clamp(28px,3.6vw,52px);border:0;border-left:1px solid var(--line);border-radius:0;background:#171d26;box-shadow:none}
.auth-stage .panel-heading{margin-bottom:28px;align-items:start;gap:14px}
.auth-stage .panel-heading h2{font-size:clamp(22px,2.2vw,29px);margin:6px 0 8px;letter-spacing:-.025em}
.auth-stage .panel-heading p{font-size:13px;line-height:1.55;color:var(--muted)}
.auth-stage .provider{min-height:54px;gap:13px;border:1px solid var(--line-strong);border-radius:9px;background:#222b35;color:var(--text);font-size:14px;font-weight:650;transition:all var(--transition)}
.auth-stage .provider:hover{background:#2b3b47;border-color:rgba(39,159,255,.56)}
.auth-stage .provider-logo{width:30px;height:30px;border-radius:7px;background:#111820}
.auth-stage .auth-footnote{margin-top:26px;padding-top:18px}
.auth-stage .auth-footnote p{font-size:12px;line-height:1.6}
.auth-unavailable{padding:16px;border:1px solid var(--line-strong);border-radius:9px;color:var(--muted);font-size:13px}
.auth-download-link{display:inline-flex;align-items:center;gap:8px;color:var(--accent);font-size:13px;line-height:1.5;margin-top:18px;font-weight:650}
.auth-download-link:hover{text-decoration:underline}

/* ── Detail Card & Panels ── */
.detail-card{width:100%}
.auth-card{padding:30px}
.panel-heading{display:flex;align-items:center;gap:15px;margin-bottom:24px}
.panel-heading h2{font-size:21px;margin-bottom:4px}
.panel-heading p{font-size:13px}
.feature-icon,.panel-icon,.notice-icon,.empty-icon{display:grid;place-items:center;flex:none;width:42px;height:42px;border:1px solid var(--line);border-radius:9px;color:var(--accent);background:var(--surface-soft)}
.providers{display:grid;gap:10px}.providers form{margin:0}
.provider{width:100%;justify-content:flex-start;min-height:54px;padding:10px 16px;background:var(--surface)}
.provider-logo{display:grid;place-items:center;width:30px;height:30px;border-radius:6px;background:var(--surface-raised);font-weight:800;color:var(--text)}
.provider-arrow{margin-left:auto;color:var(--muted)}
.auth-footnote{display:flex;align-items:flex-start;gap:10px;border-top:1px solid var(--line);padding-top:18px;margin-top:22px;color:var(--muted)}
.auth-footnote svg{flex:none;margin-top:2px}
.auth-footnote p{font-size:12px}

/* ── Connections Page ── */
.connections-list{list-style:none;padding:0;margin:20px 0 0}
.connections-list>li{padding:20px 0;border-top:1px solid var(--line);min-width:0}
.connections-list>li:last-child{padding-bottom:0}
.connection-item{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}
.connection-item>div{min-width:0}
.connection-name{margin-top:10px;font-size:16px!important}
.connection-item>form{flex-shrink:0}
.connection-item h3{font-size:15px}
.connection-item form label{font-size:13px}
.connection-item form .button{margin-top:8px}
.permission-tags{display:flex;flex-direction:column;gap:6px;margin-top:14px}
.permission-tag{display:inline-flex;align-items:center;gap:8px;padding:2px 0;color:var(--text-secondary);font-size:13px;background:none;border:none}
.permission-tag::before{content:"✓";display:inline-grid;place-items:center;width:15px;height:15px;border-radius:50%;background:rgba(16,185,129,0.15);color:var(--green);font-size:10px;font-weight:700;flex:none}
.mcp-endpoint-box{display:flex;align-items:center;gap:12px;padding:12px 16px;background:var(--surface-soft);border:1px solid var(--line);border-radius:var(--radius-sm);margin:14px 0 10px}
.endpoint-url{flex:1;font-family:var(--font-mono);font-size:13px;color:var(--accent);word-break:break-all}
.endpoint-subtext{font-size:12px;color:var(--muted);margin-bottom:18px}
.mcp-client-guides{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:16px}
.client-guide-card{padding:16px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--surface-soft);display:flex;flex-direction:column;gap:8px}
.client-guide-card h3{font-size:14px;margin:0;color:var(--text)}
.client-guide-card p{font-size:12px;color:var(--muted);line-height:1.5;margin:0;flex:1}
.client-guide-card .text-link{font-size:12px;min-height:28px}

/* ── Usage Dashboard ── */
.usage-dashboard{display:flex;flex-direction:column;gap:22px}
.usage-banner{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:22px 26px;background:linear-gradient(135deg,rgba(39,159,255,0.08),rgba(101,150,223,0.04)),var(--surface);border-color:rgba(39,159,255,0.22)}
.usage-banner-content h2{font-size:22px;letter-spacing:-0.03em;margin:4px 0 6px;color:var(--text)}
.banner-kicker{font-size:10px;letter-spacing:0.12em;font-weight:750;color:var(--accent);text-transform:uppercase}
.plan-badge{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;background:rgba(39,159,255,0.12);border:1px solid rgba(39,159,255,0.28);border-radius:20px;color:var(--accent);font-size:12px;font-weight:650}
.usage-stats-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.stat-card{padding:22px;display:flex;flex-direction:column;gap:10px}
.stat-hero{display:flex;align-items:baseline;gap:6px}
.stat-value{font-size:32px;font-weight:750;letter-spacing:-0.03em;color:var(--text);font-family:var(--font-mono)}
.stat-total{font-size:16px;color:var(--muted);font-family:var(--font-mono)}
.stat-progress-bar{width:100%;height:6px;border-radius:3px;background:rgba(255,255,255,0.08);overflow:hidden;margin:4px 0}
.stat-progress-fill{height:100%;background:linear-gradient(90deg,var(--accent),#729fe8);border-radius:3px}
.stat-subtext{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.stat-caption{font-size:12px;color:var(--muted);margin:0}
.chart-card{padding:24px 28px}
.chart-header{margin-bottom:20px}
.chart-subtitle{font-size:13px;color:var(--muted);margin-top:2px}
.chart-container{display:flex;gap:16px;height:220px;padding:12px 0 6px}
.chart-y-axis{display:flex;flex-direction:column;justify-content:space-between;font-size:11px;font-family:var(--font-mono);color:var(--muted-soft);padding-bottom:24px;text-align:right;min-width:44px}
.chart-bars-wrap{flex:1;position:relative;display:flex;flex-direction:column}
.chart-gridlines{position:absolute;inset:0 0 24px 0;display:flex;flex-direction:column;justify-content:space-between;pointer-events:none}
.gridline{border-bottom:1px solid rgba(255,255,255,0.06);width:100%}
.chart-bars{position:relative;flex:1;display:flex;align-items:flex-end;justify-content:space-around;gap:12px;padding-bottom:24px;z-index:2}
.chart-bar-col{flex:1;max-width:54px;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}
.bar-track{width:100%;height:160px;display:flex;align-items:flex-end;justify-content:center}
.bar-fill{width:100%;border-radius:4px 4px 0 0;transition:height 0.3s ease,background 0.2s}
.bar-fill.active{background:linear-gradient(180deg,var(--accent),#0070e0);box-shadow:0 0 12px rgba(39,159,255,0.25)}
.bar-fill.active:hover{background:#a6c5fc}
.bar-fill.empty{background:rgba(255,255,255,0.05)}
.bar-label{margin-top:8px;font-size:12px;color:var(--muted);font-weight:550;text-align:center}
.usage-details-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.tool-breakdown-list{list-style:none;padding:0;margin:16px 0 0;display:flex;flex-direction:column;gap:14px}
.breakdown-row{display:flex;justify-content:space-between;align-items:center;font-size:12px;margin-bottom:4px}
.breakdown-count{color:var(--muted);font-size:11px}
.breakdown-bar{width:100%;height:4px;border-radius:2px;background:rgba(255,255,255,0.06);overflow:hidden}
.breakdown-fill{height:100%;background:var(--accent);border-radius:2px}
.activity-list{list-style:none;padding:0;margin:16px 0 0;display:flex;flex-direction:column;gap:10px}
.activity-item{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-radius:var(--radius-sm);background:var(--surface-soft);border:1px solid var(--line);font-size:12px}
.activity-meta{display:flex;align-items:center;gap:12px}
.activity-client{display:flex;align-items:center;gap:6px;font-weight:600;color:var(--text)}
.activity-time{color:var(--muted-soft);font-size:11px}
.activity-tool{display:flex;align-items:center;gap:10px}

/* ── Consent Scope List ── */
.scope-list{list-style:none;margin:18px 0;padding:0}
.scope-list li{padding:14px 0;border-top:1px solid var(--line)}
.scope-list strong{font-size:14px}
.scope-list li p{margin:4px 0;font-size:13px}
.scope-list code,code{font-family:var(--font-mono);font-size:.9em;overflow-wrap:anywhere}
.scope-list code{color:var(--muted)}
.security-note{display:flex;align-items:flex-start;gap:10px;margin-top:22px;padding:14px 16px;border:1px solid var(--line);border-radius:8px;color:var(--muted);background:var(--surface-soft);font-size:12px;line-height:1.75}
.security-note svg{flex:none;margin-top:2px;color:var(--accent)}
.empty-state{display:flex;align-items:flex-start;gap:14px;padding:24px 0}
.empty-state p{font-size:13px}
.output-notice{display:block;margin:0 0 18px;padding:12px 16px;border:1px solid var(--line);border-left:3px solid var(--accent);background:var(--positive-bg);color:var(--text);border-radius:6px;font-size:13px}

/* ── Forms ── */
label{display:block;font-weight:600;font-size:13px;color:var(--text);margin:16px 0 6px}
input:not([type=hidden]),select,textarea{display:block;width:100%;min-height:44px;margin:6px 0 12px;padding:10px 14px;border:1px solid var(--line-strong);border-radius:7px;background:var(--surface-soft);color:var(--text);font-size:13px;transition:border-color var(--transition),box-shadow var(--transition)}
input:not([type=hidden]):focus,select:focus,textarea:focus{border-color:var(--accent);outline:none;box-shadow:0 0 0 2px rgba(39,159,255,.25)}
.field-help{margin-top:10px!important;font-size:12px!important;color:var(--muted)!important}

/* ── MCP Guidance Cards ── */
.mcp-endpoint{margin:18px 0!important;padding:14px 18px;border:1px solid rgba(39,159,255,.25);background:rgba(39,159,255,.04);border-radius:8px;color:var(--text)!important}
.mcp-endpoint code{font-size:13px;color:var(--accent)}
.mcp-client-guides{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:22px 0}
.mcp-client-guides>div{padding:18px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft);transition:border-color var(--transition)}
.mcp-client-guides>div:hover{border-color:rgba(39,159,255,.25)}
.mcp-client-guides h3{font-size:15px;margin-bottom:6px}
.mcp-client-guides p{font-size:13px;line-height:1.65}
.mcp-client-guides .text-link{margin-right:16px;vertical-align:middle;font-size:12px}
.mcp-client-guides .text-link:last-child{margin-right:0}

/* ── Project Grants ── */
.project-grants{margin-top:18px;padding:16px;border:1px solid var(--line);border-radius:9px;background:var(--surface-soft)}
.project-grants>strong{font-size:13px}.project-grants>p{font-size:12px}
.project-grants ul{list-style:none;padding:0;margin:12px 0 0}
.project-grants li{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
.project-grants li>form{margin:0}
.project-grants li .button{min-height:40px;font-size:12px}
.grant-client{min-width:0;overflow-wrap:anywhere;font-size:12px;color:var(--text)}

/* ── Devices Page & Progress ── */
.setup-progress{background:linear-gradient(145deg,rgba(39,159,255,.07),var(--surface));border:1px solid rgba(39,159,255,.22);border-radius:12px;padding:22px;box-shadow:0 8px 24px rgba(0,0,0,.15)}
.setup-progress-heading{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:18px}
.setup-progress-heading strong{font-size:15px;color:var(--text)}
.setup-progress-heading span{color:var(--muted);font-size:12px}
.setup-progress ol{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;list-style:none;margin:0;padding:0}
.setup-progress li{display:flex;align-items:flex-start;gap:9px;padding:12px 10px;background:var(--surface-soft);border:1px solid var(--line);border-radius:8px;min-width:0;transition:border-color var(--transition)}
.setup-progress li.progress-complete{border-color:rgba(16,185,129,.32)}
.setup-progress li.progress-current{border-color:rgba(39,159,255,.3)}
.progress-number{color:var(--accent);font:700 12px var(--font-mono);padding-top:2px}
.progress-complete .progress-number{color:var(--green)}
.setup-progress li>div{min-width:0;display:grid;gap:3px}
.setup-progress li strong{color:var(--text);font-size:12px}
.setup-progress li small{color:var(--muted);font-size:11px;line-height:1.55}

/* ── Quickstart Card & Device Rows ── */
.page-devices .quickstart-card{border-color:rgba(39,159,255,.25);background:linear-gradient(125deg,var(--surface),rgba(39,159,255,.05))}
.card-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 22px;border-bottom:1px solid var(--line)}
.card-header h2{margin:0}
.list-count{color:var(--muted);font-size:12px}
.device-card{padding:0;overflow:hidden}.device-list{margin:0}
.device-list>li{border-top:0;border-bottom:1px solid var(--line);padding:18px 22px}
.device-list>li:last-child{padding-bottom:18px}
.device-row{display:grid;grid-template-columns:8px minmax(0,1fr) auto;gap:14px;align-items:center}
.device-dot{width:8px;height:8px;border-radius:50%;background:#73737f}
.device-dot.connected{background:var(--green);box-shadow:0 0 6px var(--green)}
.device-summary{min-width:0}
.device-summary h3{font:13px var(--font-mono);margin-bottom:3px}
.device-summary p{font-size:12px;line-height:1.55}
.device-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.device-actions form{margin:0}
.device-actions .button{min-height:40px;padding:8px 12px;font-size:12px}
.device-actions .status-pill{font-size:11px;padding:5px 8px}
.device-register{grid-column:2/-1;margin-top:4px}
.device-register summary{width:fit-content;min-height:40px;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--accent);list-style:none;cursor:pointer}
.device-register summary:before{content:'+';font-size:15px}
.device-register[open] summary:before{content:'−'}
.device-register form{margin:0 0 4px;padding:14px 16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft);max-width:440px}
.device-register label{margin-top:0;font-size:12px}
.card-footnote{display:flex;align-items:flex-start;gap:8px;padding:13px 22px;color:var(--muted);font-size:11px}
.card-footnote svg{flex:none;margin-top:1px}
.device-card>.empty-state{padding:24px 22px}

/* ── Projects Card ── */
.project-section-heading,.project-empty{margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}
.projects-card .project-empty{margin-top:18px;padding-top:18px}
.project-item form{margin-top:14px}
.project-item>strong{font-size:15px}
.project-item select{max-width:440px}
.project-empty p{font-size:13px}
/* Single clear next step instead of five full-size onboarding cards. */
.setup-next-step{display:flex;align-items:center;justify-content:space-between;gap:16px;
 border:1px solid var(--line);border-radius:12px;background:var(--surface-soft);padding:15px 20px}
.setup-next-step strong{font-size:13px;font-weight:700;white-space:nowrap}
.setup-next-step span{font-size:12px;color:var(--muted);line-height:1.5}
.project-access-details{margin-top:10px;border-top:1px solid var(--line);padding-top:8px}
.project-access-details>summary,.device-advanced>summary{width:fit-content;cursor:pointer;
 padding:8px 4px;color:var(--accent);font-size:13px;font-weight:700}
.project-access-details[open]>summary,.device-advanced[open]>summary{margin-bottom:10px}
.project-access-details>p,.device-advanced>p{font-size:12px;color:var(--muted);max-width:620px}
.project-access-details form,.device-advanced form{max-width:520px}
.device-advanced form{margin:6px 0 0}
.device-register p{max-width:510px;font-size:12px;color:var(--muted)}
@media(max-width:680px){.setup-next-step{align-items:flex-start;flex-direction:column;gap:5px}}

/* ── Client Shortcuts ── */
.client-shortcuts>p{font-size:13px}
.client-shortcuts ul{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:4px}
.client-shortcuts li{display:grid;grid-template-columns:36px minmax(0,1fr) auto;align-items:center;gap:12px;padding:12px 0}
.client-shortcuts h3{font-size:13px;font-weight:550;margin:0 0 2px}
.client-shortcuts li p{font-size:12px}
.client-shortcuts .text-link{font-size:12px}
.client-icon{display:grid;place-items:center;width:36px;height:36px;border:1px solid var(--line);border-radius:8px;color:var(--muted);background:var(--surface-raised)}

/* ── Advanced Identity ── */
.advanced-identity{margin:22px 0 0;padding:16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft)}
.advanced-identity p{margin-top:10px!important;font-size:12px!important}
.local-setup-command{padding:12px 0;border-top:1px solid var(--line)}
.local-setup-command strong{font-size:13px}
.local-setup-command code{display:block;overflow-wrap:anywhere;white-space:pre-wrap;user-select:text;line-height:1.7;background:#06090e;border:1px solid var(--line);padding:12px;border-radius:6px;font-size:12px;color:var(--accent)}
summary{cursor:pointer;min-height:36px;font-size:13px;color:var(--muted);font-weight:550}
#pairing-manual{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}
.pairing-code{display:inline-block;font:16px var(--font-mono);letter-spacing:.09em;color:var(--accent)}
.local-folder-browse{margin-top:14px;padding:14px 16px;border:1px solid var(--line);border-radius:8px;background:var(--surface-soft)}
.local-folder-browse strong{color:var(--text);font-size:13px}
.local-folder-browse p{margin-top:6px!important;font-size:12px!important}
.local-folder-browse code{color:var(--accent);white-space:normal;overflow-wrap:anywhere}

/* ── Status Detail ── */
.status-card{padding:8px 0}.status-card h2{margin-top:16px}
.state-detail{display:grid;gap:0;margin-top:16px}
.state-detail>div{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:12px 0;border-top:1px solid var(--line);font-size:13px}
.state-detail small{color:var(--muted);font-size:12px}

/* ── Dashboard Grid ── */
.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
.dashboard-card{display:flex;flex-direction:column;align-items:flex-start}
.dashboard-card-top{margin-bottom:14px}
.dashboard-card h2{font-size:18px}
.dashboard-card>.button{margin-top:18px}
.dashboard-card>p{flex:1}
.workspace-reminder{display:flex;align-items:flex-start;gap:10px;padding:0 4px;color:var(--muted)}
.workspace-reminder svg{flex:none;margin-top:2px}
.workspace-reminder p{margin:0;font-size:12px;line-height:1.8}

/* ── Footer ── */
.site-footer{border-top:1px solid var(--line);background:var(--surface)}
.footer-inner{max-width:1400px;margin:auto;padding:22px 36px;display:flex;justify-content:space-between;gap:20px;color:var(--muted);font-size:12px}
.footer-separator{margin:0 7px;color:var(--line-strong)}

/* ── Responsive Queries ── */
@media(max-width:1250px){
  .overview-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
  .mcp-client-guides{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:1080px){
  .workspace-sidebar{width:214px}
  .workspace-app>.site-main{margin-left:214px}
  .workspace-layout{padding:28px 24px 54px}
  .workspace-topbar{padding:0 24px}
  .account-columns{grid-template-columns:1fr}
  .account-side{grid-template-columns:1fr 1fr}
  .landing-panel{grid-template-columns:1fr}
  .topology-panel{border-left:0;border-top:1px solid var(--line)}
  .steps-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:1060px){
  .header-inner,.content-wrap{padding-left:26px;padding-right:26px}
  .landing-intro{padding:30px}
  .release-label{display:none}
}
@media(max-width:980px){
  .setup-progress ol{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media(max-width:960px){
  .usage-stats-grid,.usage-details-grid,.mcp-client-guides{grid-template-columns:1fr}
}
@media(max-width:860px){
  .auth-stage{grid-template-columns:1fr}
  .auth-intro{padding:28px}
  .auth-intro h2{font-size:29px}
  .auth-journey{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
  .auth-journey-step{gap:8px}
  .auth-journey-step>span{width:30px;height:30px}
  .auth-stage .auth-card{border-left:0;border-top:1px solid var(--line);padding:30px}
  .entry-choices{grid-template-columns:1fr}
}
@media(max-width:750px){
  .header-inner{min-height:64px;padding:10px 20px}
  .header-right,.public-nav{gap:16px}
  .content-wrap,.workspace-layout{padding:26px 20px 46px}
  .workspace-app>.site-main{margin-left:0}
  .workspace-sidebar{position:static;width:100%;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:12px 16px;overflow:visible}
  .workspace-sidebar>.brand{margin-bottom:10px;padding:0 5px}
  .sidebar-section-label{display:none}
  .workspace-app>.site-main,.workspace-topbar{margin-left:0}
  .workspace-sidebar .sidebar-links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-bottom:0}
  .sidebar-links a{display:flex;justify-content:center;gap:5px;padding:10px 5px;font-size:11px;letter-spacing:-.01em;white-space:nowrap}
  .sidebar-links a svg{width:15px;height:15px}
  .sidebar-note,.sidebar-footer{display:none}
  .workspace-topbar{padding:10px 20px;min-height:46px}
  .workspace-topbar-actions span{display:none}
  .overview-tiles{grid-template-columns:1fr}
  .overview-tile{min-height:85px}
  .account-side{grid-template-columns:1fr}
  .checklist-list>li{grid-template-columns:30px minmax(0,1fr)}
  .checklist-list>li>.text-link,.checklist-list>li>.status-pill{grid-column:2;justify-self:start}
  .landing-intro{padding:26px}
  .landing-intro h2{font-size:32px}
  .section-head{align-items:flex-start;flex-direction:column;gap:8px}
  .section-head p{text-align:left;max-width:none}
  .account-welcome{align-items:flex-start}
  .card{padding:20px}
  .footer-inner{padding:18px 20px}
  .mcp-client-guides{grid-template-columns:1fr}
  .home-setup-guide>.steps-grid{grid-template-columns:1fr;padding:0 12px 12px}
  .setup-help{grid-template-columns:1fr;gap:12px}
  .page-sign-in .content-wrap,.page-consent .content-wrap,.page-notice .content-wrap{padding-top:30px}
  .snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .project-grants li{grid-template-columns:minmax(0,1fr) auto}
  .project-grants li>form{grid-column:1/-1;justify-self:start}
}
@media(max-width:560px){
  h1{font-size:26px}
  .brand{font-size:14px;gap:8px}
  .brand-mark{width:34px;height:34px;min-width:34px;max-width:34px}
  .brand-mark .brand-logo{width:22px;height:22px;min-width:22px;max-width:22px;max-height:22px}
  .public-nav a,.header-account{font-size:12px}
  .header-account{padding:0 10px}
  .public-nav{gap:14px}
  .steps-grid{grid-template-columns:1fr}
  .step{padding:18px}
  .step-index{margin-bottom:12px}
  .landing-intro{padding:22px}
  .landing-intro h2{font-size:28px}
  .topology-panel{padding:20px 18px}
  .topology-node{gap:9px;padding:12px}
  .topology-icon{width:32px;height:32px}
  .topology-tag{font-size:9px}
  .topology-node strong{font-size:12px}
  .topology-node small{font-size:11px}
  .topology-foot{align-items:flex-start;font-size:11px}
  .topology-foot svg{flex:none}
  .card,.auth-card{padding:18px}
  .connection-item{display:block}
  .connection-item>form{margin-top:14px}
  .account-welcome{padding:15px;align-items:flex-start}
  .account-welcome>.status-pill{display:none}
  .account-banner{align-items:start}
  .avatar{width:42px;height:42px;font-size:18px}
  .account-banner h2{font-size:18px}
  .account-banner p{font-size:12px}
  .checklist-list>li{padding:14px 0}
  .form-actions .button{flex:1}
  .footer-inner{display:grid;gap:6px}
  .overview-tile{min-height:90px}
  .device-list>li{padding:16px}
  .device-row{grid-template-columns:8px minmax(0,1fr);align-items:start}
  .device-dot{margin-top:6px}
  .device-actions{grid-column:2;justify-content:flex-start;gap:6px}
  .device-register{grid-column:2}
  .card-header{padding:16px}
  .client-shortcuts li{grid-template-columns:30px minmax(0,1fr);gap:10px}
  .client-icon{width:30px;height:30px}
  .client-shortcuts li>.text-link{grid-column:2;justify-self:start;min-height:32px}
  .setup-progress{padding:16px}
  .setup-progress ol{grid-template-columns:1fr}
  .setup-progress li{align-items:center;padding:10px 12px}
  .setup-progress li>div{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .workspace-app .page-heading{flex-direction:column;gap:14px}
  .workspace-app h1{font-size:24px}
  .workspace-topbar{display:none}
  .sidebar-links a{font-size:10.5px;gap:4px}
  .page-sign-in .page-heading{margin-bottom:13px}
  .auth-stage{border-radius:11px}
  .auth-journey{display:none}
  .auth-mobile-journey{display:block;margin:0 0 11px;font-size:12px;line-height:1.45;color:var(--muted)}
  .auth-intro{padding:19px 20px}
  .auth-intro h2{font-size:25px;margin:8px 0 6px}
  .auth-intro .auth-lead{margin-bottom:10px;font-size:13px;line-height:1.45}
  .auth-local-note{padding-top:10px;font-size:11px}
  .auth-stage .auth-card{padding:18px 20px}
  .auth-stage .panel-heading{margin-bottom:14px}
  .auth-stage .panel-heading h2{margin:4px 0 5px}
  .auth-stage .auth-footnote{margin-top:16px;padding-top:12px}
  .entry-choice{padding:18px;gap:12px}
  .entry-choice-icon{width:40px;height:40px}
  .entry-choice strong{font-size:15px}
  .landing-intro .action-row{display:grid;grid-template-columns:1fr}
  .landing-intro .action-row .button{width:100%}
}
@media(max-width:380px){
  .page-sign-in .content-wrap{padding-top:12px}
  .page-sign-in .page-heading{margin-bottom:5px}
  .auth-intro{padding:11px 16px}
  .auth-intro h2{margin:6px 0 5px}
  .auth-intro .auth-lead{margin-bottom:6px}
  .auth-mobile-journey{margin-bottom:6px}
  .auth-stage .auth-card{padding:12px 18px}
  .auth-stage .panel-heading{margin-bottom:8px}
}
@media(prefers-reduced-motion:reduce){
  *,*:before,*:after{scroll-behavior:auto!important;transition:none!important;animation:none!important}
  .auth-stage .provider{transition:none}
  .entry-choice{transition:none}.entry-choice:hover{transform:none}
  .overview-tile:hover{transform:none}
}
/* LOCAL PREMIUM UX PROTOTYPE */
:root{
 --bg:#090a0d;--surface:#191b20;--surface-raised:#24272e;--surface-soft:#12151a;
 --surface-glass:rgba(10,17,27,.9);--line:rgba(159,196,218,.14);
 --line-strong:rgba(166,209,231,.26);--text:#f2f7fd;--text-secondary:#d7e6f3;
 --muted:#a3b8cc;--muted-soft:#7d94aa;--primary:#0876cb;
 --radius:12px;--radius-sm:8px;--radius-lg:16px;
 --shadow-sm:0 12px 30px rgba(0,0,0,.13)
}
body{line-height:1.5;letter-spacing:-.007em}
.site-main{background:radial-gradient(ellipse at 50% -25%,rgba(39,159,255,.09),transparent 65%),var(--bg)}
.site-header{background:rgba(9,16,26,.92);border-color:rgba(142,184,210,.13)}
.header-inner{min-height:78px}
.brand{font-weight:780;letter-spacing:-.035em}
.brand-mark{border-radius:12px;background:rgba(39,159,255,.08)}
.public-nav a:last-child{border:1px solid var(--line-strong);border-radius:10px;padding:0 15px}
.content-wrap{max-width:1400px}
.page-home .page-heading{margin-bottom:18px}
.page-home .page-heading h1{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#95abbc}
.page-home .page-heading .eyebrow,.page-home .page-heading .summary{display:none}
.landing-panel{
 min-height:390px;grid-template-columns:minmax(0,1.04fr) minmax(355px,.96fr);
 border-radius:15px;border:1px solid var(--accent-border);
 background:linear-gradient(120deg,rgba(39,159,255,.045),transparent 65%),#141d29;
 box-shadow:0 10px 28px rgba(0,0,0,.13)
}
.landing-intro{background:none;padding:clamp(30px,4.6vw,62px)}
.landing-product-label{margin-top:30px;color:#9bbbd1;letter-spacing:.16em;font-size:10px}
.landing-intro h2{font-size:clamp(30px,3.3vw,45px);font-weight:770;line-height:1.08;letter-spacing:-.064em;margin:11px 0 19px}
.landing-accent{color:#9dc3fc}
.landing-intro>p:not(.hero-note){max-width:495px;font-size:15px;line-height:1.65;color:#bed0df}
.landing-intro .action-row{margin-top:26px;gap:12px}
.landing-intro .action-row .button{min-height:52px;font-size:14px;border-radius:11px;padding:12px 22px}
.button.primary{background:var(--primary);border-color:var(--primary);color:var(--on-accent);box-shadow:0 7px 25px rgba(39,159,255,.16);font-weight:800}
.button.primary:hover{background:#a6c5fc;color:#0b1828}
.button.secondary{background:rgba(255,255,255,.025);border-color:rgba(172,210,232,.32)}
.landing-platforms{margin-top:22px;gap:8px}
.landing-platforms>span{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#8097b0}
.landing-platforms>a{font-size:11px;color:#c9e4f2;min-height:35px;border-radius:9px;background:#13273a}
.hero-note{margin-top:21px!important;font-size:11px!important}
.topology-panel{
 padding:34px 30px;border-left:1px solid var(--line);
 background:#142033
}
.topology-eyebrow{margin-bottom:27px;color:#abc8dd}
.topology-node{padding:17px;border-radius:14px;background:rgba(23,41,59,.85);border-color:rgba(148,198,224,.19)}
.topology-node strong{font-size:14px}
.topology-node-cloud{background:rgba(15,79,97,.42);border-color:rgba(39,159,255,.37)}
.topology-icon{width:43px;height:43px;border-radius:12px;background:#203549}
.topology-link{height:42px}
.topology-link small{background:#142333}
.entry-choices{gap:16px}
.entry-choice{
 position:relative;min-height:126px;border-radius:12px;padding:18px;gap:14px;
 background:#132132;border-color:rgba(150,191,223,.2);box-shadow:0 8px 28px rgba(0,0,0,.1)
}
.entry-choice-primary{background:radial-gradient(circle at 0 0,rgba(39,159,255,.18),transparent 62%),#122536;border-color:rgba(39,159,255,.35)}
.entry-choice-cloud{background:radial-gradient(circle at 98% 100%,rgba(107,109,216,.12),transparent 65%),#151d30}
.entry-choice.unavailable,.entry-choice.unavailable:hover{opacity:.78;cursor:default;transform:none;box-shadow:none;border-color:var(--line-strong)}
.entry-choice:hover{transform:translateY(-3px);background:#192d42;border-color:var(--accent);box-shadow:0 17px 40px rgba(0,0,0,.25)}
.entry-choice-icon{width:52px;height:52px;border-radius:15px;background:#1b3a4c;border-color:rgba(39,159,255,.25);color:#9dc3fc}
.entry-choice-copy{display:grid;gap:7px;min-width:0}
.entry-choice-copy small{letter-spacing:.12em;font-size:10px;font-weight:800;color:#8faec4}
.entry-choice-copy strong{font-size:20px;line-height:1.25;letter-spacing:-.032em}
.entry-choice-copy>span{font-size:12px;line-height:1.45;color:#a4bacc}
.entry-choice-copy b{display:flex;align-items:center;gap:7px;margin-top:7px;color:#9dc3fc;font-size:12px}
.entry-choice-arrow{color:#8aaac0}
.next-section{margin-top:12px}
.next-section h2{font-size:22px}
.next-section .section-head p{color:#89a5b7;font-size:12px}
.home-setup-guide,.setup-faq{border-radius:14px;background:#152335;border:1px solid var(--line);margin-top:10px}
.home-setup-guide>summary,.setup-faq>summary{
 display:flex;align-items:center;justify-content:space-between;min-height:58px;
 padding:13px 21px;cursor:pointer;font-size:14px;font-weight:750;list-style:none
}
.home-setup-guide>summary::-webkit-details-marker,.setup-faq>summary::-webkit-details-marker{display:none}
.home-setup-guide .steps-grid{padding:13px 18px 21px}
.setup-faq .setup-help{margin:0;padding:18px;border-top:1px solid var(--line)}
.workspace-sidebar{width:245px;background:linear-gradient(160deg,#101b2a,#0e1724);padding-top:25px}
.workspace-app>.site-main{margin-left:245px}
.sidebar-links a{min-height:48px;border-radius:11px}
.sidebar-links a[aria-current=page]{background:rgba(39,159,255,.11);border-color:rgba(39,159,255,.2);color:#9dc3fc}
.sidebar-note{padding:15px;border-radius:13px;background:#182a3f}
.sidebar-note-badge{display:flex;align-items:center;gap:7px;color:#a6c5fc;font-size:10px;font-weight:800;letter-spacing:.06em;margin-bottom:8px}
.sidebar-note strong{font-size:12px}
.sidebar-note .text-link{min-height:30px;margin-top:6px}
.workspace-topbar{background:#13161b}
.workspace-layout{padding-top:27px}
.account-welcome{border:0;background:none;padding:2px 0 4px}
.account-banner h2{font-size:22px}
.avatar{border-radius:15px;width:54px;height:54px;background:#233b59}
.premium-focus-panel{
 display:flex;justify-content:space-between;align-items:center;gap:25px;padding:29px;
 border-radius:19px;border:1px solid rgba(39,159,255,.31);
 background:radial-gradient(ellipse at 94% 0,rgba(39,159,255,.17),transparent 60%),linear-gradient(120deg,#16354a,#132438);
 box-shadow:0 20px 55px rgba(0,0,0,.15)
}
.focus-eyebrow{display:inline-flex;align-items:center;gap:8px;color:#a6c5fc;font-size:10px;font-weight:800;letter-spacing:.14em}
.premium-focus-panel h2{font-size:clamp(22px,2.5vw,31px);letter-spacing:-.04em;margin:9px 0}
.premium-focus-panel p{color:#b6d0e0;font-size:13px;line-height:1.55;max-width:480px;margin:0}
.premium-focus-panel .button{min-height:49px;border-radius:11px;flex-shrink:0}
.workspace-snapshot-card{background:transparent;border:0;box-shadow:none;padding:1px 0}
.workspace-snapshot-card:hover{border-color:transparent}
.snapshot-grid{gap:13px}
.snapshot-card{
 display:grid;position:relative;justify-items:start;gap:6px;text-align:left;
 min-height:133px;border-radius:15px;padding:17px;border:1px solid var(--line);
 background:#192839;transition:transform var(--transition),border-color var(--transition)
}
.snapshot-card:hover{background:#233750;transform:translateY(-2px);border-color:var(--accent)}
.snapshot-icon{color:#98bcf4}
.snapshot-card .metric{font:750 33px var(--font-sans);color:#f0f7fc;letter-spacing:-.05em;margin:0}
.snapshot-card .metric-label{font-size:12px;color:#a9c0d4}
.snapshot-link-arrow{position:absolute;right:16px;top:18px;color:#789db3}
.overview-tile{border-radius:16px;background:#162537;border-color:var(--line)}
.overview-tile:hover{background:#263c55}
.tile-icon{border-radius:12px;width:44px;height:44px;color:#a6c5fc}
.tile-body strong{font-size:15px}
.tile-body small{font-size:12px}
.account-columns{grid-template-columns:minmax(0,1.25fr) minmax(280px,.8fr)}
.account-columns .card{border-radius:16px}
.checklist-disclosure>summary{display:inline-flex;gap:8px;align-items:center;cursor:pointer;min-height:40px;color:#a6c5fc;font-size:13px;font-weight:750}
.checklist-disclosure .checklist-list{margin-top:13px}
.auth-stage{max-width:1200px;border-radius:16px;background:#172437;box-shadow:0 12px 32px rgba(0,0,0,.12)}
.auth-intro{background:radial-gradient(circle at 5% 0,rgba(27,179,212,.13),transparent 65%),#0e1c2c}
.auth-intro h2{font-size:clamp(32px,3vw,47px)}
.auth-stage .auth-card{background:#162536}
.auth-stage .provider{border-radius:12px;background:#213248}
@media(max-width:1080px){
 .landing-panel{grid-template-columns:1fr}
 .topology-panel{border-left:0;border-top:1px solid var(--line)}
 .workspace-sidebar{width:215px}
 .workspace-app>.site-main{margin-left:215px}
 .account-columns{grid-template-columns:1fr}
}
@media(max-width:750px){
 .workspace-sidebar{width:100%}
 .workspace-app>.site-main{margin-left:0}
 .entry-choices{grid-template-columns:1fr}
 .premium-focus-panel{flex-direction:column;align-items:flex-start;padding:23px}
 .premium-focus-panel .button{width:100%}
 .snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:560px){
 .header-inner{min-height:62px}
 .landing-panel{border-radius:17px}
 .landing-intro{padding:23px}
 .landing-product-label{margin-top:23px}
 .landing-intro h2{font-size:clamp(32px,8vw,41px)}
 .landing-intro .action-row{display:flex;flex-direction:column;align-items:stretch}
 .landing-intro .action-row .button{width:100%}
 .topology-panel{padding:23px 18px}
 .entry-choice{padding:18px;min-height:120px;gap:13px}
 .entry-choice-icon{width:43px;height:43px}
 .entry-choice-copy strong{font-size:17px}
 .entry-choice-arrow{display:none}
 .premium-focus-panel h2{font-size:24px}
 .snapshot-card{min-height:121px;padding:15px}
 .snapshot-card .metric{font-size:28px}
}


/* Local UX review: remove redundant mobile navigation and keep actions above diagrams. */
.page-account .page-heading h1{
 position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap
}
.page-account .page-heading{margin:0}
.page-account .page-heading .summary{display:none}
.workspace-snapshot-card>.card-kicker{display:none}
.workspace-snapshot-card>h2{font-size:18px!important;letter-spacing:-.026em;margin-top:1px}
@media(max-width:560px){
 .header-inner{padding-inline:14px;gap:8px}
 .brand{font-size:12px}
 .brand-title small{display:none}
 .brand-mark{width:33px;height:33px;min-width:33px;max-width:33px}
 .brand-mark .brand-logo{width:21px;height:21px;min-width:21px;max-width:21px;max-height:21px}
 .header-right,.public-nav{gap:8px}
 .public-nav a:first-child{display:none}
 .public-nav a{font-size:11px;white-space:nowrap;min-height:37px}
 .public-nav a:last-child{padding:0 10px}
 .topology-panel{display:none}
 .page-account .page-heading{display:none}
 .account-welcome{padding-top:5px}
 .account-banner p{font-size:11px}
}



/* Measured padding and alignment across the workspace, especially device availability. */
:root{--content-gutter:clamp(20px,3vw,50px);--card-padding:clamp(22px,2.4vw,32px)}
.workspace-layout{padding:34px var(--content-gutter) 68px}
.page-heading{margin-bottom:24px}
.page-heading .summary{max-width:68ch;line-height:1.65}
.page-stack{gap:20px}
.card{padding:var(--card-padding)}
.page-devices .status-card{padding:var(--card-padding);border-radius:19px}
.page-devices .status-card .status-message{min-width:0}
.page-devices .status-card h2{font-size:clamp(19px,2vw,24px);line-height:1.3;margin:15px 0 8px}
.page-devices .status-card p{max-width:72ch;font-size:13px;line-height:1.7}
.page-devices .status-card .state-detail{margin-top:22px;border-radius:13px;overflow:hidden;border:1px solid var(--line)}
.page-devices .status-card .state-detail>div{padding:13px 18px;border-top:1px solid var(--line);font-size:13px}
.page-devices .status-card .state-detail>div:first-child{border-top:0}
.page-devices .status-card .state-detail small{text-align:right;font-weight:650;white-space:normal}
.page-devices .client-shortcuts{padding:var(--card-padding);border-radius:19px}
.client-shortcuts>p{margin-top:5px!important;max-width:68ch}
.client-shortcuts ul{margin-top:19px;gap:12px;padding:0;list-style:none}
.client-shortcuts li{display:block;padding:0}
.client-shortcut-link{min-height:76px;display:grid;grid-template-columns:46px minmax(0,1fr) auto;align-items:center;gap:17px;
 padding:15px 18px;border:1px solid var(--line);border-radius:13px;background:rgba(17,35,52,.65)}
.client-shortcut-link:hover{background:rgba(24,67,87,.5);border-color:rgba(60,207,222,.6)}
.client-shortcut-link:focus-visible{outline-offset:3px}
.client-shortcut-link>.client-icon{width:44px;height:44px;border-radius:12px;flex:none}
.client-shortcut-link>span:nth-child(2){display:grid;gap:4px;min-width:0}
.client-shortcut-link strong{font-size:14px;line-height:1.3;color:var(--text)}
.client-shortcut-link small{font-size:12px;line-height:1.5;color:var(--muted)}
.client-shortcut-link b{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;font-size:12px;color:#79e4ed}
.page-devices .card,.page-connections .card{min-width:0}
.http-setup-callout{scroll-margin-top:105px;background:linear-gradient(120deg,#122b3c,#122133);
 border:1px solid rgba(64,208,221,.34);padding:var(--card-padding);border-radius:18px}
.http-setup-heading{display:flex;align-items:center;gap:15px}
.http-setup-icon{display:grid;place-items:center;width:52px;height:52px;flex:none;border-radius:15px;background:#1e4053;color:#7ae5ee}
.http-setup-heading h2{font-size:23px;margin:4px 0 3px}
.http-setup-heading p{font-size:13px}
.http-command{display:block;overflow-x:auto;margin-top:20px;white-space:pre-wrap;overflow-wrap:anywhere;
 padding:18px 20px;border-radius:11px;border:1px solid rgba(137,186,204,.23);
 background:#091521;color:#acf3f7;font-size:13px;line-height:1.75;user-select:text}
.http-setup-footer{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;margin-top:14px;color:#adc8d8;font-size:12px}
.http-setup-footer code{color:#dcf5f8}
.workspace-snapshot-card{padding:2px 0}
.snapshot-card:focus-visible{outline-offset:3px}
.setup-faq{background:#152335;border:1px solid var(--line);border-radius:13px}
.setup-faq summary{min-height:58px;padding:15px 21px;font-weight:750}
.setup-faq>.setup-help{padding:19px 21px}
@media(max-width:750px){
 .workspace-layout{padding:24px 20px 48px}
 .page-devices .status-card,.page-devices .client-shortcuts{padding:23px}
 .topology-panel{display:none}
}
@media(max-width:560px){
 :root{--card-padding:20px;--content-gutter:17px}
 .workspace-layout{padding:22px var(--content-gutter) 46px}
 .page-devices .status-card,.page-devices .client-shortcuts{padding:20px}
 .page-devices .status-card .state-detail>div{align-items:flex-start;gap:8px;flex-wrap:wrap;padding:13px 14px}
 .client-shortcut-link{grid-template-columns:40px minmax(0,1fr);gap:10px;padding:15px}
 .client-shortcut-link>.client-icon{width:40px;height:40px}
 .client-shortcut-link>b{grid-column:2;justify-self:start}
 .http-setup-heading{align-items:flex-start}
 .http-setup-heading h2{font-size:20px}
 .http-command{padding:15px;font-size:12px}
 .entry-choices{grid-template-columns:1fr}
}



/* One calm, accessible graphite/slate design across Cloud workspaces. */
.workspace-app .workspace-sidebar{width:232px;background:#0e1015}
.workspace-app>.site-main{margin-left:232px;background:var(--bg)}
.workspace-app .workspace-layout{padding:28px clamp(18px,2.8vw,42px) 56px;max-width:1560px}
.workspace-app .workspace-topbar{min-height:50px;background:#13161b}
.workspace-app .workspace-sidebar .sidebar-links a{min-height:40px;padding:8px 11px;border-radius:9px}
.workspace-app .workspace-sidebar .sidebar-links a[aria-current=page]{background:var(--accent-soft);border-color:var(--accent-border);color:var(--accent)}
.workspace-app .page-stack{gap:16px}
.workspace-app .card{border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.10)}
.workspace-app .card:hover{border-color:var(--line-strong)}
.workspace-app .account-welcome{padding:8px 0 4px;border:0;background:transparent}
.workspace-app .premium-focus-panel{min-height:unset;padding:20px 22px;gap:16px;border-radius:12px;border:1px solid var(--accent-border);background:linear-gradient(115deg,rgba(39,159,255,.075),transparent 67%),var(--surface);box-shadow:none}
.workspace-app .premium-focus-panel h2{font-size:clamp(21px,2.1vw,27px);margin:7px 0}
.workspace-app .premium-focus-panel p{color:var(--muted);line-height:1.5}
.workspace-app .premium-focus-panel .button{min-height:43px;box-shadow:none}
.workspace-app .workspace-snapshot-card{padding:12px 18px;border:1px solid var(--line);background:var(--surface);box-shadow:none}
.workspace-app .snapshot-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin:9px 0}
.workspace-app .snapshot-card{display:grid;position:relative;align-content:center;justify-items:start;gap:4px;min-height:90px;text-align:left;background:transparent;border:0;border-right:1px solid var(--line);border-radius:0;padding:6px 15px;transform:none;box-shadow:none}
.workspace-app .snapshot-card:first-child{padding-left:2px}
.workspace-app .snapshot-card:last-child{border-right:0}
.workspace-app .snapshot-card:hover{background:transparent;border-color:var(--line);transform:none}
.workspace-app .snapshot-card .metric{font:750 26px var(--font-sans);color:var(--text);margin:0}
.workspace-app .snapshot-card .metric-label{font-size:12px;color:var(--muted)}
.workspace-app .snapshot-card .snapshot-icon{color:var(--accent)}
.workspace-app .snapshot-card .snapshot-link-arrow{top:13px;right:12px}
.overview-tiles{display:block;background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.overview-tile{display:flex;align-items:center;min-height:0;gap:12px;padding:13px 18px;border:0;border-bottom:1px solid var(--line);border-radius:0;background:transparent;transform:none;box-shadow:none}
.overview-tile:last-child{border-bottom:0}
.overview-tile:hover{background:var(--surface-raised);border-color:var(--line);transform:none;box-shadow:none}
.overview-tile .tile-icon{width:34px;height:34px;border-radius:9px;color:var(--accent)}
.overview-tile .tile-body{gap:3px}
.overview-tile .tile-body strong{font-size:13px}
.overview-tile .tile-body small{font-size:12px;line-height:1.4}
.workspace-app .button.primary{box-shadow:none;color:var(--on-accent)}
.workspace-app .button.primary:hover{box-shadow:none}
.entry-choice:hover{transform:none;box-shadow:none;border-color:var(--accent-border)}
@media(max-width:1080px) and (min-width:751px){
  .workspace-app .workspace-sidebar{width:214px}
  .workspace-app>.site-main{margin-left:214px}
}
@media(max-width:750px){
  .workspace-app .workspace-sidebar{width:100%}
  .workspace-app>.site-main{margin-left:0}
  .workspace-app .workspace-layout{padding:18px 16px 40px}
  .workspace-app .premium-focus-panel{flex-direction:column;align-items:flex-start;padding:18px}
  .workspace-app .premium-focus-panel .button{width:100%}
  .workspace-app .snapshot-grid{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:8px}
  .workspace-app .snapshot-card:nth-child(2){border-right:0}
  .workspace-app .snapshot-card:nth-child(3),.workspace-app .snapshot-card:nth-child(4){border-top:1px solid var(--line);padding-top:12px}
}
@media(max-width:400px){
  .workspace-app .snapshot-card{padding:8px}
  .overview-tile{padding:12px}
}
@media(prefers-reduced-motion:reduce){
  .overview-tile,.workspace-app .snapshot-card,.workspace-app .premium-focus-panel{transition:none}
}

/* Mobile workspace stays task-first: all six routes visible, profile and help in Settings. */
@media(max-width:750px){
  .workspace-app .workspace-sidebar{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px 12px;padding:9px 12px 8px;overflow:visible}
  .workspace-app .workspace-sidebar>.brand{grid-column:1;grid-row:1;min-height:36px;padding:0;margin:0;max-width:100%}
  .workspace-app .workspace-sidebar .sidebar-section-label{display:none}
  .workspace-app .workspace-sidebar .sidebar-profile{grid-column:2;grid-row:1;display:grid;place-items:center;width:38px;height:38px;margin:0;padding:0;border-radius:12px;background:var(--surface-soft)}
  .workspace-app .workspace-sidebar .profile-identity{display:none}
  .workspace-app .workspace-sidebar .sidebar-footer-links{display:none}
  .workspace-app .workspace-sidebar .sidebar-links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-column:1/-1;grid-row:2;gap:4px;margin:0;min-width:0}
  .workspace-app .workspace-sidebar .sidebar-links a{min-height:44px;min-width:0;width:100%;padding:7px 3px;justify-content:center;gap:3px;font-size:clamp(11px,2.9vw,12px);letter-spacing:-.02em;white-space:nowrap}
  .workspace-app .workspace-sidebar .sidebar-links a svg{width:14px;height:14px}
}
.settings-support-links{display:flex;flex-wrap:wrap;gap:10px 18px;padding:12px 2px;color:var(--muted);font-size:12px}
.settings-support-links a{color:var(--text-secondary);text-decoration:underline;text-decoration-color:var(--line-strong);text-underline-offset:3px}
.settings-support-links a:hover,.settings-support-links a:focus-visible{color:var(--accent)}

`;
