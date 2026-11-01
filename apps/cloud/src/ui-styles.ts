// First-party static visual system: no external fonts, scripts or image requests.
export const uiCss = String.raw`
:root{color-scheme:dark;--bg:#0a0e15;--surface:#121a25;--surface-raised:#192330;--surface-soft:#0e1520;--line:#283647;--line-strong:#425671;--text:#f0f5fc;--muted:#acbdcf;--muted-soft:#91a5bb;--blue:#afcfff;--blue-strong:#83b7ff;--green:#86dfbd;--amber:#f2cc91;--danger:#ffb7b2;--radius:17px;--shadow:0 18px 65px rgba(0,0,0,.14)}
*{box-sizing:border-box}html{min-height:100%;background:var(--bg);scroll-behavior:smooth}
body{min-height:100vh;margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;letter-spacing:-.012em;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}button,input{font:inherit}button{cursor:pointer}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--blue-strong);outline-offset:4px}
.skip-link{position:absolute;left:18px;top:-60px;background:#f3f7ff;color:#151b25;padding:10px 16px;z-index:30;border-radius:9px}.skip-link:focus{top:12px}
.app-shell{min-height:100vh;display:flex;flex-direction:column}
.site-header{border-bottom:1px solid #253244;background:#0f1620}
.header-inner{max-width:1320px;margin:auto;padding:0 38px;min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:24px}
.brand{display:inline-flex;align-items:center;gap:12px;font-size:16px;font-weight:660;letter-spacing:-.035em;white-space:nowrap}
.brand-mark{display:grid;place-items:center;width:42px;height:42px;color:#b5d2ff;background:#1a2d43;border:1px solid #385779;border-radius:12px;box-shadow:inset 0 1px rgba(255,255,255,.08)}
.brand-title{display:flex;align-items:baseline;gap:5px}.brand-title b{font-weight:790}.brand-title small{font-size:11px;font-weight:580;color:#93a9c1;margin-left:7px;letter-spacing:.035em;text-transform:uppercase}
.header-right{display:flex;align-items:center;gap:35px}
.release-label{display:flex;align-items:center;gap:9px;font-size:12px;color:var(--muted);white-space:nowrap}
.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);flex-shrink:0;box-shadow:0 0 0 3px rgba(134,223,189,.07)}.release-label .status-dot{background:#86b8df}
.public-nav{display:flex;gap:26px}.public-nav a,.header-account{font-size:13px;font-weight:590;color:#acbed1;display:inline-flex;align-items:center;gap:8px}
.public-nav a[aria-current=page],.public-nav a:hover,.header-account:hover{color:var(--text)}
.site-main{flex:1}.content-wrap,.workspace-layout{max-width:1230px;margin:0 auto;padding:50px 36px 100px}
.content-wrap>.main-content{width:100%}.page-sign-in .content-wrap,.page-consent .content-wrap,.page-notice .content-wrap{max-width:790px;padding-top:74px}
.page-heading{margin-bottom:31px}
.eyebrow,.card-kicker{font-size:11px;letter-spacing:.13em;text-transform:uppercase;font-weight:750;color:#8fb9ec;margin:0 0 13px}
h1{font-size:clamp(33px,3.4vw,46px);line-height:1.14;letter-spacing:-.047em;font-weight:730;margin:0 0 12px}
h2{font-size:21px;line-height:1.27;font-weight:690;letter-spacing:-.034em;margin:0 0 10px}
h3{font-size:16px;line-height:1.35;font-weight:670;letter-spacing:-.02em;margin:0 0 8px}
.summary{max-width:750px;color:var(--muted);font-size:14px;line-height:1.8;margin:0}
.workspace-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:44px;padding-top:43px}
.workspace-sidebar{border-right:1px solid var(--line);padding:10px 20px 15px 0;display:flex;flex-direction:column;min-height:560px}
.sidebar-label{margin:0 0 18px;padding:0 14px;font-size:10px;color:#8b9eb5;letter-spacing:.15em;font-weight:760}
.sidebar-links{display:grid;gap:6px}.sidebar-links a{display:flex;align-items:center;gap:13px;min-height:45px;padding:0 13px;border-radius:10px;font-weight:590;font-size:13px;color:#afc0d1;transition:background .18s,color .18s}
.sidebar-links a svg{color:#8ca8c9;flex:none}.sidebar-links a:hover{color:var(--text);background:#1b2838}
.sidebar-links a[aria-current=page]{background:#22354c;color:#e6f0ff;font-weight:720;box-shadow:inset 3px 0 0 #99c7ff}.sidebar-links a[aria-current=page] svg{color:#b9d7ff}
.sidebar-footer{display:grid;grid-template-columns:12px 1fr;align-items:center;gap:6px 8px;border-top:1px solid var(--line);padding:23px 10px 0;margin-top:auto;font-size:11px}
.sidebar-footer strong{font-weight:650;color:#d3e0ee}.sidebar-footer small{grid-column:2;color:var(--muted-soft);font-size:11px;line-height:1.6}
.page-stack{display:grid;gap:23px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:27px;min-width:0;box-shadow:0 1px rgba(255,255,255,.015)}
.card p{color:var(--muted);line-height:1.74;margin:0;font-size:13px}
.card-kicker:has(svg){display:flex;align-items:center;gap:9px}.card-kicker svg{color:#a8cbf5;flex-shrink:0}
.status-pill{font-weight:690;font-size:11px;line-height:1;display:inline-flex;align-items:center;gap:8px;align-self:flex-start;padding:9px 12px;border:1px solid #38516b;border-radius:100px;color:#c2d4e8;background:#192736;white-space:nowrap}
.status-pill.ready{color:#a1ebcf;border-color:#315f54;background:#152d29}.status-pill.pending{color:#f3d39f;border-color:#6d5438;background:#32271d}
.button{display:inline-flex;align-items:center;justify-content:center;gap:10px;min-height:44px;white-space:normal;padding:11px 19px;border:1px solid #49607c;border-radius:10px;color:#e8f2ff;font-size:13px;font-weight:700;background:#26384c;transition:background .18s,border-color .18s,transform .18s}
.button:hover{background:#304960;border-color:#7394b8;transform:translateY(-1px)}.button.primary{background:#b4d4ff;border-color:#b4d4ff;color:#15253a;box-shadow:0 3px 20px rgba(123,176,246,.1)}
.button.primary:hover{background:#d5e6ff;border-color:#d5e6ff}.button.secondary{background:#243449}.button.disabled{color:#a0afc0;background:#252d38;cursor:not-allowed;opacity:.8}
.button.reject{background:#1d2937}.button.danger{background:#37272f;color:#ffd0c9;border-color:#795761}.button.danger:hover{background:#50313c}
[hidden]{display:none!important}
#pairing-manual{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}
#pairing-manual summary{cursor:pointer;color:var(--muted);font-size:12px;margin-bottom:12px}
.pairing-code{display:inline-block;letter-spacing:.09em;font-family:ui-monospace,monospace;font-size:15px;color:var(--blue)}
.action-row,.form-actions{display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin-top:26px}
.landing-panel{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(365px,.92fr);gap:0;overflow:hidden;padding:0;box-shadow:var(--shadow);background:#121b28}
.landing-intro{padding:55px 47px 40px;background:radial-gradient(ellipse at 9% 3%,rgba(93,143,211,.105),transparent 57%),#131d29}
.landing-intro h2{font-size:clamp(36px,3.5vw,49px);max-width:520px;margin:31px 0 17px;line-height:1.09;letter-spacing:-.055em;font-weight:750}
.landing-intro>p:not(.hero-note){max-width:490px;font-size:15px;line-height:1.85;color:#b9c9da}
.landing-intro .action-row{margin-top:30px}.hero-note{display:flex;align-items:center;gap:10px;margin:32px 0 0!important;font-size:12px!important;color:#a4b8ce!important}.hero-note svg{color:#94b6e1;flex-shrink:0}
.topology-panel{position:relative;display:flex;flex-direction:column;justify-content:center;min-width:0;padding:30px 35px;background:radial-gradient(circle at 50% 40%,rgba(76,126,192,.12),transparent 58%),radial-gradient(#33455d 0.65px,transparent .65px),#0e1723;background-size:auto,22px 22px,auto;border-left:1px solid #293a50}
.topology-eyebrow{display:flex;align-items:center;justify-content:space-between;margin:0 0 23px;color:#93b1cf;letter-spacing:.15em;font-weight:740;font-size:10px}.topology-eyebrow-dot{width:7px;height:7px;border-radius:50%;background:#789bbc}
.topology-node{position:relative;display:flex;align-items:center;gap:14px;background:#172433;border:1px solid #38516a;border-radius:13px;padding:15px 16px;box-shadow:0 12px 24px rgba(0,0,0,.14)}
.topology-node>span:nth-child(2){display:flex;flex-direction:column;gap:4px;min-width:0}.topology-node strong{font-size:13px;color:#edf4ff;font-weight:720}.topology-node small{color:#a9bfd3;font-size:11px;line-height:1.4}
.topology-icon{display:grid;place-items:center;width:40px;height:40px;flex:none;border-radius:10px;background:#283e56;color:#b1d2fd}
.topology-node-cloud{border-color:#5f88b6;background:#1d3147;box-shadow:0 0 0 1px rgba(154,200,254,.09),0 14px 30px rgba(0,0,0,.12)}
.topology-node-device{background:#151e2b;border-style:dashed;border-color:#445365}.topology-node-device .topology-icon{background:#26313e;color:#9cabbc}
.topology-indicator{margin-left:auto;width:8px;height:8px;border-radius:50%;background:#8490a0;flex:none}.topology-indicator.on{background:var(--green);box-shadow:0 0 0 4px rgba(134,223,189,.09)}
.topology-tag{margin-left:auto;font-size:10px;font-weight:650;color:#e1c69d;white-space:nowrap}
.topology-link{height:48px;position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center}
.topology-link span{position:absolute;width:1px;height:100%;background:#4e6d90}.topology-link span:after{content:"";position:absolute;bottom:0;left:-3px;border:4px solid transparent;border-top-color:#81aee0;transform:translateY(6px)}
.topology-link small{z-index:1;color:#94b7dc;font-size:9px;letter-spacing:.1em;font-weight:800;background:#101b2a;padding:5px 10px;border-radius:20px;border:1px solid #32475e}
.topology-link.inactive span{background:repeating-linear-gradient(to bottom,#56606e 0,#56606e 4px,transparent 4px,transparent 9px)}.topology-link.inactive span:after{border-top-color:#6c7380}
.topology-link.inactive small{color:#a5afbc;background:#131c28;border-color:#384354}
.topology-foot{display:flex;align-items:center;gap:9px;justify-content:center;margin-top:23px;font-size:11px;color:#9db4ca}
.next-section{padding-top:20px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:22px;margin-bottom:21px}.section-head h2{font-size:26px;margin:0}
.section-head p{max-width:250px;font-size:12px;color:var(--muted);margin:0;line-height:1.6;text-align:right}
.steps-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.step{position:relative;padding:25px 25px 27px;background:#111923;border:1px solid #29394a;border-radius:15px;min-height:210px}
.step-index{color:#88b2e4;font-size:12px;font-weight:760;display:flex;align-items:center;justify-content:space-between;margin:0 0 31px}
.step-icon{display:grid;place-items:center;width:43px;height:43px;border-radius:11px;background:#1e3044;color:#b2d3fd;border:1px solid #354c68}
.step p{color:var(--muted);font-size:12px;line-height:1.72;margin:0}.step-state{display:inline-block;color:#e6ca9d;font-size:11px;margin-top:12px}
.account-card{background:linear-gradient(115deg,#1a2b3d,#141e2b);border-color:#36495f}
.account-banner{display:flex;align-items:center;gap:22px}.account-banner h2{font-size:26px;margin:12px 0 5px;overflow-wrap:anywhere}
.avatar{width:70px;height:70px;flex-shrink:0;border-radius:19px;display:grid;place-items:center;background:#2b4967;border:1px solid #5f83a9;color:#e4f1ff;font-size:29px;font-weight:720}
.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.dashboard-card{display:flex;flex-direction:column;gap:6px;min-height:270px}.dashboard-card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.dashboard-card .button{margin-top:auto;align-self:flex-start}.dashboard-card>p{margin-bottom:22px}
.feature-icon,.panel-icon{height:46px;width:46px;display:grid;place-items:center;border-radius:12px;background:#243b54;border:1px solid #37526e;color:#bdd9ff;flex-shrink:0}.dashboard-card .card-kicker{margin-bottom:0}
.next-steps{display:grid;grid-template-columns:1fr 1fr;gap:35px}.next-steps h2{font-size:21px}
.status-list{display:grid;gap:0}.status-list>div{display:grid;grid-template-columns:10px 1fr auto;align-items:center;gap:12px;padding:13px 0;border-bottom:1px solid var(--line);font-size:12px;color:#d0ddea}
.status-list>div:last-child{border-bottom:0}.status-list b{font-weight:640;color:#9cddc6}.status-list .pending .status-dot{background:var(--amber)}.status-list .pending b{color:#edc995}
.auth-card,.detail-card{max-width:720px;padding:35px 38px}.panel-heading{display:flex;align-items:center;gap:16px;margin-bottom:28px}.panel-heading h2{font-size:23px}.panel-heading p{font-size:13px}
.providers{display:grid;gap:12px}.providers form{margin:0}.provider{width:100%;min-height:57px;text-align:left;justify-content:flex-start;background:#1c2837;border-color:#3a4d65;font-size:14px}
.provider-logo{width:32px;height:32px;display:grid;place-items:center;border-radius:9px;background:#edf3ff;color:#1b2434;font-weight:800}.provider-logo.github{background:#2f4156;color:#eaf4ff}.provider-arrow{margin-left:auto;color:var(--blue)}
.auth-footnote{display:flex;gap:12px;border-top:1px solid var(--line);padding-top:20px;margin-top:27px;color:#a6c4e7;align-items:flex-start}.auth-footnote svg{flex-shrink:0;margin-top:1px}.auth-footnote p{font-size:12px;line-height:1.7}
.notice-icon{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;background:#493733;color:#efc0a6;margin-bottom:22px}
.text-link,.mini-link{display:inline-flex;align-items:center;gap:7px;margin-top:21px;font-size:13px;font-weight:680;color:var(--blue)}.text-link:hover,.mini-link:hover{text-decoration:underline}
.output-notice{display:block;padding:14px 17px;background:#1b302d;border:1px solid #346253;border-radius:10px;color:#bcead9;margin-bottom:19px}
.scope-list,.connections-list{list-style:none;margin:0;padding:0;display:grid;gap:11px}
.scope-list li{background:#1b2939;border:1px solid #38516d;border-radius:11px;padding:17px 19px;font-size:12px;color:#d7e6f5;overflow-wrap:anywhere}
.scope-list strong{display:block;font-weight:670;font-size:13px;margin-bottom:4px}.scope-list code{display:block;color:var(--blue);font-size:11px;margin-top:7px}.scope-list p{margin:5px 0 0;color:var(--muted);font-size:12px}
.field-help{margin:6px 0 18px!important;color:var(--muted);font-size:13px;line-height:1.7}
.security-note:has(svg){display:flex;align-items:flex-start;gap:12px}.security-note svg{flex:none;color:#9fc4ef;margin-top:1px}
.security-note{margin-top:22px;padding:17px 19px;border-radius:11px;border:1px solid #354a61;background:#141f2d;color:#b9cde1;font-size:12px;line-height:1.75}
.connection-item{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:22px;background:#141f2d;border:1px solid #2c4055;border-radius:13px;min-width:0}
.connection-item h3{margin:0 0 8px;overflow-wrap:anywhere}.connection-item .connection-name{margin-top:12px}.connection-item p{font-size:12px;overflow-wrap:anywhere}
.mcp-endpoint{padding:14px 16px;margin:14px 0!important;border-radius:10px;
  background:#101c2b;border:1px solid #385574;overflow-wrap:anywhere}
.mcp-endpoint code{font-size:13px;color:#c0dcff;user-select:all}
.mcp-client-guides{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin:20px 0}
.mcp-client-guides>div{border:1px solid #354b62;border-radius:12px;background:#172433;padding:17px}
.mcp-client-guides .text-link{margin-top:12px;font-size:12px}
@media(max-width:700px){.mcp-client-guides{grid-template-columns:1fr}}
.connection-item form{flex-shrink:0}.permission-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:15px}
.permission-tag{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;border:1px solid #38516a;background:#202f42;padding:6px 9px;border-radius:7px;color:#c0d8f4;font-size:11px;overflow-wrap:anywhere}
.empty-state{display:flex;align-items:flex-start;gap:17px;padding:26px;background:#111b28;border:1px dashed #475f7c;border-radius:12px}
.empty-icon{flex-shrink:0;width:43px;height:43px;display:grid;place-items:center;border-radius:10px;background:#253950;color:#b9d5fc}.empty-state h3{margin:0 0 6px}.empty-state p{font-size:13px}.empty-state .status-pill{margin-top:10px}
.status-card{display:flex;gap:20px;align-items:flex-start}.status-card>div{flex:1}.status-card .status-pill{margin:0 0 16px}.status-card h2{margin-bottom:12px}
.state-detail{display:grid;gap:10px;margin-top:22px;border-top:1px solid var(--line);padding-top:20px}.state-detail>div{display:flex;justify-content:space-between;gap:18px;color:#d7e2ee;font-size:12px}.state-detail small{font-size:12px;color:var(--muted)}
input:not([type=hidden]){display:block;width:100%;margin:9px 0 16px;min-height:45px;padding:11px 14px;border:1px solid #49607d;border-radius:10px;background:#101b29;color:var(--text)}
label{display:block;font-weight:600;font-size:13px}.form-actions{justify-content:flex-end}.form-actions .reject{margin-right:auto}
.site-footer{border-top:1px solid #253244;background:#0c121b}.footer-inner{max-width:1230px;margin:auto;padding:23px 36px;display:flex;justify-content:space-between;gap:16px;font-size:11px;color:#94a8bd}.footer-separator{margin:0 7px;color:#56718d}
@media(max-width:1060px){.workspace-layout{grid-template-columns:190px minmax(0,1fr);gap:28px}.next-steps{grid-template-columns:1fr}.landing-panel{grid-template-columns:1fr 365px}.landing-intro{padding:40px 34px}.topology-panel{padding:25px 23px}.brand-title small{display:none}}
@media(max-width:750px){.header-inner{padding:12px 20px;min-height:70px}.header-right{gap:16px}.release-label{display:none}.workspace-layout{display:block;padding:28px 20px 68px}.workspace-sidebar{min-height:auto;padding:0;margin:0 0 30px;border-right:0;border-bottom:1px solid var(--line)}.sidebar-label,.sidebar-footer{display:none}.sidebar-links{display:flex;gap:7px;overflow-x:auto;padding-bottom:14px}.sidebar-links a{white-space:nowrap;min-height:42px;padding:0 13px;font-size:12px;gap:9px}.content-wrap,.page-sign-in .content-wrap,.page-consent .content-wrap,.page-notice .content-wrap{padding:37px 20px 70px}.landing-panel{grid-template-columns:1fr}.landing-intro{padding:36px 31px}.landing-intro h2{max-width:580px}.topology-panel{border-left:0;border-top:1px solid #2d4055;padding:29px 31px}.steps-grid{grid-template-columns:1fr}.step{min-height:0}.step-index{margin-bottom:22px}.section-head{display:block}.section-head p{margin:9px 0 0;text-align:left;max-width:none}.footer-inner{padding:20px}.page-heading{margin-bottom:28px}}
@media(max-width:560px){h1{font-size:33px}.brand-title{font-size:15px}.brand-mark{width:39px;height:39px}.header-right{gap:13px}.public-nav{gap:15px}.public-nav a{font-size:12px}.header-account{font-size:12px}.dashboard-grid{grid-template-columns:1fr}.landing-intro{padding:29px 25px}.landing-intro h2{font-size:37px}.topology-panel{padding:25px 19px}.topology-node{padding:13px 12px;gap:10px}.topology-icon{width:35px;height:35px}.topology-tag{font-size:9px}.topology-node strong{font-size:12px}.topology-node small{font-size:10px}.card,.auth-card,.detail-card{padding:24px}.landing-panel{padding:0}.connection-item,.status-card{display:block}.connection-item form{margin-top:17px}.form-actions .button{flex:1}.footer-inner{display:block}.footer-inner>span{display:block;margin-bottom:6px}.account-banner{align-items:flex-start}.avatar{width:52px;height:52px;font-size:21px}.next-steps{gap:19px}.panel-heading h2{font-size:20px}.page-sign-in .content-wrap{padding-top:47px}}
@media(max-width:560px){.sidebar-links{gap:3px;justify-content:space-between;overflow-x:visible}.sidebar-links a{padding:0 6px;gap:5px;min-height:44px;font-size:11px;flex-shrink:0}.sidebar-links a svg{width:15px;height:15px}}
@media(max-width:360px){.header-inner{padding-left:12px;padding-right:12px;gap:10px}.brand{gap:6px;font-size:13px}.brand-mark{width:33px;height:33px}.brand-mark svg{width:22px;height:22px}.public-nav{gap:9px}.public-nav a{font-size:11px}.header-right{gap:8px}.topology-node{gap:6px}.topology-tag{font-size:8px}.topology-node>span:nth-child(2){min-width:0;overflow-wrap:anywhere}.sidebar-links a{padding:0 4px;gap:4px;font-size:10.75px}.sidebar-links a svg{width:14px;height:14px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important;transform:none!important}}
`;
