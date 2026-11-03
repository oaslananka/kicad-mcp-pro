import assert from "node:assert/strict";
import {test} from "node:test";
import {spawnSync} from "node:child_process";
import {auditCloudflareEdge} from "./cloudflare-edge-contract.mjs";

const HOST="kicad-mcp-pro.oaslananka.dev";
const fixtureOrigin=host=>["http:","",host].join("/");
const TUNNEL="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const endpoints=[
  ["POST","/api/v1/pairing/device/challenge"],
  ["POST","/api/v1/pairing/device/redeem"],
  ["GET","/api/v1/connector/ws"]
];
function snapshot(){
  return {
    hostname:HOST,zoneName:"oaslananka.dev",expectedDedicatedTunnelId:TUNNEL,
    dns:{type:"CNAME",name:HOST,content:TUNNEL+".cfargotunnel.com",proxied:true},
    tunnel:{id:TUNNEL,status:"healthy",connectionCount:4,ingress:[
      {hostname:HOST,service:fixtureOrigin("app:8787")},
      {service:"http_status:404"}
    ]},
    rateLimiting:{
      inventoryStatus:"verified",plan:"enterprise",
      capacityVerified:true,
      rules:endpoints.map(([method,path],i)=>({
        enabled:true,action:"block",
        expression:'(http.host eq "'+HOST+'" and http.request.method eq "'+
          method+'" and http.request.uri.path eq "'+path+'")',
        characteristics:["ip.src","cf.colo.id","http.request.uri.path"],
        period:10,requestsPerPeriod:i===2?15:5
      }))
    },
    workerRoutes:{inventoryStatus:"verified",matchingHostnameCount:0},
    transformRules:{inventoryStatus:"verified",sourceHeaderRewriteCount:0},
    originIsolationAccepted:true,headerProvenanceAccepted:true
  };
}
function blocked(name,mutate,code){
  test("fail-closed Cloudflare gate: "+name,()=>{
    const value=snapshot();
    mutate(value);
    const result=auditCloudflareEdge(value);
    assert.equal(result.verdict,"BLOCKED");
    assert.ok(result.findings.includes(code),JSON.stringify(result));
  });
}
test("accepted synthetic snapshot is only a configuration prerequisite",()=>{
  assert.deepEqual(auditCloudflareEdge(snapshot()),{
    verdict:"CONFIG_PREREQUISITES_MET",findings:[]
  });
});
blocked("wrong DNS zone",x=>{x.zoneName="unrelated.invalid";},
  "WRONG_ZONE_OR_HOSTNAME");
blocked("wrong product hostname",x=>{x.hostname="unrelated.oaslananka.dev";},
  "WRONG_ZONE_OR_HOSTNAME");
blocked("DNS target wrong",x=>{x.dns.content="other.cfargotunnel.com";},
  "DNS_TUNNEL_MISMATCH");
blocked("Tunnel unhealthy",x=>{x.tunnel.status="degraded";},
  "TUNNEL_NOT_HEALTHY");
blocked("wrong origin target",x=>{x.tunnel.ingress[0].service=fixtureOrigin("legacy-app:8787");},
  "DEDICATED_ORIGIN_ROUTE_NOT_CONFIGURED");
blocked("shared tunnel routes",x=>{x.tunnel.ingress.push({
  hostname:"other.example.invalid",service:fixtureOrigin("other:3000")
});},"TUNNEL_SHARED_WITH_OTHER_HOSTNAMES");
blocked("sanitized inventory of other hostnames",x=>{
  x.tunnel.otherHostnameCount=3;
},"TUNNEL_SHARED_WITH_OTHER_HOSTNAMES");
blocked("not operator-approved tunnel",x=>{x.expectedDedicatedTunnelId="";},
  "DEDICATED_TUNNEL_NOT_ACCEPTED");
blocked("Free tier already uses one rate-limit slot",x=>{
  x.rateLimiting.plan="free";x.rateLimiting.rules=[{
    enabled:true,action:"block",expression:"cf.waf.credential_check.password_leaked",
    characteristics:["ip.src","cf.colo.id"],period:10,requestsPerPeriod:5
  }];
},"FREE_TIER_RATE_RULE_SLOT_EXHAUSTED");
blocked("no challenge rule",x=>{x.rateLimiting.rules.shift();},
  "CHALLENGE_EDGE_RULE_MISSING");
blocked("no redeem rule",x=>{x.rateLimiting.rules.splice(1,1);},
  "REDEEM_EDGE_RULE_MISSING");
blocked("no WebSocket rule",x=>{x.rateLimiting.rules.pop();},
  "WSS_EDGE_RULE_MISSING");
blocked("unscoped rule",x=>{x.rateLimiting.rules[0].expression="true";},
  "CHALLENGE_EDGE_RULE_MISSING");
blocked("no source IP characteristic",x=>{
  x.rateLimiting.rules[0].characteristics=["cf.colo.id"];
},"CHALLENGE_EDGE_RULE_MISSING");
blocked("rule cannot block",x=>{x.rateLimiting.rules[2].action="log";},
  "WSS_EDGE_RULE_MISSING");
blocked("Worker routes unknown",x=>{
  x.workerRoutes.inventoryStatus="unknown";
},"WORKER_ROUTE_INVENTORY_UNKNOWN");
blocked("Worker route hits hostname",x=>{
  x.workerRoutes.matchingHostnameCount=1;
},"WORKER_ROUTE_REQUIRES_REVIEW");
blocked("Transform phase unavailable",x=>{
  x.transformRules.inventoryStatus="unknown";
},"TRANSFORM_RULE_INVENTORY_UNKNOWN");
blocked("source header rewrite",x=>{
  x.transformRules.sourceHeaderRewriteCount=1;
},"SOURCE_HEADER_REWRITE_REQUIRES_REVIEW");
blocked("direct origin bypass unverified",x=>{
  x.originIsolationAccepted=false;
},"ORIGIN_ISOLATION_UNVERIFIED");
blocked("header authenticity unverified",x=>{
  x.headerProvenanceAccepted=false;
},"SOURCE_HEADER_PROVENANCE_UNVERIFIED");
blocked("unknown plan capacity",x=>{
  x.rateLimiting.capacityVerified=false;
},"PLAN_RULE_CAPACITY_UNVERIFIED");
test("CLI rejects missing, malformed or overlong input without printing secrets",()=>{
  for(const payload of ["","{bad","x".repeat(32_900)]){
    const result=spawnSync(process.execPath,["scripts/check-cloudflare-edge.mjs"],{
      input:payload,encoding:"utf8",timeout:10_000
    });
    assert.equal(result.status,2);
    assert.doesNotMatch(result.stdout,/secret|token/i);
  }
});
test("CLI serializes only nonsensitive findings and exits nonzero when blocked",()=>{
  const bad=snapshot();
  bad.dns.content="sensitive-content.invalid";
  const result=spawnSync(process.execPath,["scripts/check-cloudflare-edge.mjs"],{
    input:JSON.stringify(bad),encoding:"utf8",timeout:10_000
  });
  assert.equal(result.status,1);
  assert.doesNotMatch(result.stdout,/sensitive-content/);
  assert.match(result.stdout,/DNS_TUNNEL_MISMATCH/);
});
