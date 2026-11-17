import test from "node:test";
import assert from "node:assert/strict";
import {renderDevicesPage} from "../src/devices-ui.js";

test("owner device card differentiates saved edit permission from active server write capability",()=>{
  const device={
    id:"11111111-1111-4111-8111-111111111111",
    alias:"Lab Computer",enabled:true,revoked:false,fingerprint:"a".repeat(64),
    createdAt:new Date("2026-11-15T00:00:00Z"),csrf:"test",
    connectionState:"connected" as const
  };
  const project={
    id:"22222222-2222-4222-8222-222222222222",
    deviceId:device.id,alias:"Disposable",enabled:true,grantCsrf:"test"
  };
  const options={
    projects:[project],
    clients:["www.mcpjam.com"],
    writeClients:["www.mcpjam.com"],
    savedGrants:[{projectId:project.id,clientId:"www.mcpjam.com",maxMode:"write" as const}]
  };
  const unavailable=renderDevicesPage([device],undefined,true,{
    ...options,nativeWriteAvailable:false
  });
  assert.match(unavailable,/Cloud editing is not enabled/);
  assert.doesNotMatch(unavailable,/Cloud write service is ready/);
  const available=renderDevicesPage([device],undefined,true,{
    ...options,nativeWriteAvailable:true
  });
  assert.match(available,/Cloud editing is available when the owner connects the editing device/);
  assert.doesNotMatch(available,/Cloud editing is not enabled/);
  assert.match(available,/Edit permission saved/);
});

test("write-ready server without OAuth write clients shows actionable consent guidance",()=>{
  const html=renderDevicesPage([],undefined,true,{
    projects:[{
      id:"22222222-2222-4222-8222-222222222222",
      deviceId:"11111111-1111-4111-8111-111111111111",
      alias:"Disposable",enabled:true,grantCsrf:"test"
    }],
    clients:["www.mcpjam.com"],
    writeClients:[],
    savedGrants:[],
    nativeWriteAvailable:true
  });
  assert.match(html,/reconnect your AI app/i);
  assert.match(html,/projects:write/);
});
