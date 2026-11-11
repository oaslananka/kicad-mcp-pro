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

test("devices become the first, compact home card with a functional setup link",()=>{
 const html=renderDevicesPage([device("AMD2700X","connected")],undefined,true,[],
   "local-dev-owner",[],[],true);
 assert.match(html,/<title>Devices/);
 assert.match(html,/class="app-shell workspace-app device-home-app"/);
 assert.match(html,/class="page-stack device-home-stack/);
 assert.match(html,/href="#connect-computer"[^>]*>.*Add a device/);
 assert.match(html,/Your devices/);
 assert.match(html,/AMD2700X/);
 assert.match(html,/Online/);
 assert.match(html,/Cloud session active/);
 assert.match(html,/action="\/devices\/revoke"/);
 assert.match(html,/role="status"/);
 assert.match(html,/Local development only/);
 assert.doesNotMatch(html,/479 of 10,000|Upgrade to Pro|Revoke all/);
 assert.ok(html.indexOf("Your devices")<html.indexOf("Your projects"));
 assert.match(uiCss,/\.device-home-app\s*\{/);
 assert.match(uiCss,/\.device-home-app \.workspace-layout/);
 assert.match(uiCss,/@media\s*\(max-width:750px\)/);
});

test("online, offline, revoked and unverified status are honest",()=>{
 const html=renderDevicesPage([
   device("Connected machine","connected"),
   device("Offline machine","disconnected"),
   device("Revoked machine","disconnected",true),
   device("Unknown machine","unknown")
 ]);
 assert.equal((html.match(/>Online<\/span>/g)||[]).length,1);
 assert.match(html,/Offline machine/);
 assert.match(html,/>Offline<\/span>/);
 assert.match(html,/>Revoked<\/span>/);
 assert.match(html,/Status unknown/);
 assert.doesNotMatch(html,/Last seen \d|kicad_probe_success/);
});

test("disabled enrollment does not present a fake Add a device action",()=>{
 const html=renderDevicesPage([],undefined,false);
 assert.doesNotMatch(html,/class="device-add-button"/);
 assert.match(html,/not enabled on this deployment/);
});