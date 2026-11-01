import assert from "node:assert/strict";
import {generateKeyPairSync,randomUUID,sign} from "node:crypto";
import {execFileSync} from "node:child_process";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {createServer,request as httpsRequest,type Server} from "node:https";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import path from "node:path";
import {test} from "node:test";
import type {PreparedOwnerSummary} from "../src/connector-ws.js";
import {
  createSignedOwnerIntentDelivery,createVerifiedOwnerIntentIntake
} from "../src/owner-read-intent-transfer.js";
const cloud="https://cloud.example.test";
const intent=():PreparedOwnerSummary=>Object.freeze({
  requestId:randomUUID(),ownerSub:"trusted-owner",
  clientId:"approved-oauth-client",deviceId:randomUUID(),
  projectId:randomUUID(),origin:cloud,operation:"project_summary",
  expiresAtUnixMs:Date.now()+25_000
});
function packet(requestId:string,signature:string,scope:PreparedOwnerSummary){
  return JSON.stringify({version:1,intent:{
    requestId,ownerSub:scope.ownerSub,clientId:scope.clientId,
    deviceId:scope.deviceId,projectId:scope.projectId,origin:scope.origin,
    expiresAtUnixMs:scope.expiresAtUnixMs
  },signature});
}
function post(
  port:number,ca:Buffer,body:string,
  options:{origin?:string;cookie?:string;authorization?:string}={}
):Promise<number>{
  return new Promise((resolve,reject)=>{
    const request=httpsRequest({
      hostname:"127.0.0.1",servername:"localhost",port,ca,
      path:"/internal/owner-read/intent",method:"POST",
      headers:{Host:"localhost:"+port,"Content-Type":"application/json",
        ...(options.origin?{Origin:options.origin}:{}),
        ...(options.cookie?{Cookie:options.cookie}:{}),
        ...(options.authorization?{Authorization:options.authorization}:{})
      },timeout:5_000
    },response=>{
      response.resume();
      response.on("end",()=>resolve(response.statusCode??0));
      response.on("error",reject);
    });
    request.on("error",reject);
    request.end(body);
  });
}
test("Cloud Ed25519 intent transfer is HTTPS-only, authenticated, exact and one-shot",
  {timeout:50_000},async()=>{
    const dir=await mkdtemp(path.join(tmpdir(),"cloud-owner-transfer-"));
    const {publicKey,privateKey}=generateKeyPairSync("ed25519");
    const signingKey=privateKey.export({format:"pem",type:"pkcs8"}).toString();
    const verifyKey=publicKey.export({format:"pem",type:"spki"}).toString();
    const wrong=generateKeyPairSync("ed25519").privateKey.export({
      format:"pem",type:"pkcs8"
    }).toString();
    const certPath=path.join(dir,"cert.pem");
    const keyPath=path.join(dir,"key.pem");
    let server:Server|undefined;
    try{
      execFileSync("openssl",[
        "req","-x509","-newkey","rsa:2048","-sha256","-nodes",
        "-days","1","-keyout",keyPath,"-out",certPath,
        "-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost"
      ],{stdio:"ignore"});
      let intake:ReturnType<typeof createVerifiedOwnerIntentIntake>|undefined;
      let slowResponse=false;
      let slowResponseClosed=false;
      server=createServer({
        key:await readFile(keyPath),cert:await readFile(certPath)
      },(req,res)=>{
        if(slowResponse){
          req.resume();
          res.writeHead(200,{"Content-Type":"text/plain"});
          res.write("processing");
          const drip=setInterval(()=>{if(!res.destroyed)res.write(".");},250);
          const end=setTimeout(()=>{if(!res.destroyed)res.end();},5_500);
          res.on("close",()=>{
            clearInterval(drip);clearTimeout(end);slowResponseClosed=true;
          });
          return;
        }
        void (intake?.(req,res)??Promise.reject(Error("No trusted intake"))).catch(()=>{
          if(!res.headersSent)res.writeHead(403);
          res.end();
        });
      });
      await new Promise<void>(r=>server!.listen(0,"::",r));
      const address=server.address() as AddressInfo;
      const origin="https://localhost:"+address.port;
      const accepted=new Map<string,PreparedOwnerSummary>();
      let issuerCredentialLookups=0;
      intake=createVerifiedOwnerIntentIntake(
        origin,cloud,verifyKey,async ownerSub=>{
          issuerCredentialLookups++;
          return ownerSub==="trusted-owner"?"active-owned-credential":null;
        },{
          addTrustedIntent:(signedScope,credentialId)=>{
            if(credentialId!=="active-owned-credential"||
               accepted.has(signedScope.requestId))return false;
            accepted.set(signedScope.requestId,{
              ...signedScope,operation:"project_summary"
            });
            return true;
          }
        }
      );
      const cert=await readFile(certPath);
      const deliver=createSignedOwnerIntentDelivery(origin,cloud,signingKey,cert);
      const first=intent();
      const link=await deliver(first);
      assert.equal(link,
        origin+"/owner-read/review?requestId="+first.requestId);
      assert.deepEqual(accepted.get(first.requestId),first);
      assert.equal(issuerCredentialLookups,1);
      assert.equal(await deliver(first),null,"A signed scope cannot replay");
      assert.equal(issuerCredentialLookups,1,
        "Replay must be denied before any database credential lookup");
      assert.equal((await post(address.port,cert,
        packet(randomUUID(),"A".repeat(86),first))),403,
        "A forged signature cannot import owner approval scope");
      assert.equal((await post(address.port,cert,
        JSON.stringify({version:1,intent:first}))),403,
        "Unsigned client-supplied scope is not trusted");
      assert.equal((await post(address.port,cert,
        packet(randomUUID(),"A".repeat(86),first),{
          authorization:"Bearer stolen-oauth-access-token"
        })),403,"OAuth bearer alone cannot access the internal intake");
      assert.equal((await post(address.port,cert,
        packet(randomUUID(),"A".repeat(86),first),{
          cookie:"__Secure-better-auth.session_token=forged"
        })),403,"Browser session cookies cannot authenticate Cloud");
      assert.equal((await post(address.port,cert,
        packet(randomUUID(),"A".repeat(86),first),{
          origin:"https://evil.example.test"
        })),403);
      assert.equal(issuerCredentialLookups,1,
        "Untrusted requests never reach independent credential selection");
      const second=intent();
      const wrongSender=createSignedOwnerIntentDelivery(origin,cloud,wrong,cert);
      assert.equal(await wrongSender(second),null);
      assert.equal(accepted.has(second.requestId),false);
      const independentlySigned=intent();
      const canonical=Buffer.from(JSON.stringify([
        "kicad-owner-read-intent-v1",
        independentlySigned.requestId,independentlySigned.ownerSub,
        independentlySigned.clientId,independentlySigned.deviceId,
        independentlySigned.projectId,independentlySigned.origin,
        "project_summary",independentlySigned.expiresAtUnixMs
      ]));
      const signature=sign(null,canonical,privateKey).toString("base64url");
      assert.equal(await post(address.port,cert,packet(
        independentlySigned.requestId,signature,{
          ...independentlySigned,clientId:"tampered-client"
        })),403,"A valid signature cannot be reassigned to another OAuth client");
      assert.equal(await post(address.port,cert,packet(
        independentlySigned.requestId,signature,{
          ...independentlySigned,deviceId:randomUUID()
        })),403,"A signature for one device is not valid for another");
      assert.equal(await post(address.port,cert,packet(
        independentlySigned.requestId,signature,independentlySigned)),204,
        "Unmodified exact trusted request is accepted only once");
      assert.equal(await post(address.port,cert,packet(
        independentlySigned.requestId,signature,independentlySigned)),403);
      assert.equal(accepted.get(independentlySigned.requestId)?.clientId,
        independentlySigned.clientId);
      assert.equal(await deliver({...intent(),origin:"https://evil.example.test"}),
        null,"Signer must refuse an unrelated Cloud origin");
      assert.equal(await deliver({...intent(),expiresAtUnixMs:Date.now()-10}),
        null,"Expired preparations never reach authority");
      assert.equal(await deliver({...intent(),expiresAtUnixMs:Date.now()+90_000}),
        null,"Unbounded approval periods are rejected");
      const third=intent();
      const duplicate=await Promise.all([
        deliver(third),deliver(third),deliver(third)
      ]);
      assert.equal(duplicate.filter(Boolean).length,1,
        "Concurrent signed delivery cannot register multiple review intents");
      assert.equal(accepted.size,3);
      // A peer can drip response bytes faster than an idle socket timeout.
      // Issuance must still fail closed within a fixed overall deadline.
      slowResponse=true;
      const started=Date.now();
      assert.equal(await deliver(intent()),null);
      assert.ok(Date.now()-started<4_500,
        "Slow-drip owner authority must not hold Cloud prepare indefinitely");
      for(let i=0;i<20&&!slowResponseClosed;i++){
        await new Promise(resolve=>setTimeout(resolve,25));
      }
      assert.equal(slowResponseClosed,true,
        "Expired transfer must close the stalled HTTPS response");
      slowResponse=false;
      assert.throws(()=>createSignedOwnerIntentDelivery(
        "http://localhost",cloud,signingKey,cert),/HTTPS/);
      assert.throws(()=>createVerifiedOwnerIntentIntake(
        origin,cloud,signingKey,async()=>null,{addTrustedIntent:()=>false}
      ),/Ed25519|key/i,"Issuer accepts only a public verification key");
      assert.throws(()=>createSignedOwnerIntentDelivery(
        origin,cloud,"not-a-private-key",cert));
    }finally{
      if(server)await new Promise<void>(resolve=>server!.close(()=>resolve()));
      await rm(dir,{recursive:true,force:true});
    }
  });
