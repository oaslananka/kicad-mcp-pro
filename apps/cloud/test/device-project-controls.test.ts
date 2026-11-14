import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {test} from "node:test";
import {renderDevicesPage} from "../src/devices-ui.js";
import {deviceProjectsClient} from "../src/device-projects-client.js";
import {uiCss} from "../src/ui-styles.js";

test("device project menus default open and expose compact owner-scoped actions",()=>{
  const id=randomUUID(),first=randomUUID(),second=randomUUID();
  const device={id,alias:"My workstation",enabled:true,revoked:false,
    fingerprint:"f".repeat(64),createdAt:new Date(),csrf:"revoke",
    browseCsrf:"owner-browse",connectionState:"connected" as const};
  const projects=[{
    id:first,deviceId:id,alias:"Main board",enabled:true,
    localPath:"C:\\Projects\\Main\\Main.kicad_pro",
    renameCsrf:"rename-main",deleteCsrf:"delete-main"
  },{
    id:second,deviceId:id,alias:"Antenna",enabled:true,
    localPath:"C:\\Projects\\Main\\Antenna.kicad_pro",
    renameCsrf:"rename-antenna",deleteCsrf:"delete-antenna"
  }];
  const html=renderDevicesPage([device],undefined,true,{projects,ownerSub:"local-dev-owner",clients:[],savedGrants:[],sandboxMode:true,browseEnabled:true});
  assert.match(html,/class="device-projects-menu"[^>]*open=""/);
  assert.ok(html.includes('data-device-id="'+id+'"'));
  assert.equal((html.match(/class="device-linked-project"/g)||[]).length,2);
  assert.equal((html.match(/class="project-action-dialog project-rename-dialog"/g)||[]).length,2);
  assert.equal((html.match(/class="project-action-dialog project-remove-dialog"/g)||[]).length,2);
  assert.equal((html.match(/data-open-project-dialog="project-remove-/g)||[]).length,2);
  assert.match(html,/Main\.kicad_pro/);
  assert.match(html,/Antenna\.kicad_pro/);
  assert.match(html,/action="\/devices\/projects\/delete"/);
  assert.match(html,/action="\/devices\/projects\/rename"/);
  assert.match(html,/Remove project\?/);
  assert.match(html,/The KiCad files/);
  assert.match(html,/\/assets\/device-projects\.js/);
  assert.doesNotMatch(html,/class="device-project-remove"/);
  assert.doesNotMatch(html,/<section class="card projects-card"/);
  assert.match(uiCss,/\.project-action-dialog::backdrop/);
});

test("project menu preference is local per-device and dialogs are script-controlled",()=>{
  assert.match(deviceProjectsClient,/localStorage\.getItem/);
  assert.match(deviceProjectsClient,/localStorage\.setItem/);
  assert.match(deviceProjectsClient,/data-device-id/);
  assert.match(deviceProjectsClient,/dialog\.showModal\(\)/);
  assert.match(deviceProjectsClient,/dialog\.close\(\)/);
  assert.match(deviceProjectsClient,/fetch\("\/devices\?csrf-refresh=1"/);
  assert.doesNotMatch(deviceProjectsClient,/localStorage\.setItem\([^)]*alias/);
});

test("production fallback has no local project control or owner file paths",()=>{
  const id=randomUUID(),projectId=randomUUID();
  const html=renderDevicesPage([{
    id,alias:"Remote workstation",enabled:true,revoked:false,
    fingerprint:"a".repeat(64),createdAt:new Date(),csrf:"csrf",
    connectionState:"connected"
  }],undefined,true,{projects:[{
    id:projectId,deviceId:id,alias:"Project",enabled:true,
    localPath:"C:\\Private\\Sensitive.kicad_pro"
  }],ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false,browseEnabled:false});
  assert.doesNotMatch(html,/Sensitive\.kicad_pro/);
  assert.doesNotMatch(html,/\/assets\/device-projects\.js/);
  assert.doesNotMatch(html,/class="device-projects-menu"/);
});

test("Online legacy Connector shows a clear upgrade path instead of dead Browse",()=>{
  const id=randomUUID();
  const device={id,alias:"Old Windows machine",enabled:true,revoked:false,
    fingerprint:"f".repeat(64),createdAt:new Date(),csrf:"revoke",
    browseNeedsUpgrade:true,connectionState:"connected" as const};
  const html=renderDevicesPage([device],undefined,true,{projects:[],ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false,browseEnabled:true});
  assert.match(html,/Update the KiCad MCP Pro Connector/);
  assert.doesNotMatch(html,/action="\/devices\/projects\/browse"/);
  assert.match(html,/Online/);
});

test("production device-first projects have working action dialogs without duplicate projects card",()=>{
  const id=randomUUID(),project=randomUUID();
  const html=renderDevicesPage([{
    id,alias:"Remote KiCad",enabled:true,revoked:false,
    fingerprint:"d".repeat(64),createdAt:new Date(),csrf:"revoke",
    connectionState:"connected",browseCsrf:"browse"
  }],undefined,true,{projects:[{
    id:project,deviceId:id,alias:"Control board",enabled:true,
    renameCsrf:"rename",deleteCsrf:"remove",grantCsrf:"grant"
  }],ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false,browseEnabled:true});

  assert.equal((html.match(/class="device-linked-project"/g)||[]).length,1);
  assert.match(html,/data-open-project-dialog="project-rename-/);
  assert.match(html,/data-open-project-dialog="project-remove-/);
  assert.match(html,/src="\/assets\/device-projects\.js"/);
  assert.match(html,/id="registered-projects"/);
  assert.doesNotMatch(html,/<h2>Your projects<\/h2>/);
  assert.doesNotMatch(html,/Advanced: register a project name/);
});


test("Cloud project location copy distinguishes private paths from offline state",()=>{
  const id=randomUUID(),projectId=randomUUID();
  const device={
    id,alias:"Owner computer",enabled:true,revoked:false,
    fingerprint:"f".repeat(64),createdAt:new Date(),csrf:"revoke"
  };
  const opts={
    projects:[{id:projectId,deviceId:id,alias:"PCB",enabled:true,
      localPath:"C:\\Private\\Design.kicad_pro"}],
    ownerSub:"owner",clients:[],savedGrants:[],sandboxMode:false,browseEnabled:true
  };
  const connected=renderDevicesPage([{...device,connectionState:"connected" as const}],undefined,true,opts);
  assert.match(connected,/File path kept private on your computer/);
  assert.doesNotMatch(connected,/Local path unavailable|Design\.kicad_pro/);
  const disconnected=renderDevicesPage([{...device,connectionState:"disconnected" as const}],undefined,true,opts);
  assert.match(disconnected,/Device offline.*reconnect to access from Cloud/);
  assert.doesNotMatch(disconnected,/Design\.kicad_pro/);
});
