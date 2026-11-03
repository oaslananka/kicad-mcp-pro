import test from "node:test";
import assert from "node:assert/strict";
import {execFileSync,spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {dirname,resolve} from "node:path";
const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const base={
  PUBLIC_ORIGIN:"https://pcb.example.test",
  OAUTH_ISSUER:"https://pcb.example.test/api/auth",
  OAUTH_JWKS_URL:"https://pcb.example.test/api/auth/jwks",
  OAUTH_AUDIENCE:"https://pcb.example.test/mcp",
  KICAD_DB_PASSWORD:"not-a-secret-test-fixture",
  AUTH_MODE:"builtin",BETTER_AUTH_SECRET:"synthetic-auth-fixture-value-at-least-32-characters",
  GITHUB_CLIENT_ID:"sample-id",GITHUB_CLIENT_SECRET:"not-a-secret-test-fixture",
  KICAD_TUNNEL_NETWORK:"pcb_dedicated_ingress",
  CLOUDFLARE_TUNNEL_TOKEN:"not-a-secret-test-fixture"};
const cli=(action,updates={})=>spawnSync(process.execPath,["scripts/portable-config.mjs",action],
  {cwd:root,env:{...base,...updates},encoding:"utf8"});
test("public target and dedicated network are validated without printing secrets",()=>{
  assert.equal(cli("origin").stdout.trim(),base.PUBLIC_ORIGIN);
  assert.equal(cli("network").stdout.trim(),base.KICAD_TUNNEL_NETWORK);
  assert.equal(cli("google").stdout.trim(),"false");
  assert.equal(cli("google",{GOOGLE_CLIENT_ID:"google-test",GOOGLE_CLIENT_SECRET:"dummy"}).stdout.trim(),"true");
  const result=cli("validate");
  assert.equal(result.status,0,result.stderr);
  assert.doesNotMatch(result.stdout, /not-a-secret-test-fixture/);
});
test("fail closed on unsafe or inconsistent deployment config",()=>{
  for(const delta of [
    {PUBLIC_ORIGIN:"http://pcb.example.test"},
    {PUBLIC_ORIGIN:"https://pcb.example.test/with-path"},
    {PUBLIC_ORIGIN:"https://user:pass@pcb.example.test"},
    {OAUTH_AUDIENCE:"https://another.example/mcp"},
    {OAUTH_ISSUER:"https://another.example/api/auth"},
    {AUTH_MODE:"external"},
    {AUTH_MODE:""},
    {BETTER_AUTH_SECRET:"short"},
    {BETTER_AUTH_SECRET:"x".repeat(31)},
    {KICAD_DB_PASSWORD:""},
    {ALLOWED_ORIGINS:"http://insecure.example.test"},
    {ALLOWED_ORIGINS:"https://ok.example.test/prefix"},
    {ALLOWED_ORIGINS:"https://username:pass@ok.example.test"},
    {ALLOWED_ORIGINS:"not-an-origin"},
    {GITHUB_CLIENT_SECRET:""},
    {GOOGLE_CLIENT_ID:"partial-google"},
    {KICAD_TUNNEL_NETWORK:"bad network/name"},
    {CONNECTOR_WS_ENABLED:"true"},
    {PAIRING_DEVICE_API_ENABLED:"true"}
  ]) {
    const out=cli("validate",delta);
    assert.notEqual(out.status,0,JSON.stringify(Object.keys(delta)));
    assert.doesNotMatch(out.stderr,/not-a-secret-test-fixture/);
  }
});
test("Doppler configuration fingerprint changes on credential or routing drift without revealing secrets",()=>{
  const baseline=cli("fingerprint");
  assert.equal(baseline.status,0,baseline.stderr);
  assert.match(baseline.stdout.trim(),/^[a-f0-9]{64}$/);
  assert.equal(cli("fingerprint").stdout,baseline.stdout);
  for(const delta of [
    {KICAD_DB_PASSWORD:"different-secret-test-fixture"},
    {BETTER_AUTH_SECRET:"another-synthetic-auth-secret-value-that-is-long"},
    {GITHUB_CLIENT_SECRET:"different-github-client-credential"},
    {CLOUDFLARE_TUNNEL_TOKEN:"different-tunnel-credential"},
    {PUBLIC_ORIGIN:"https://new-pcb.example.test",
     OAUTH_ISSUER:"https://new-pcb.example.test/api/auth",
     OAUTH_JWKS_URL:"https://new-pcb.example.test/api/auth/jwks",
     OAUTH_AUDIENCE:"https://new-pcb.example.test/mcp"},
    {MANAGEMENT_CLIENT_ID:"new-owner"},
    {ALLOWED_ORIGINS:"https://client.example.test"},
    {KICAD_TUNNEL_NETWORK:"alternative_ingress"}
  ]){
    const result=cli("fingerprint",delta);
    assert.equal(result.status,0,result.stderr);
    assert.match(result.stdout.trim(),/^[a-f0-9]{64}$/);
    assert.notEqual(result.stdout,baseline.stdout);
    assert.doesNotMatch(result.stdout,/synthetic|fixture|credential|secret|token/i);
  }
  const invalid=cli("fingerprint",{BETTER_AUTH_SECRET:"short"});
  assert.notEqual(invalid.status,0);
  assert.doesNotMatch(invalid.stderr,/synthetic-auth-fixture/);
});
test("new VPS accepts exact 32-character auth secret and HTTPS allowlist",()=>{
  const result=cli("validate",{
    BETTER_AUTH_SECRET:"x".repeat(32),
    ALLOWED_ORIGINS:"https://owner.example.test, https://client.example.test"
  });
  assert.equal(result.status,0,result.stderr);
});
test("production compose accepts configurable external network and forwards management config",()=>{
  const output=execFileSync("/usr/bin/docker",["compose","-f","infra/compose.production.yml","config","--format","json"],
    {cwd:root,env:{...base,MANAGEMENT_CLIENT_ID:"owner-ui",ALLOWED_ORIGINS:base.PUBLIC_ORIGIN},encoding:"utf8"});
  const config=JSON.parse(output);
  assert.equal(config.networks.tunnel.name,base.KICAD_TUNNEL_NETWORK);
  assert.equal(config.networks.tunnel.external,true);
  assert.equal(config.services.app.environment.MANAGEMENT_CLIENT_ID,"owner-ui");
  assert.equal(config.services.app.environment.ALLOWED_ORIGINS,base.PUBLIC_ORIGIN);
  assert.equal(config.services.app.ports,undefined);
});
test("managed Cloudflare tunnel is opt-in, bound to dedicated network and publishes no ports",()=>{
  const output=execFileSync("/usr/bin/docker",["compose","-f","infra/compose.cloudflare.yml","config","--format","json"],
    {cwd:root,env:base,encoding:"utf8"});
  const config=JSON.parse(output);
  assert.equal(config.networks.ingress.external,true);
  assert.equal(config.networks.ingress.name,base.KICAD_TUNNEL_NETWORK);
  assert.equal(config.services.cloudflared.environment.TUNNEL_TOKEN,base.CLOUDFLARE_TUNNEL_TOKEN);
  assert.equal(config.services.cloudflared.ports,undefined);
  assert.equal(config.services.cloudflared.privileged,undefined);
});

test("scoped VPS mode refuses inherited Doppler selection and never echoes secrets",()=>{
  for (const entry of [
    {DOPPLER_TOKEN:"synthetic-token-do-not-use"},
    {DOPPLER_PROJECT:"wrong-project"},
    {DOPPLER_CONFIG:"wrong-config"}
  ]) {
    const result=spawnSync("/usr/bin/bash",["scripts/doppler-runtime.sh","node","--version"],
      {cwd:root,env:{KICAD_DOPPLER_SCOPED:"true",...entry},encoding:"utf8"});
    assert.equal(result.status,2);
    assert.match(result.stderr,/Ambiguous Doppler selection/);
    assert.ok(!Object.values(entry).some(value=>result.stderr.includes(value)));
  }
});
test("token enrollment only runs with an interactive terminal",()=>{
  const result=spawnSync("/usr/bin/bash",["scripts/setup-vps-doppler.sh","test-project","test-config"],
    {cwd:root,env:{},encoding:"utf8",input:"synthetic-token-do-not-use\n"});
  assert.equal(result.status,2);
  assert.match(result.stderr,/Interactive owner TTY required/);
  assert.doesNotMatch(result.stderr,/synthetic-token-do-not-use/);
});

test("protected production watcher keeps selected ingress across deploy and rollback",()=>{
  const validate=(mode)=>spawnSync("/usr/bin/bash",["-c",
    "set -euo pipefail; source scripts/production-compose-files.sh; select_production_compose_files; printf '%s\\n' \"${production_compose_files[@]}\""],
    {cwd:root,env:{...base,KICAD_CLOUD_PRODUCTION_INGRESS:mode},encoding:"utf8"});
  const shared=validate("shared");
  assert.equal(shared.status,0,shared.stderr);
  assert.deepEqual(shared.stdout.trim().split("\n"),
    ["-f","infra/compose.production.yml"]);
  const isolated=validate("isolated");
  assert.equal(isolated.status,0,isolated.stderr);
  assert.deepEqual(isolated.stdout.trim().split("\n"),
    ["-f","infra/compose.production.yml","-f","infra/compose.isolated-ingress.candidate.yml"]);
  const invalid=validate("unreviewed");
  assert.notEqual(invalid.status,0);
});
