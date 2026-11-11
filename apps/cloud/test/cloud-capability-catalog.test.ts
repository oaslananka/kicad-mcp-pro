import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CLOUD_READ_CAPABILITIES,
  CLOUD_READ_CATEGORIES,
  CLOUD_READ_TASKS,
  listConfiguredCloudCapabilities
} from "../src/cloud-capabilities.js";

const allConfigured=Object.fromEntries(
  CLOUD_READ_TASKS.map(task=>[task,true])
) as Record<(typeof CLOUD_READ_TASKS)[number],boolean>;

test("Cloud capabilities are stable, category-first and never expose local mutation tools",()=>{
  const categories=listConfiguredCloudCapabilities(allConfigured,true);
  assert.deepEqual(categories.map(group=>group.category),CLOUD_READ_CATEGORIES);
  assert.equal(categories.reduce((sum,g)=>sum+g.tools.length,0),5);
  const tools=categories.flatMap(group=>group.tools);
  assert.deepEqual(
    tools.map(t=>t.task).sort(),
    [...CLOUD_READ_TASKS].sort()
  );
  assert.ok(tools.every(tool=>tool.mode==="readonly"));
  assert.ok(tools.every(tool=>tool.canExecuteNow===false));
  assert.ok(tools.every(tool=>tool.state==="owner_session_required"));
  assert.ok(tools.every(tool=>tool.requiresOwnerSession===true));
  assert.ok(tools.every(tool=>!/(delete|write|command|exec)/.test(tool.tool)));
  assert.equal(new Set(CLOUD_READ_CAPABILITIES.map(c=>c.tool)).size,5);
});

test("Offline Connector is not advertised as an executable tool",()=>{
  const categories=listConfiguredCloudCapabilities(allConfigured,false);
  assert.equal(categories.flatMap(group=>group.tools).length,5);
  assert.ok(categories.flatMap(group=>group.tools).every(tool=>tool.state==="device_not_connected"));
  assert.ok(categories.flatMap(group=>group.tools).every(tool=>tool.canExecuteNow===false));
});

test("Disabled operations are absent; filters do not imply capabilities",()=>{
  const onlyDrc={
    ...Object.fromEntries(CLOUD_READ_TASKS.map(task=>[task,false])),
    check_board_drc:true
  } as Record<(typeof CLOUD_READ_TASKS)[number],boolean>;
  const categories=listConfiguredCloudCapabilities(onlyDrc,true);
  assert.deepEqual(categories.map(g=>g.category),["validation"]);
  assert.deepEqual(categories[0]?.tools.map(t=>t.tool),["get_project_drc_counts"]);
  assert.deepEqual(listConfiguredCloudCapabilities(onlyDrc,true,"schematic"),[]);
  assert.deepEqual(listConfiguredCloudCapabilities(onlyDrc,true,"validation"),categories);
  assert.deepEqual(listConfiguredCloudCapabilities(
    Object.fromEntries(CLOUD_READ_TASKS.map(task=>[task,false])) as typeof onlyDrc,true
  ),[]);
});
