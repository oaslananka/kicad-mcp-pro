import assert from "node:assert/strict";

/** Pure validation of the offline merged Compose model. No side effects. */
export function assertIngressCandidate(model,env,raw){
  assert.deepEqual(Object.keys(model.services).sort((a,b)=>a.localeCompare(b)),["app","cloudflared_kicad","db"]);
  assert.equal(model.name,"kicad-cloud");
  assert.equal(model.services.app.image,"kicad-mcp-pro-cloud:production");
  assert.equal(model.services.app.environment.AUTH_MODE,"external");
  // New Compose passes disabled defaults explicitly. Either absent (older
  // fixtures) or "false" is safe; "true" remains a forbidden activation.
  assert.equal(model.services.app.environment.PAIRING_DEVICE_API_ENABLED ?? "false","false");
  assert.equal(model.services.app.environment.CONNECTOR_WS_ENABLED ?? "false","false");
  assert.equal(model.services.app.environment.CONNECTOR_OPERATOR_ONESHOT_ENABLED ?? "false","false");
  assert.equal(model.services.app.environment.TRUSTED_CLOUDFLARED_PEERS ?? "","");
  assert.deepEqual(Object.keys(model.services.app.networks).sort((a,b)=>a.localeCompare(b)),
    ["connector_egress","database","ingress_private"]);
  assert.deepEqual(Object.keys(model.services.cloudflared_kicad.networks).sort((a,b)=>a.localeCompare(b)),
    ["connector_egress","ingress_private"]);
  assert.deepEqual(Object.keys(model.services.db.networks),["database"]);
  assert.equal(model.services.app.networks.ingress_private.ipv4_address,env.KICAD_INGRESS_APP_IP);
  assert.equal(model.services.cloudflared_kicad.networks.ingress_private.ipv4_address,env.KICAD_INGRESS_PROXY_IP);
  assert.equal(model.networks.ingress_private.internal,true);
  assert.ok(model.networks.ingress_private.attachable!==true);
  assert.equal(model.networks.ingress_private.ipam.config[0].subnet,env.KICAD_INGRESS_SUBNET);
  assert.ok(model.networks.connector_egress.internal!==true);
  assert.ok(model.networks.connector_egress.attachable!==true);
  assert.ok(!Object.hasOwn(model.networks,"tunnel"),
    "The shared ops_internal network must not survive overlay merging");
  assert.ok(!raw.includes("ops_internal"),
    "The legacy shared network must not be referenced");
  for(const svc of Object.values(model.services)){
    assert.equal(svc.ports,undefined,"Candidate must never publish a host port");
  }
  assert.equal(model.services.app.read_only,true);
  assert.ok(model.services.app.cap_drop.includes("ALL"));
  assert.deepEqual(model.services.cloudflared_kicad.cap_drop,["ALL"]);
  assert.equal(model.services.cloudflared_kicad.read_only,true);
  assert.equal(model.services.cloudflared_kicad.user,"65532:65532");
  assert.ok(model.services.cloudflared_kicad.command.includes("--token-file"));
  assert.ok(model.services.cloudflared_kicad.command.includes("/run/secrets/kicad_tunnel_token"));
  assert.ok(!model.services.cloudflared_kicad.command.includes("--token"));
  assert.deepEqual(model.services.cloudflared_kicad.secrets.map(x=>x.source),
    ["kicad_tunnel_token"]);
  assert.equal(model.secrets.kicad_tunnel_token.file,env.KICAD_TUNNEL_TOKEN_FILE);
  assert.equal(model.services.db.volumes[0].type,"volume");
  assert.equal(model.services.db.volumes[0].target,"/var/lib/postgresql/data");
  assert.ok(!raw.includes("KICAD_CLOUDFLARE_TUNNEL_TOKEN="),
    "Do not render token assignment into container settings");

}
