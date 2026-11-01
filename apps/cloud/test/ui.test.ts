import assert from "node:assert/strict";
import {test} from "node:test";
import {renderConsentPage} from "../src/consent-ui.js";
import {renderDevicesPage} from "../src/devices-ui.js";
import {renderConnectionsPage} from "../src/connections-ui.js";
import {renderLanding,renderAccount,renderSignIn} from "../src/browser-ui.js";
import {uiCss} from "../src/ui-styles.js";

test("cloud console presents available features without overstating local KiCad support",()=>{
  const page=renderLanding(false);
  assert.match(page,/KiCad MCP Cloud/);
  assert.match(page,/Account access pending/);
  assert.doesNotMatch(page,/href="\/sign-in"/);
  assert.match(page,/Device pairing and local KiCad control are not enabled yet/);
  assert.match(page,/rel="stylesheet" href="\/assets\/ui.css"/);
  assert.doesNotMatch(page,/<script[\s>]/i);
  assert.match(uiCss,/@media\(max-width:560px\)/);
  assert.match(uiCss, /prefers-reduced-motion/);
  const open=renderLanding(true);
  assert.match(open,/href="\/sign-in"/);
});
test("sign-in presents both providers without altering signed parameters",()=>{
  const value="client_id=trusted%26scope=openid%20projects%3Aread";
  const page=renderSignIn(value);
  assert.match(page,/Continue with Google/);
  assert.match(page,/Continue with GitHub/);
  assert.match(page,/action="\/auth\/start\/google"/);
  assert.match(page,/action="\/auth\/start\/github"/);
  assert.match(page,/name="oauth_query"/);
  assert.match(page,/client_id=trusted%26scope=openid/);
  assert.doesNotMatch(page,/<script[\s>]/i);
});
test("first login presents only the configured provider",()=>{
  const github=renderSignIn("",["github"]);
  assert.match(github,/Continue with GitHub/);
  assert.doesNotMatch(github,/Continue with Google/);
  const google=renderSignIn("",["google"]);
  assert.match(google,/Continue with Google/);
  assert.doesNotMatch(google,/Continue with GitHub/);
});

test("user, client and scope content cannot inject HTML into premium pages",()=>{
  const attack='<script>alert("x")</script>';
  const account=renderAccount(attack);
  const consent=renderConsentPage({kind:"approve",clientName:attack,
    scopes:[attack,"projects:read"],query:"q&a",csrf:"csrf"});
  const connections=renderConnectionsPage([{
    id:"fixture",name:attack,scopes:[attack],clientId:"fixture-client",csrf:"csrf"
  }]);
  for(const page of [account,consent,connections]){
    assert.doesNotMatch(page,/<script[\s>]/i);
    assert.match(page,/&lt;script&gt;/);
    assert.match(page,/href="\/assets\/ui.css"/);
  }
  assert.match(consent,/name="oauth_query" value="q&amp;a"/);
  assert.match(consent,/value="approve"/);
  assert.match(consent,/value="deny"/);
  assert.match(connections,/action="\/connections\/revoke"/);
});

test("signed-in console has real navigation, clear states and readable consent",()=>{
  const account=renderAccount("Engineer");
  assert.match(account,/nav class="sidebar-links" aria-label="Workspace"/);
  assert.match(account,/aria-current="page"/);
  assert.match(account,/Local KiCad connection not enabled/);
  assert.match(account,/Manage connections/);
  const devices=renderDevicesPage([],undefined,false);
  assert.match(devices,/Not enabled/);
  assert.doesNotMatch(devices,/href="\/devices\/pairing"/);
  assert.doesNotMatch(devices,/action="\/devices\/revoke"/);
  const connections=renderConnectionsPage([{id:"one",clientId:"test-client",csrf:"fixture",
    name:"ChatGPT",scopes:["openid","projects:read"]}]);
  assert.match(connections,/1 connected app/);
  assert.match(connections,/Identify your account/);
  assert.match(connections,/title="projects:read"/);
  assert.match(connections,/Remove access/);
  const consent=renderConsentPage({kind:"approve",clientName:"ChatGPT",
    scopes:["openid","projects:read"],query:"sig",csrf:"token"});
  assert.match(consent,/Read approved projects/);
  assert.match(consent,/Project grants are separate/);
  assert.match(consent,/value="approve"/);
  assert.match(consent,/value="deny"/);
  assert.doesNotMatch(consent,/<script[\s>]/i);
  assert.match(uiCss,/\.workspace-sidebar/);
  assert.match(uiCss,/@media\(max-width:560px\)/);
  assert.match(uiCss,/:focus-visible/);
});


