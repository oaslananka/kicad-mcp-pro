import assert from "node:assert/strict";
import {test} from "node:test";
import {renderAccount,renderLanding} from "../src/browser-ui.js";
import {renderConnectionsPage} from "../src/connections-ui.js";
import {renderDevicesPage} from "../src/devices-ui.js";
import {uiCss} from "../src/ui-styles.js";

test("brand SVG is a constrained external image, never an unscaled inline file",()=>{
  const html=renderAccount("Engineer");
  assert.match(html, /class="brand-mark"><img class="brand-logo" src="\/assets\/icon\.svg" alt="" width="24" height="24"/);
  assert.match(uiCss,/\.brand-mark \.brand-logo\{width:24px;height:24px;min-width:24px;max-width:24px;max-height:24px/);
  assert.match(uiCss,/\.brand-mark\{width:38px;height:38px;min-width:38px;max-width:38px;aspect-ratio:1/);
  assert.doesNotMatch(html, /<svg[^>]+width="512"/);
});

test("workspace overview uses full-width operational navigation, not a centered 920px funnel",()=>{
  const html=renderAccount("Engineer",["github"],["github"]);
  assert.match(html,/class="overview-tiles"/);
  assert.match(html,/class="account-columns"/);
  assert.match(html,/href="\/devices#registered-projects"/);
  assert.match(html,/href="\/connections"/);
  assert.match(html,/action="\/auth\/link\/github"|GitHub.*Connected/);
  assert.doesNotMatch(html, /Acme Hardware|Alex.s MacBook|Deploy Agent|Enterprise SSO|99\.98%|1,482 MCP/);
  assert.match(uiCss,/\.workspace-layout\{width:100%;max-width:1800px/);
  assert.match(uiCss,/@media\(max-width:750px\)/);
  assert.match(uiCss,/@media\(max-width:560px\)/);
});

test("Cloud availability never implies consent, pairing or a running device",()=>{
  const html=renderLanding(true);
  assert.match(html,/Account sign-in available/);
  assert.match(html,/Client consent required/);
  assert.match(html,/Owner pairing required/);
  assert.equal((html.match(/topology-indicator on/g)||[]).length,0);
  assert.match(html,/<details class="home-setup-guide"><summary>/);
  assert.doesNotMatch(html,/<details class="home-setup-guide" open/);
  assert.doesNotMatch(html,/Enterprise SSO|PRO Tier|FIDO2 required/);
});

test("device/client views retain actual empty states and explicit revocation actions",()=>{
  const devices=renderDevicesPage([],undefined,true);
  const apps=renderConnectionsPage([]);
  assert.match(devices,/No registered projects yet/);
  assert.doesNotMatch(devices,/Acme Hardware|Alex.s MacBook|Workstation Pro/);
  assert.match(apps,/No AI apps connected yet/);
  assert.doesNotMatch(apps,/Claude Desktop.*Active|Cursor IDE.*Connected|kmcp_live_/);
  const active=renderConnectionsPage([{
    id:"fixture",clientId:"test",csrf:"csrf",name:"Example",scopes:["projects:read"]
  }]);
  assert.match(active,/action="\/connections\/revoke"/);
  assert.match(active,/name="csrf" value="csrf"/);
});

test("obsidian UI remains first-party with accessible responsive focus",()=>{
  assert.match(uiCss,/--accent:#00daf3/);
  assert.match(uiCss,/:focus-visible/);
  assert.match(uiCss,/prefers-reduced-motion/);
  assert.doesNotMatch(uiCss,/@import|url\(https?:/i);
});
