import assert from "node:assert/strict";
import {test} from "node:test";
import {randomUUID} from "node:crypto";
import {renderDevicesPage} from "../src/devices-ui.js";
import {uiCss} from "../src/ui-styles.js";

const id=()=>randomUUID();
function device(alias:string,connectionState:"connected"|"disconnected"|"unknown",revoked=false){
 return {id:id(),alias,enabled:!revoked,revoked,fingerprint:"f".repeat(64),
   createdAt:new Date(),csrf:"csrf",deleteCsrf:revoked?"delete":undefined,
   connectionState:connectionState==="unknown"?undefined:connectionState};
}

test("devices retain functional setup while using the same workspace shell as every page",()=>{
 const html=renderDevicesPage([device("AMD2700X","connected")],undefined,true,{projects:[],ownerSub:"local-dev-owner",clients:[],savedGrants:[],sandboxMode:true});
 assert.match(html,/<title>Devices/);
 assert.match(html,/class="app-shell workspace-app"/);
 assert.doesNotMatch(html,/device-home-app|device-home-sidebar/);
 assert.match(html,/href="\/account"[^>]*>[\s\S]*?Account<\/span>/);
 assert.match(html,/href="\/devices" aria-current="page"[^>]*>.*Devices/);
 assert.match(html,/href="\/connections"/);
 assert.match(html,/href="\/settings"/);
 assert.match(html,/class="page-stack/);
 assert.doesNotMatch(html,/device-home-stack/);
 assert.match(html,/href="#connect-computer"[^>]*>.*Add a device/);
 assert.match(html,/Your devices/);
 assert.match(html,/AMD2700X/);
 assert.match(html,/Online/);
 assert.match(html,/Cloud session active/);
 assert.match(html,/action="\/devices\/revoke"/);
 assert.match(html,/<output aria-label="Connected"/);
 assert.match(html,/Local development only/);
 assert.doesNotMatch(html,/479 of 10,000|Upgrade to Pro|Revoke all/);
 assert.ok(html.indexOf("Your devices")<html.indexOf("Your projects"));
 assert.match(uiCss,/\.workspace-app \.workspace-layout/);
 assert.match(uiCss,/@media\s*\(max-width:750px\)/);
});

test("online, offline, revoked and unverified status are honest",()=>{
 const html=renderDevicesPage([
   device("Connected machine","connected"),
   device("Offline machine","disconnected"),
   device("Revoked machine","disconnected",true),
   device("Unknown machine","unknown")
 ]);
 assert.equal((html.match(/>Online<\/output>/g)||[]).length,1);
 assert.match(html,/Offline machine/);
 assert.match(html,/>Offline<\/output>/);
 assert.match(html,/>Revoked<\/output>/);
 assert.match(html,/Status unknown/);
 assert.doesNotMatch(html,/Last seen \d|kicad_probe_success/);
});

test("disabled enrollment does not present a fake Add a device action",()=>{
 const html=renderDevicesPage([],undefined,false);
 assert.doesNotMatch(html,/class="device-add-button"/);
 assert.match(html,/not enabled on this deployment/);
});
test("first pairing offers one Windows setup command and one installed app entrypoint",()=>{
  const first=renderDevicesPage([],undefined,true,{projects:[],ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false});
  assert.match(first,/irm https:\/\/raw\.githubusercontent\.com\/oaslananka\/kicad-mcp-pro\/main\/scripts\/install-cloud\.ps1 \| iex/);
  assert.match(first,/kicad-mcp-pro cloud/);
  assert.match(first,/Connect this device/);
  assert.match(first,/Keep the terminal open/);
  assert.doesNotMatch(first,/kicad-mcp-pro cloud connect|kicad-mcp-pro cloud reconnect/);
  const next=renderDevicesPage([device("Paired computer","connected")],undefined,true,
    {projects:[],ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false});
  assert.match(next,/kicad-mcp-pro cloud/);
  assert.doesNotMatch(next,/kicad-mcp-pro cloud connect|cloud reconnect/);
});

test("paired offline devices reuse the same install/update command and device identity",()=>{
 const offline=renderDevicesPage([device("Workbench","disconnected")]);
 assert.match(offline,/href="#reconnect-computer"/);
 assert.match(offline,/id="reconnect-computer"/);
 assert.match(offline,/kicad-mcp-pro cloud/);
 assert.match(offline,/same registered device/i);
 assert.match(offline,/irm https:\/\/raw\.githubusercontent\.com\/oaslananka\/kicad-mcp-pro\/main\/scripts\/install-cloud\.ps1 \| iex/);
 assert.doesNotMatch(offline,/kicad-mcp-pro cloud status|kicad-mcp-pro cloud reconnect|read-only background Connector/);
 const connected=renderDevicesPage([device("Workbench","connected")]);
 assert.doesNotMatch(connected,/id="reconnect-computer"/);
 const sandbox=renderDevicesPage([device("Workbench","disconnected")],undefined,true,{sandboxMode:true});
 assert.doesNotMatch(sandbox,/id="reconnect-computer"/);
});