test("remote MCP host guidance uses configured HTTPS origin and never implies a live KiCad device",()=>{
  const html=renderConnectionsPage([],undefined,"https://cloud.example.test");
  assert.match(html,/https:\/\/cloud\.example\.test\/mcp/);
  assert.match(html,/Open Plugins, choose Add custom MCP server/);
  assert.match(html,/Open Customize \/ Connectors/);
  assert.match(html,/href="\/devices"/);
  assert.match(html,/endpoint alone does not grant project access/);
  assert.match(html,/not imply a running KiCad engine/);
  assert.match(html,/help\.openai\.com\/en\/articles\/12584461-connecting-custom-mcp-servers-in-chatgpt/);
  assert.match(html,/support\.claude\.com\/en\/articles\/11175166-get-started-with-custom-connectors-using-remote-mcp/);
  assert.doesNotMatch(html,/api[_-]?key|<script[\s>]/i);
  assert.match(uiCss,/\.mcp-client-guides/);
  const dev=renderConnectionsPage([],undefined,"http://127.0.0.1:8787");
  assert.match(dev,/not public HTTPS/);
  assert.doesNotMatch(dev,/Open Plugins, choose Add custom MCP server/);
  assert.doesNotMatch(dev,/https:\/\/cloud\.example\.test\/mcp/);
  const noOrigin=renderConnectionsPage([]);
  assert.doesNotMatch(noOrigin,/id="mcp-setup"/);
});

test("configured MCP endpoint in guidance is HTML escaped, no raw attributes injected",()=>{
  const html=renderConnectionsPage([],undefined,"https://example.test/?x=<unsafe>&y=1");
  assert.match(html,/https:\/\/example\.test\/mcp/);
  assert.doesNotMatch(html,/<unsafe>|https:\/\/example\.test\/\?x=/);
});

test("device and project controls show aliases while keeping opaque IDs in forms",()=>{
  const deviceId="11111111-1111-4111-8111-111111111111";
  const projectId="22222222-2222-4222-8222-222222222222";
  const deviceName="Main Lab";
  const html=renderDevicesPage(
    [{id:deviceId,alias:deviceName,enabled:true,revoked:false,
      fingerprint:"secret-test-fingerprint-42",createdAt:new Date(),
      csrf:"device-csrf",projectCsrf:"project-csrf",connectionState:"connected"}],
    undefined,true,
    [{id:projectId,deviceId,alias:"Controller PCB",enabled:true,grantCsrf:"grant-csrf"}],
    "private-account-id",["authorized-client"]);
  assert.match(html,/>Main Lab</);
  assert.match(html,/>Controller PCB</);
  assert.match(html,/On device: Main Lab/);
  assert.match(html,/Registered projects/);
  assert.match(html,/Advanced: local Connector account ID/);
  assert.match(html,/<details class="advanced-identity"/);
  assert.doesNotMatch(html,/Credential fingerprint|secret-test-fingerprint-42/);
  assert.doesNotMatch(html,/Registered project IDs/);
  assert.doesNotMatch(html,/<code>22222222-2222-4222-8222-222222222222<\/code>/);
  assert.doesNotMatch(html,/Device: 11111111-1111-4111-8111-111111111111/);
  assert.match(html,/name="project_id" value="22222222-2222-4222-8222-222222222222"/);
  assert.match(html,/name="device_id" value="11111111-1111-4111-8111-111111111111"/);
  assert.match(html,/name="client_id"/);
  assert.match(html,/name="csrf"/);
  const escaped=renderDevicesPage(
    [{id:deviceId,alias:"<script>device</script>",enabled:true,revoked:false,
      fingerprint:"secret",createdAt:new Date(),csrf:"csrf"}],
    undefined,true,
    [{id:projectId,deviceId,alias:"<svg onload=bad>",enabled:false}]);
  assert.doesNotMatch(escaped,/<script>|<svg onload/);
  assert.match(escaped,/&lt;script&gt;device&lt;\/script&gt;/);
  assert.match(escaped,/&lt;svg onload=bad&gt;/);
});
