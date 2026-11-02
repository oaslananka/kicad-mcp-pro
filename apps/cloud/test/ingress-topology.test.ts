import assert from "node:assert/strict";
import {test} from "node:test";
import {
  inspectIngressTopology,type IngressTopology,type IngressFinding
} from "../src/ingress-topology.js";

const APP="a".repeat(64),PROXY="b".repeat(64),DB="c".repeat(64);
function fixture():IngressTopology{
  return {
    app:{
      Id:APP,Name:"/app",HostConfig:{
        NetworkMode:"bridge",PortBindings:{},Privileged:false,
        CapAdd:null,CapDrop:["ALL"],SecurityOpt:["no-new-privileges:true"]
      },
      NetworkSettings:{Networks:{
        ingress:{IPAddress:"172.30.0.3",IPAMConfig:{IPv4Address:"172.30.0.3"}},
        database:{IPAddress:"172.31.0.3",IPAMConfig:{IPv4Address:"172.31.0.3"}}
      }}
    },
    proxy:{
      Id:PROXY,Name:"/proxy",HostConfig:{
        NetworkMode:"bridge",PortBindings:{},Privileged:false,CapDrop:["ALL"]
      },
      NetworkSettings:{Networks:{
        ingress:{IPAddress:"172.30.0.2",IPAMConfig:{IPv4Address:"172.30.0.2"}},
        outbound:{IPAddress:"172.32.0.5",IPAMConfig:null}
      }}
    },
    networks:[
      {Name:"ingress",Driver:"bridge",Internal:true,Attachable:false,
        Containers:{[APP]:{Name:"app"},[PROXY]:{Name:"proxy"}}},
      {Name:"database",Driver:"bridge",Internal:true,Attachable:false,
        Containers:{[APP]:{Name:"app"},[DB]:{Name:"db"}}}
    ],
    privateNetwork:"ingress",expectedProxyIp:"172.30.0.2"
  };
}
function finding(fn:(x:IngressTopology)=>void,expected:IngressFinding){
  const input=fixture();fn(input);
  const result=inspectIngressTopology(input);
  assert.equal(result.verdict,"BLOCKED",expected);
  assert.ok(result.findings.includes(expected),JSON.stringify(result));
}

test("isolated fixed peer, internal app networks and no host ports satisfy prerequisite only",()=>{
  const report=inspectIngressTopology(fixture());
  assert.deepEqual(report,{verdict:"PREREQUISITES_MET",findings:[]});
  const changed=fixture();
  changed.app.NetworkSettings.Networks.ingress.IPAMConfig={IPv4Address:"172.30.0.3/29"};
  assert.deepEqual(inspectIngressTopology(changed),report);
});
test("current multi-tenant bridge topology cannot pass, even with a pinned proxy IP",()=>{
  finding(x=>{x.networks[0].Containers!["outsider"]={Name:"unrelated-app"};},
    "OTHER_INGRESS_MEMBERS");
  finding(x=>{x.networks[0].Internal=false;},"NETWORK_NOT_PRIVATE_BRIDGE");
  finding(x=>{x.networks[0].Attachable=true;},"NETWORK_ATTACHABLE");
});
test("dynamic peer and mismatched trusted IP fail closed",()=>{
  finding(x=>{x.proxy.NetworkSettings.Networks.ingress.IPAMConfig=null;},
    "PROXY_IP_NOT_FIXED");
  finding(x=>{x.expectedProxyIp="172.30.0.9";},"PROXY_IP_MISMATCH");
  finding(x=>{x.proxy.NetworkSettings.Networks.ingress.IPAddress="172.30.0.9";},
    "PROXY_IP_NOT_FIXED");
  finding(x=>{x.app.NetworkSettings.Networks.ingress.IPAMConfig=null;},
    "APP_IP_NOT_FIXED");
  finding(x=>{x.networks[0].Containers={[APP]:{Name:"app"}};},"PROXY_MISSING_FROM_INGRESS");
  finding(x=>{x.networks[0].Containers={[PROXY]:{Name:"proxy"}};},"APP_MISSING_FROM_INGRESS");
});
test("host published ports, elevated privileges and extra Docker networks block",()=>{
  finding(x=>{x.app.HostConfig.PortBindings={"8787/tcp":[{HostPort:"8787"}]};},
    "APP_HAS_PUBLISHED_PORTS");
  finding(x=>{x.app.HostConfig.Privileged=true;},"APP_PRIVILEGED");
  finding(x=>{x.app.HostConfig.CapAdd=["NET_ADMIN"];},"APP_EXTRA_CAPABILITIES");
  finding(x=>{x.app.HostConfig.CapDrop=[];},"APP_NO_CAP_DROP_ALL");
  finding(x=>{x.app.NetworkSettings.Networks.internet={IPAddress:"172.99.1.2"};
    x.networks.push({Name:"internet",Driver:"bridge",Internal:false,Containers:{[APP]:{Name:"app"}}});},
  "APP_HAS_NONPRIVATE_NETWORK");
  finding(x=>{x.app.NetworkSettings.Networks.extra={IPAddress:"172.99.1.2"};},
    "APP_HAS_UNVERIFIED_NETWORK");
  finding(x=>{x.app.HostConfig.NetworkMode="host";},"APP_NETWORK_MODE_UNSAFE");
  finding(x=>{x.proxy.HostConfig.NetworkMode="host";},"PROXY_NETWORK_MODE_UNSAFE");
});
test("tool rejects invalid inventory rather than guessing",()=>{
  finding(x=>{x.proxy.Id=APP;},"INVALID_INVENTORY");
  finding(x=>{x.expectedProxyIp="0.0.0.0/0";},"INVALID_INVENTORY");
  finding(x=>{x.privateNetwork="missing";},"PRIVATE_NETWORK_MISSING");
});
