import assert from "node:assert/strict";
import {test} from "node:test";
import {join} from "node:path";
import {assertIngressCandidate} from "./ingress-candidate-contract.mjs";

// Synthetic RFC1918 sample, never a recommended production allocation.
const testPrefix=[10,255,242].join(".");
const env={
  KICAD_INGRESS_APP_IP:testPrefix+".3",
  KICAD_INGRESS_PROXY_IP:testPrefix+".2",
  KICAD_INGRESS_SUBNET:testPrefix+".0/29",
  KICAD_TUNNEL_TOKEN_FILE:join(process.cwd(),".kicad-ingress-test-source")
};
function valid(){
  return {
    name:"kicad-cloud",
    services:{
      app:{
        image:"kicad-mcp-pro-cloud:production",
        environment:{AUTH_MODE:"external"},
        networks:{database:{},ingress_private:{ipv4_address:env.KICAD_INGRESS_APP_IP},
          connector_egress:{}},
        read_only:true,cap_drop:["ALL"]
      },
      db:{
        networks:{database:{}},
        volumes:[{type:"volume",target:"/var/lib/postgresql/data"}]
      },
      cloudflared_kicad:{
        networks:{ingress_private:{ipv4_address:env.KICAD_INGRESS_PROXY_IP},
          connector_egress:{}},
        read_only:true,cap_drop:["ALL"],user:"65532:65532",
        command:["tunnel","--no-autoupdate","run","--token-file",
          "/run/secrets/kicad_tunnel_token"],
        secrets:[{source:"kicad_tunnel_token"}]
      }
    },
    networks:{
      database:{internal:true},
      ingress_private:{internal:true,ipam:{config:[{subnet:env.KICAD_INGRESS_SUBNET}]}},
      connector_egress:{internal:false}
    },
    secrets:{kicad_tunnel_token:{file:env.KICAD_TUNNEL_TOKEN_FILE}}
  };
}
test("a clean, private KiCad-only ingress model satisfies the offline contract",()=>{
  const model=valid();
  assert.doesNotThrow(()=>assertIngressCandidate(model,env,JSON.stringify(model)));
});
const scenarios=[
  ["re-introduces shared ops_internal network",m=>{
    m.networks.tunnel={name:"ops_internal",external:true};
  }],
  ["app loses the dedicated outbound OAuth metadata path",m=>{
    delete m.services.app.networks.connector_egress;
  }],
  ["app accidentally re-joins shared ops infrastructure",m=>{
    m.services.app.networks.ops_internal={};
  }],
  ["connector silently reuses shared egress",m=>{
    m.services.cloudflared_kicad.networks.ops_internal={};
  }],
  ["tunnel TCP peer loses static IP",m=>{
    delete m.services.cloudflared_kicad.networks.ingress_private.ipv4_address;
  }],
  ["app loses static IP",m=>{
    delete m.services.app.networks.ingress_private.ipv4_address;
  }],
  ["ingress bridge can reach the Internet",m=>{
    m.networks.ingress_private.internal=false;
  }],
  ["extra published port leaks app",m=>{
    m.services.app.ports=["8787:8787"];
  }],
  ["container unexpectedly becomes writable",m=>{
    m.services.app.read_only=false;
  }],
  ["connector receives dangerous elevated capabilities",m=>{
    m.services.cloudflared_kicad.cap_drop=[];
  }],
  ["connector token inserted in the command",m=>{
    m.services.cloudflared_kicad.command=["tunnel","run","--token","secret"];
  }],
  ["connector secret comes from an unapproved file",m=>{
    m.secrets.kicad_tunnel_token.file=join(process.cwd(),".unapproved-ingress-source");
  }],
  ["OAuth mode silently changes",m=>{
    m.services.app.environment.AUTH_MODE="builtin";
  }],
  ["device API is enabled before acceptance",m=>{
    m.services.app.environment.PAIRING_DEVICE_API_ENABLED="true";
  }],
  ["WebSocket API enabled before acceptance",m=>{
    m.services.app.environment.CONNECTOR_WS_ENABLED="true";
  }],
  ["local one-shot tool enabled before acceptance",m=>{
    m.services.app.environment.CONNECTOR_OPERATOR_ONESHOT_ENABLED="true";
  }],
  ["ingress trusted IP is set before acceptance",m=>{
    m.services.app.environment.TRUSTED_CLOUDFLARED_PEERS="172.18.0.9";
  }],
  ["persistent database volume replaced",m=>{
    m.services.db.volumes=[];
  }]
];
for(const [name,mutate] of scenarios){
  test("candidate contract rejects when "+name,()=>{
    const m=valid();
    mutate(m);
    assert.throws(()=>assertIngressCandidate(m,env,JSON.stringify(m)));
  });
}
