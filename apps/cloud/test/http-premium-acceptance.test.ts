import assert from "node:assert/strict";
import {test} from "node:test";
import {renderLanding,renderSignIn,renderAccount} from "../src/browser-ui.js";
import {renderDevicesPage} from "../src/devices-ui.js";
import {renderConnectionsPage} from "../src/connections-ui.js";
import {uiCss} from "../src/ui-styles.js";

test("HTTP replaces desktop download but Cloud /mcp and authorization remain visible",()=>{
 const landing=renderLanding(true);
 const signin=renderSignIn("",["google","github"]);
 const connections=renderConnectionsPage([],undefined,"https://cloud.example.test");
 assert.match(landing,/href="#http-setup"/);
 assert.match(landing,/127\.0\.0\.1:3334\/mcp/);
 assert.doesNotMatch(landing+signin,/Tauri|desktop app|\.dmg|AppImage|setup\.exe/i);
 assert.match(signin,/action="\/auth\/start\/github"/);
 assert.match(connections,/https:\/\/cloud\.example\.test\/mcp/);
});
test("unavailable device status has real inset and AI rows have full-size click targets",()=>{
 const html=renderDevicesPage([],undefined,false);
 assert.match(html,/class="card status-card" id="registered-projects"><div class="status-message">/);
 assert.equal((html.match(/class="client-shortcut-link"/g)??[]).length,3);
 assert.match(uiCss,/\.page-devices \.status-card\{padding:var\(--card-padding\)/);
 assert.match(uiCss,/\.client-shortcut-link\{min-height:76px/);
 assert.match(uiCss,/@media\(max-width:560px\)/);
});
test("next action guides true state without manufacturing connectivity",()=>{
 for(const [snapshot,key] of [
  [{devices:0,projects:0,clients:0,grants:0},"pair-device"],
  [{devices:1,projects:0,clients:0,grants:0},"add-project"],
  [{devices:1,projects:1,clients:0,grants:0},"connect-client"],
  [{devices:1,projects:1,clients:1,grants:0},"grant-access"],
  [{devices:1,projects:1,clients:1,grants:1},"review-access"]
 ] as const){
   assert.match(renderAccount("Engineer",["github"],[],snapshot),new RegExp('data-next-action="'+key+'"'));
 }
});

test("Cloud choice never sends people to HTTP when Cloud sign-in is unavailable",()=>{
 const available=renderLanding(true);
 const pending=renderLanding(false);
 assert.match(available,/<a class="entry-choice entry-choice-cloud" href="\/sign-in">/);
 assert.match(pending,/<div class="entry-choice entry-choice-cloud unavailable" aria-disabled="true">/);
 assert.doesNotMatch(pending,/<a class="entry-choice entry-choice-cloud"/);
 assert.match(pending,/Cloud sign-in unavailable/);
 assert.match(pending,/Pair your computer/);
});
