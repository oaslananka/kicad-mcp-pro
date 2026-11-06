// Public HTTPS metadata is data, never executable source. Keep remote payloads
// out of shell pipelines into interpreters (Scorecard downloadThenRun).
import {resolve} from "node:path";
import {pathToFileURL} from "node:url";

const COMMIT_SHA=/^[a-f0-9]{40}$/;

export async function readPublicHealthRevision(origin,options={}){
  const {requireOk=false,fetchImpl=globalThis.fetch,timeoutMs=10_000}=options;
  const base=new URL(origin);
  if(base.protocol!=="https:" || base.username || base.password ||
     base.search || base.hash || base.pathname!=="/"){
    throw new Error("Invalid public HTTPS origin");
  }
  const endpoint=new URL("/health",base);
  const response=await fetchImpl(endpoint,{redirect:"error",
    headers:{Accept:"application/json"},signal:AbortSignal.timeout(timeoutMs)});
  if(!response.ok){
    throw new Error("Public health HTTP error");
  }
  const data=await response.json();
  if(!data || typeof data!=="object" ||
     !COMMIT_SHA.test(data.revision) || (requireOk && data.status!=="ok")){
    throw new Error("Invalid public health metadata");
  }
  return data.revision;
}

if(process.argv[1] && pathToFileURL(resolve(process.argv[1])).href===import.meta.url){
  try{
    process.stdout.write(await readPublicHealthRevision(
      process.argv[2],{requireOk:process.argv[3]==="--require-ok"}));
  }catch{
    process.stderr.write("Public HTTPS health verification unavailable\n");
    process.exitCode=1;
  }
}
