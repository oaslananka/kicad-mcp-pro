import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {mkdtemp,rm,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {delimiter,join,resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {test} from "node:test";

const helper=resolve(fileURLToPath(new URL("../scripts/production-db-target.sh",import.meta.url)));
const stub=String.raw`#!/usr/bin/env bash
case "$1" in
  ps)
    [[ "$MOCK_DISCOVERY_FAIL" != 1 ]] || exit 1
    printf '%s\n' "$MOCK_MATCHES"
    ;;
  container) [[ "$MOCK_LEGACY" != 0 ]] ;;
  inspect)
    if [[ "$2" == kicad-cloud-db-1 && "$3" == --format &&
      "$4" == '{{.State.Running}}' ]]; then
      if [[ "$MOCK_LEGACY" == stopped ]]; then printf 'false\n'; else printf 'true\n'; fi
    else
      printf '%s\n' "$MOCK_HEALTH"
    fi
    ;;
  exec) printf '%s\n' "$MOCK_DATABASE" ;;
  *) exit 2 ;;
esac
`;

test("KiCad Cloud backup target chooses only one healthy verified database",
  {skip:process.platform==="win32"},async(t)=>{
    const dir=await mkdtemp(join(tmpdir(),"kicad-db-target-"));
    try{
      await writeFile(join(dir,"docker"),stub,{mode:0o700});
      const cases=[
        {name:"Coolify production database",matches:"coolify-postgres",legacy:"0",health:"healthy",database:"kicad_cloud",ok:true,expected:"coolify-postgres"},
        {name:"legacy Compose fallback",matches:"",legacy:"1",health:"healthy",database:"kicad_cloud",ok:true,expected:"kicad-cloud-db-1"},
        {name:"stopped legacy ignored",matches:"coolify-postgres",legacy:"stopped",health:"healthy",database:"kicad_cloud",ok:true,expected:"coolify-postgres"},
        {name:"no matching database",matches:"",legacy:"0",health:"healthy",database:"kicad_cloud",ok:false},
        {name:"two Coolify databases",matches:"db-one\ndb-two",legacy:"0",health:"healthy",database:"kicad_cloud",ok:false},
        {name:"legacy plus Coolify ambiguous",matches:"coolify-postgres",legacy:"1",health:"healthy",database:"kicad_cloud",ok:false},
        {name:"unhealthy database",matches:"coolify-postgres",legacy:"0",health:"unhealthy",database:"kicad_cloud",ok:false},
        {name:"wrong database identity",matches:"coolify-postgres",legacy:"0",health:"healthy",database:"unrelated",ok:false},
        {name:"Docker discovery failure",matches:"coolify-postgres",legacy:"0",health:"healthy",database:"kicad_cloud",ok:false}
      ] as const;
      for(const item of cases){
        await t.test(item.name,()=>{
          const args=["-c",'source "'+helper+'" && kicad_cloud_database_container'];
          const result=spawnSync("bash",args,{encoding:"utf8",
            env:{...process.env,PATH:dir+delimiter+process.env.PATH,
              MOCK_MATCHES:item.matches,MOCK_LEGACY:item.legacy,
              MOCK_HEALTH:item.health,MOCK_DATABASE:item.database,
              MOCK_DISCOVERY_FAIL:item.name==="Docker discovery failure"?"1":"0"}});
          if(item.ok){
            assert.equal(result.status,0,result.stderr);
            assert.equal(result.stdout.trim(),item.expected);
          }else{
            assert.notEqual(result.status,0);
          }
        });
      }
    }finally{
      await rm(dir,{recursive:true,force:true});
    }
  });
