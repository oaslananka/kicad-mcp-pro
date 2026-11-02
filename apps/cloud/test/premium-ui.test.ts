import assert from "node:assert/strict";
import {test} from "node:test";
import {renderAccount,renderLanding,renderSignIn} from "../src/browser-ui.js";
import {renderConnectionsPage} from "../src/connections-ui.js";
import {renderConsentPage} from "../src/consent-ui.js";
import {renderDevicesPage} from "../src/devices-ui.js";
import {renderPairingReviewPage} from "../src/pairing-review-ui.js";
import {uiCss} from "../src/ui-styles.js";

test("premium visual language is first-party, consistent and responsive",()=>{
  for(const token of ["--bg:","--surface:","--blue:","--green:","--amber:","--danger:"]){
    assert.ok(uiCss.includes(token),"missing design token "+token);
  }
  assert.match(uiCss,/@media\(max-width:750px\)/);
  assert.match(uiCss,/@media\(max-width:560px\)/);
  assert.match(uiCss,/prefers-reduced-motion/);
  assert.match(uiCss,/:focus-visible/);
  assert.match(uiCss,/\.topology-panel/);
  assert.doesNotMatch(uiCss,/@import|url\(https?:|animation:\s*infinite/i);
});
test("landing topology shows Cloud availability but no active KiCad connection",()=>{
  const enabled=renderLanding(true);
  assert.match(enabled,/ACCESS ARCHITECTURE/);
  assert.match(enabled,/EXPLICIT PERMISSIONS/);
  assert.match(enabled,/Connection not enabled/);
  assert.match(enabled,/Project access always requires separate approval/);
  assert.match(enabled,/href="\/sign-in"/);
  assert.match(enabled,/<svg[^>]+aria-hidden="true"/);
  assert.doesNotMatch(enabled,/Foundation preview|<script[\s>]/i);
  const disabled=renderLanding(false);
  assert.match(disabled,/Account access pending/);
  assert.doesNotMatch(disabled,/href="\/sign-in"/);
  assert.match(disabled,/Connection not enabled/);
});
test("security pages share brand/navigation while preserving authorization forms",()=>{
  const pages=[
    renderSignIn("opaque",["github"]),renderAccount("Engineer"),
    renderConnectionsPage([{id:"fixture",clientId:"client",csrf:"csrf",
      name:"AI client",scopes:["openid"]}]),
    renderDevicesPage([],undefined,false),
    renderConsentPage({kind:"approve",clientName:"AI client",
      scopes:["openid","projects:read"],query:"opaque",csrf:"csrf"}),
    renderPairingReviewPage("csrf")
  ];
  for(const html of pages){
    assert.match(html,/<main id="main-content"/);
    assert.match(html,/href="\/assets\/ui.css"/);
    assert.match(html,/class="brand-mark"/);
    assert.match(html,/aria-label="KiCad MCP Cloud home"/);
    assert.match(html,/<svg[^>]+aria-hidden="true"/);
    if (html === pages[5]) {
      assert.match(html, /src="\/assets\/pairing-review\.js"/);
      assert.doesNotMatch(html, /<script(?![^>]*src=)/i);
    } else assert.doesNotMatch(html, /<script[\s>]/i);
  }
  assert.match(pages[0],/action="\/auth\/start\/github"/);
  assert.match(pages[2],/action="\/connections\/revoke"/);
  assert.match(pages[4],/value="deny"[^>]*name="decision"/);
  assert.match(pages[4],/value="approve"[^>]*name="decision"/);
  assert.match(pages[5],/name="csrf"/);
});
