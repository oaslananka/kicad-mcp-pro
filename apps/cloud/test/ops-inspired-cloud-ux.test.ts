import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {renderPage} from "../src/ui-shell.js";
import {renderDevicesPage} from "../src/devices-ui.js";
import {uiCss} from "../src/ui-styles.js";

const deviceId=randomUUID(),projectId=randomUUID();
const device={id:deviceId,alias:"Assembly station",enabled:true,revoked:false,
  fingerprint:"fixture",createdAt:new Date(),csrf:"device-csrf",
  browseCsrf:"browse-csrf",connectionState:"connected" as const};
const project={id:projectId,deviceId,alias:"RoyalBlue54L-Feather long PCB title",
  enabled:true,renameCsrf:"rename-csrf",deleteCsrf:"delete-csrf",grantCsrf:"grant-csrf"};

test("signed-in workspace prioritizes Devices without removing old project deep links",()=>{
  const html=renderPage({title:"Devices",kind:"devices",children:null});
  assert.match(html,/href="\/devices" class="brand"/);
  assert.ok(html.indexOf('href="/devices"')<html.indexOf('href="/projects"'));
  assert.match(html,/href="\/projects"/);
  assert.match(html,/href="\/devices" aria-current="page"/);
});

test("Ops-inspired warm-neutral palette uses lavender only for primary interactions",()=>{
  assert.match(uiCss,/--bg:#0f0e0d/);
  assert.match(uiCss,/--surface:#171513/);
  assert.match(uiCss,/--accent:#a99bff/);
  assert.match(uiCss,/--green:#65dca0/);
  assert.match(uiCss,/--amber:#f4c15d/);
  assert.match(uiCss,/--danger:#ff8d88/);
});

test("device project card spans the content width instead of the status-dot track",()=>{
  const html=renderDevicesPage([device],undefined,true,{
    browseEnabled:true,projects:[project],clients:[],savedGrants:[]
  });
  assert.match(html,/RoyalBlue54L-Feather long PCB title/);
  assert.match(html,/data-device-id="/);
  assert.match(html,/Add project/);
  assert.match(html,/data-open-project-dialog="project-rename-/);
  assert.match(html,/data-open-project-dialog="project-remove-/);
  assert.match(html,/>Manage access<\/summary>/);
  assert.ok(uiCss.includes(".device-projects-menu{grid-column:2/-1"));
  assert.ok(uiCss.includes(".device-project-permissions{grid-column:1/-1"));
  assert.match(uiCss,/@media\(max-width:750px\)/);
  assert.match(uiCss,/@media\(max-width:400px\)/);
  assert.ok(uiCss.includes(".workspace-app .device-card{padding:0}"));
});

test("known AI connections keep the device screen task-first",()=>{
  const html=renderDevicesPage([device],undefined,true,{
    browseEnabled:true,projects:[project],clients:["https://chatgpt.com"],
    savedGrants:[]
  });
  assert.doesNotMatch(html,/Where you use it/);
  assert.match(html,/Manage access/);
});
