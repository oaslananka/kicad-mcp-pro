import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {createServer} from "node:http";
import {type AddressInfo} from "node:net";
import {test} from "node:test";

async function execute(env:Record<string,string>):Promise<number|null>{
  return new Promise((resolve,reject)=>{
    const child=spawn(process.execPath,["healthcheck.mjs"],{
      cwd:new URL("../",import.meta.url).pathname,
      env:{...process.env,...env},
      stdio:"ignore"
    });
    child.on("error",reject);
    child.on("close",resolve);
  });
}

test("Docker healthcheck probes loopback with configured canonical Host",async()=>{
  const seen:string[]=[];
  const server=createServer((req,res)=>{
    seen.push(req.headers.host??"");
    res.writeHead(req.headers.host==="cloud.example.test"?200:403);
    res.end();
  });
  await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const port=(server.address() as AddressInfo).port;
  try{
    assert.equal(await execute({PUBLIC_ORIGIN:"https://cloud.example.test",PORT:String(port)}),0);
    assert.deepEqual(seen,["cloud.example.test"]);
    assert.equal(await execute({PUBLIC_ORIGIN:"https://other.example.test",PORT:String(port)}),1);
  }finally{
    await new Promise<void>((resolve,reject)=>server.close(e=>e?reject(e):resolve()));
  }
});

test("Docker healthcheck rejects missing origin, invalid port and closed listener",async()=>{
  for(const [origin,port] of [
    ["","8787"],["https://cloud.example.test","invalid"],
    ["https://cloud.example.test","0"],
    ["https://cloud.example.test","65536"]
  ]){
    assert.equal(await execute({PUBLIC_ORIGIN:origin,PORT:port}),1);
  }
});
