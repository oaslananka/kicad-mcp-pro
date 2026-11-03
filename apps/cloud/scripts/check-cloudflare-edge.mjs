import {readFileSync} from "node:fs";
import {auditCloudflareEdge} from "./cloudflare-edge-contract.mjs";

// Strictly offline read of a sanitized JSON snapshot from stdin. No API
// calls, no network access, no Cloudflare tokens or environment secrets.
// JSON contents are never echoed; output only non-sensitive finding codes.
const args=process.argv.slice(2);
if(args.length!==0){
  process.stderr.write("Usage: node scripts/check-cloudflare-edge.mjs < sanitized-snapshot.json\n");
  process.exitCode=2;
}else{
  try{
    const content=readFileSync(0,{encoding:"utf8"});
    if(!content||content.length>32_768)throw new Error("SNAPSHOT_SIZE_INVALID");
    const snapshot=JSON.parse(content);
    if(!snapshot||typeof snapshot!=="object"||Array.isArray(snapshot))
      throw new Error("SNAPSHOT_INVALID");
    const report=auditCloudflareEdge(snapshot);
    process.stdout.write(JSON.stringify(report)+"\n");
    if(report.verdict!=="CONFIG_PREREQUISITES_MET")process.exitCode=1;
  }catch{
    process.stderr.write("Invalid sanitized Cloudflare snapshot; release gate BLOCKED\n");
    process.exitCode=2;
  }
}
