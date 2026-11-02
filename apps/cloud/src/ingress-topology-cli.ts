import {execFileSync} from "node:child_process";
import {inspectIngressTopology,type DockerContainerSnapshot,type DockerNetworkSnapshot}
  from "./ingress-topology.js";

// This read-only CLI is intended for the authorized operator's VPS host.
// Never mounts /var/run/docker.sock into the production application container.
function dockerRead<T>(args:string[]):T{
  const result=execFileSync("/usr/bin/docker",args,{
    encoding:"utf8",timeout:5_000,maxBuffer:256*1024,
    stdio:["ignore","pipe","pipe"]
  });
  return JSON.parse(result) as T;
}
// Inspect ONLY the minimum fields required. Docker Config.Env may contain
// credentials and must never be copied into this utility, even transiently.
const containerFormat='{"Id":{{json .Id}},"Name":{{json .Name}},'+
  '"HostConfig":{"NetworkMode":{{json .HostConfig.NetworkMode}},'+
  '"PortBindings":{{json .HostConfig.PortBindings}},'+
  '"Privileged":{{json .HostConfig.Privileged}},'+
  '"CapAdd":{{json .HostConfig.CapAdd}},'+
  '"CapDrop":{{json .HostConfig.CapDrop}}},'+
  '"NetworkSettings":{"Networks":{{json .NetworkSettings.Networks}}}}';
const networkFormat='{"Name":{{json .Name}},"Driver":{{json .Driver}},'+
  '"Internal":{{json .Internal}},"Attachable":{{json .Attachable}},'+
  '"Containers":{{json .Containers}}}';
function container(name:string):DockerContainerSnapshot{
  return dockerRead(["inspect","--type","container","--format",containerFormat,name]);
}
function network(name:string):DockerNetworkSnapshot{
  return dockerRead(["network","inspect","--format",networkFormat,name]);
}
const args=process.argv.slice(2);
const expected=["--app","--proxy","--network","--expected-peer"];
const values=new Map<string,string>();
let invalid=args.length!==expected.length*2;
for(let i=0;i<args.length;i+=2){
  const key=args[i],value=args[i+1];
  if(!expected.includes(key)||!value||values.has(key)||
     !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$/.test(value))invalid=true;
  if(key&&value)values.set(key,value);
}
if(expected.some(key=>!values.has(key)))invalid=true;
if(invalid){
  process.stderr.write("Usage: npm run ingress:preflight -- --app APP --proxy PROXY --network PRIVATE_NETWORK --expected-peer FIXED_IP\n");
  process.exitCode=2;
}else{
  try{
    const app=values.get("--app")!,proxy=values.get("--proxy")!;
    const appSnapshot=container(app);
    const proxySnapshot=container(proxy);
    if(appSnapshot.Name!=="/"+app&&appSnapshot.Name!==app)
      throw new Error("INVENTORY_IDENTITY_MISMATCH");
    if(proxySnapshot.Name!=="/"+proxy&&proxySnapshot.Name!==proxy)
      throw new Error("INVENTORY_IDENTITY_MISMATCH");
    const networkNames=[...new Set(Object.keys(appSnapshot.NetworkSettings.Networks)
      .concat(values.get("--network")!))];
    const networks=networkNames.map(network);
    const result=inspectIngressTopology({
      app:appSnapshot,proxy:proxySnapshot,networks,
      privateNetwork:values.get("--network")!,
      expectedProxyIp:values.get("--expected-peer")!
    });
    process.stdout.write(JSON.stringify(result)+"\n");
    if(result.verdict!=="PREREQUISITES_MET")process.exitCode=1;
  }catch{
    // No Docker error/command/config/network dumps or secret exposure.
    process.stderr.write("Ingress topology inspection unavailable; release gate BLOCKED\n");
    process.exitCode=1;
  }
}
