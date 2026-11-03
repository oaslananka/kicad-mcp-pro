import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {test} from "node:test";
import {fileURLToPath} from "node:url";
import {dirname,resolve} from "node:path";

const cloud=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const docker=spawnSync("docker",["compose","version"],{encoding:"utf8"});
test("Coolify Git application Compose is private and preserves dedicated ingress isolation",
  {skip:docker.status!==0},()=>{
  const env={...process.env,
    DATABASE_URL:"postgresql://fixture:fixture@db.invalid/cloud",
    PUBLIC_ORIGIN:"https://cloud.example.test",
    OAUTH_ISSUER:"https://cloud.example.test/api/auth",
    OAUTH_JWKS_URL:"https://cloud.example.test/api/auth/jwks",
    OAUTH_AUDIENCE:"https://cloud.example.test/mcp",
    BETTER_AUTH_SECRET:"a".repeat(48),
    GOOGLE_CLIENT_ID:"client-id",
    GOOGLE_CLIENT_SECRET:"fixture",
    GITHUB_CLIENT_ID:"client-id",
    GITHUB_CLIENT_SECRET:"fixture",
    KICAD_INGRESS_APP_IP:"10.42.24.44",
    KICAD_INGRESS_NETWORK:"kicad-cloud-ingress-fixture",
    KICAD_INTERNAL_NETWORK:"coolify"
  };
  const rendered=spawnSync("docker",[
    "compose","-f","compose.coolify.yml","config","--format","json"
  ],{cwd:cloud,env,encoding:"utf8"});
  assert.equal(rendered.status,0,rendered.stderr);
  const parsed=JSON.parse(rendered.stdout);
  assert.deepEqual(Object.keys(parsed.services),["api"],
    "No shadow Postgres, Tunnel or extra proxy is created by Coolify");
  const api=parsed.services.api;
  assert.equal(api.build.context,cloud);
  assert.equal(api.read_only,true);
  assert.equal(api.environment.PUBLIC_ORIGIN,env.PUBLIC_ORIGIN);
  assert.equal(api.environment.GOOGLE_CLIENT_SECRET,env.GOOGLE_CLIENT_SECRET);
  assert.equal(api.environment.CONNECTOR_WS_ENABLED,"false");
  assert.equal(api.environment.CONNECTOR_MANAGED_READ_ENABLED,"false");
  assert.equal(api.ports,undefined,"API must never publish a host port");
  assert.equal(api.networks.tunnel_ingress.ipv4_address,env.KICAD_INGRESS_APP_IP);
  assert.equal(parsed.networks.tunnel_ingress.external,true);
  assert.equal(parsed.networks.tunnel_ingress.name,env.KICAD_INGRESS_NETWORK);
  assert.equal(parsed.networks.coolify.external,true);
  assert.equal(parsed.networks.coolify.name,"coolify");
  assert.deepEqual(api.cap_drop,["ALL"]);
});

test("Coolify Compose requires a preapproved ingress network and static IP",
  {skip:docker.status!==0},()=>{
    const env={...process.env,
      DATABASE_URL:"postgresql://fixture:fixture@db.invalid/cloud",
      PUBLIC_ORIGIN:"https://cloud.example.test",
      OAUTH_ISSUER:"https://cloud.example.test/api/auth",
      OAUTH_JWKS_URL:"https://cloud.example.test/api/auth/jwks",
      OAUTH_AUDIENCE:"https://cloud.example.test/mcp",
      BETTER_AUTH_SECRET:"a".repeat(48),
      KICAD_INGRESS_APP_IP:"",
      KICAD_INGRESS_NETWORK:""
    };
    const result=spawnSync("docker",[
      "compose","-f","compose.coolify.yml","config","--quiet"
    ],{cwd:cloud,env,encoding:"utf8"});
    assert.notEqual(result.status,0,"Missing private ingress config must fail closed");
});
