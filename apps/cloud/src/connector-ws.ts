import {type IncomingMessage, type Server} from "node:http";
import {randomUUID} from "node:crypto";
import {performance} from "node:perf_hooks";
import type {TrustedOAuthReadIdentity} from "./connector-read-gate.js";
import type {Socket} from "node:net";
import {WebSocket,WebSocketServer} from "ws";
import {z} from "zod";
import {BoundConnectorConnections} from "./connector-transport-binding.js";
import type {PgDeviceHandshakes} from "./device-handshake.js";
import type {RequestSourceResolver} from "./trusted-ingress.js";

export type DeviceProofPort=Pick<PgDeviceHandshakes,"issue"|"verify"|"cancel">;
/**
 * High-assurance mode: a separately verified owner approval must be consumed.
 * The explicit presence-only local pilot is lower assurance; it relies on
 * an existing owner-granted OAuth project scope and a manually started local
 * one-shot device session. Neither mode authorizes commands or file contents.
 */
export type OwnerReadConsentPort={
  consume:(scope:Readonly<{
    oauth:TrustedOAuthReadIdentity;deviceId:string;projectId:string;
    requestId:string;origin:string;operation:"project_summary";expiresAtUnixMs:number;
  }>)=>Promise<boolean>;
};
export type PreparedOwnerSummary=Readonly<{
  requestId:string;ownerSub:string;clientId:string;deviceId:string;
  projectId:string;origin:string;operation:"project_summary";
  expiresAtUnixMs:number;
}>;
export type PreparedOwnerDrc=Omit<PreparedOwnerSummary,"operation">&{
  operation:"run_drc";
};
type PreparedRead=PreparedOwnerSummary|PreparedOwnerDrc;
type ReadOperation="project_summary"|"run_drc";
type State="new"|"device_challenge"|"session_challenge"|"ready"|"closed";
export type SummaryReadResult={
  kind:"connector.local_read_preview";version:1;requestId:string;
  projectId:string;operation:"project_summary";
  files:{projectPresent:boolean;boardPresent:boolean;schematicPresent:boolean};
};
export type DrcReadResult={
  kind:"connector.local_drc_preview";version:1;requestId:string;
  projectId:string;operation:"run_drc";
  counts:{violations:number;unconnectedItems:number};
};
type ReadResult=SummaryReadResult|DrcReadResult;
type PendingRead={requestId:string;projectId:string;operation:ReadOperation;
  deadline:number;monotonicDeadline:number;
  resolve:(value:ReadResult|null)=>void;timer:NodeJS.Timeout};
type Entry={
  phase:State; owner:string; device:string; challenge:string; nonce:string;
  queued:number; pending:Promise<void>; timer:NodeJS.Timeout | null;
  lastPong:number; sessionDeadline?:number; readSent?:boolean;
  awaiting?:PendingRead; validating?:PendingRead;
};
const hello=z.strictObject({
  kind:z.literal("device.hello"),version:z.literal(1),
  ownerSub:z.string().min(1).max(256),deviceId:z.uuid()
});
const proof=z.strictObject({kind:z.literal("device.proof"),version:z.literal(1),
  signature:z.string().regex(/^[A-Za-z0-9_-]{86}$/)});
const sessionProof=z.strictObject({kind:z.literal("connector.session_proof"),version:z.literal(1),
  signature:z.string().regex(/^[A-Za-z0-9_-]{86}$/)});
const readResult=z.strictObject({
  kind:z.literal("connector.read_result"),version:z.literal(1),
  sequence:z.literal(1),result:z.discriminatedUnion("operation",[
    z.strictObject({
      kind:z.literal("connector.local_read_preview"),version:z.literal(1),
      requestId:z.uuid(),projectId:z.uuid(),operation:z.literal("project_summary"),
      files:z.strictObject({projectPresent:z.boolean(),boardPresent:z.boolean(),
        schematicPresent:z.boolean()})
    }),
    z.strictObject({
      kind:z.literal("connector.local_drc_preview"),version:z.literal(1),
      requestId:z.uuid(),projectId:z.uuid(),operation:z.literal("run_drc"),
      counts:z.strictObject({
        violations:z.number().int().nonnegative().max(1000000),
        unconnectedItems:z.number().int().nonnegative().max(1000000)
      })
    })
  ])
});
const CLOSE_POLICY=1008;
const MAX_SOCKETS=96;
const MAX_PER_IP=6;
const MAX_PER_MINUTE=12;
const MINUTE=60_000;
const INITIAL_TIMEOUT=15_000;
const PROOF_TIMEOUT=60_000;
const MAX_SESSION=300_000;

function decodeSignature(raw:string):Buffer|null{
  const bytes=Buffer.from(raw,"base64url");
  return bytes.length===64&&bytes.toString("base64url")===raw?bytes:null;
}
function denyUpgrade(socket:Socket,status=403):void{
  if(socket.destroyed)return;
  socket.end("HTTP/1.1 "+status+" Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
}
function isAllowedUpgrade(req:IncomingMessage,origin:string):boolean{
  const expected=new URL(origin);
  return req.method==="GET"&&req.url==="/api/v1/connector/ws"&&
    req.headers.host===expected.host&&
    // No browser-initiated WebSockets, cookies, bearer tokens or claimed protocol.
    req.headers.origin===undefined&&req.headers.cookie===undefined&&
    req.headers.authorization===undefined&&
    req.headers["sec-websocket-protocol"]===undefined&&
    req.headers["sec-websocket-extensions"]===undefined;
}
function asJson(raw:Buffer):unknown{
  try{return JSON.parse(raw.toString("utf8")) as unknown;}catch{return null;}
}
/**
 * Live WebSocket transport for an outbound device-initiated connection.
 * Feature gated OFF by default. Native read-only DRC counts require a second
 * explicit one-shot operator flag; no arbitrary command or file-data relay.
 * TLS termination MUST be enforced by a trusted ingress before activation
 * in production; the upgrade route itself is HTTP on the internal listener.
 */
export function attachConnectorWebSocket(
  httpServer:Server,
  options:{
    publicOrigin:string;
    proofs:DeviceProofPort;
    connections:BoundConnectorConnections;
    /** No production owner-consent verifier has been provisioned. Fail closed. */
    ownerConsent?:OwnerReadConsentPort;
    /**
     * Explicit no-customer metadata pilot: the owner already granted the
     * OAuth client/project in Cloud and manually started a one-shot device
     * process. No independent WebAuthn ceremony is asserted by this mode.
     * A separate, default-off flag is required before a single native DRC
     * counts-only operation can be requested. No general commands or paths.
     */
    operatorLocalOnce?:boolean;
    // Separate opt-in flag for foreground owner-operated native DRC counts.
    // Without this flag even the local one-shot pilot cannot run KiCad.
    operatorNativeDrcOnce?:boolean;
    maxConnections?:number;
    sourceOf:RequestSourceResolver;
  }
):{close:()=>Promise<void>;
  prepareOwnerSummary:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerSummary|null;
  requestSummary:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared?:PreparedOwnerSummary)=>Promise<SummaryReadResult|null>;
  prepareOwnerDrc:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerDrc|null;
  requestDrc:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared?:PreparedOwnerDrc)=>Promise<DrcReadResult|null>}{
  // Never let a lightweight pilot setting downgrade an independent owner
  // approval dependency, even when used outside the production entrypoint.
  if(options.operatorLocalOnce&&options.ownerConsent)
    throw Error("Conflicting owner approval modes");
  if(options.operatorNativeDrcOnce&&!options.operatorLocalOnce)
    throw Error("Native DRC pilot requires explicit local one-shot mode");
  const wss=new WebSocketServer({noServer:true,perMessageDeflate:false,
    maxPayload:1024,clientTracking:true});
  const sockets=new Set<WebSocket>();
  const readyDevices=new Map<string,{socket:WebSocket,entry:Entry}>();
  const socketKey=(owner:string,device:string)=>JSON.stringify([owner,device]);
  const ipOpen=new Map<string,number>();
  const ipWindows=new Map<string,{start:number,count:number}>();
  // Per-device throttle limits challenge reservation from self-claimed IDs.
  // Distributed DoS limits are still required before feature activation.
  const deviceWindows=new Map<string,{start:number,count:number}>();
  const preparedIntents=new WeakMap<PreparedRead,{
    socket:WebSocket;scope:string;deadline:number;
  }>();
  const reservedSockets=new WeakMap<WebSocket,PreparedRead>();
  let stopped=false;
  const waitingOAuth=new WeakMap<PendingRead,TrustedOAuthReadIdentity>();

  function allowWindow(buckets:Map<string,{start:number,count:number}>,
    id:string,max:number):boolean{
    const now=performance.now();
    const prior=buckets.get(id);
    if(!prior||now-prior.start>=MINUTE){
      buckets.set(id,{start:now,count:1});return true;
    }
    if(prior.count>=max)return false;
    prior.count++;return true;
  }
  function reject(ws:WebSocket):void{
    if(ws.readyState===WebSocket.OPEN)ws.close(CLOSE_POLICY,"policy");
    else ws.terminate();
  }
  const upgrade=(req:IncomingMessage,socket:Socket,head:Buffer):void=>{
    const ip=options.sourceOf(req);
    if(stopped||!ip||!isAllowedUpgrade(req,options.publicOrigin)){
      denyUpgrade(socket);return;
    }
    if(sockets.size>=(options.maxConnections??MAX_SOCKETS)||
       (ipOpen.get(ip)??0)>=MAX_PER_IP||
       !allowWindow(ipWindows,ip,MAX_PER_MINUTE)){
      denyUpgrade(socket,429);return;
    }
    try{
      wss.handleUpgrade(req,socket,head,ws=>{
        sockets.add(ws);
        ipOpen.set(ip,(ipOpen.get(ip)??0)+1);
        const entry:Entry={phase:"new",owner:"",device:"",challenge:"",
          nonce:"",queued:0,pending:Promise.resolve(),timer:null,lastPong:Date.now()};
        function expire(ms:number):void{
          if(entry.timer)clearTimeout(entry.timer);
          entry.timer=setTimeout(()=>{entry.phase="closed";reject(ws);},ms);
          entry.timer.unref();
        }
        function closed():boolean{return entry.phase==="closed";}
        function fail():void{
          entry.phase="closed";
          if(entry.awaiting){
            clearTimeout(entry.awaiting.timer);
            entry.awaiting.resolve(null);
            entry.awaiting=undefined;
          }
          if(entry.validating){
            clearTimeout(entry.validating.timer);
            entry.validating.resolve(null);
            entry.validating=undefined;
          }
          reject(ws);
        }
        function send(msg:object):void{
          if(ws.readyState!==WebSocket.OPEN)throw Error("socket_closed");
          ws.send(JSON.stringify(msg));
        }
        async function cancelChallenge():Promise<void>{
          if(entry.challenge){
            const id=entry.challenge;
            entry.challenge="";
            await options.proofs.cancel(entry.owner,entry.device,id);
          }
        }
        async function frame(payload:Buffer,isBinary:boolean):Promise<void>{
          if(entry.phase==="closed"||isBinary||payload.length===0||payload.length>1024){
            fail();return;
          }
          const raw=asJson(payload);
          if(entry.phase==="new"){
            const parsed=hello.safeParse(raw);
            if(!parsed.success ||
               !allowWindow(deviceWindows,parsed.data.ownerSub+":"+parsed.data.deviceId,5)){
              fail();return;
            }
            entry.owner=parsed.data.ownerSub;entry.device=parsed.data.deviceId;
            const issue=await options.proofs.issue(entry.owner,entry.device);
            if(issue.kind!=="issued"){fail();return;}
            entry.challenge=issue.challengeId;entry.nonce=issue.nonce;
            if(ws.readyState!==WebSocket.OPEN||closed()){
              await cancelChallenge();return;
            }
            entry.phase="device_challenge";
            expire(Math.min(PROOF_TIMEOUT,Math.max(1,issue.expiresAtMs-Date.now())));
            send({kind:"device.challenge",version:1,challengeId:issue.challengeId,
              deviceId:issue.deviceId,nonce:issue.nonce,expiresAtMs:issue.expiresAtMs});
            return;
          }
          if(entry.phase==="device_challenge"){
            const parsed=proof.safeParse(raw);
            const signature=parsed.success?decodeSignature(parsed.data.signature):null;
            if(!signature){fail();return;}
            const verified=await options.proofs.verify(entry.owner,entry.device,
              entry.challenge,entry.nonce,signature);
            if(verified.kind!=="verified"){fail();return;}
            entry.challenge="";entry.nonce="";
            if(ws.readyState!==WebSocket.OPEN||closed())return;
            const session=await options.connections.begin(ws,{
              ownerSub:entry.owner,deviceId:verified.deviceId});
            if(session.kind!=="issued"){fail();return;}
            if(ws.readyState!==WebSocket.OPEN||closed()){
              await options.connections.disconnect(ws);return;
            }
            entry.phase="session_challenge";
            entry.sessionDeadline=performance.now()+MAX_SESSION;
            expire(Math.min(PROOF_TIMEOUT,Math.max(1,session.expiresAtMs-Date.now())));
            send({kind:"connector.session_challenge",version:1,
              sessionId:session.sessionId,challengeId:session.challengeId,
              deviceId:verified.deviceId,nonce:session.nonce,binding:session.binding,
              expiresAtMs:session.expiresAtMs});
            return;
          }
          if(entry.phase==="session_challenge"){
            const parsed=sessionProof.safeParse(raw);
            const signature=parsed.success?decodeSignature(parsed.data.signature):null;
            if(!signature||!await options.connections.activate(ws,signature)){
              fail();return;
            }
            if(closed()||ws.readyState!==WebSocket.OPEN)return;
            entry.phase="ready";
            expire(Math.max(1,(entry.sessionDeadline??0)-performance.now()));
            send({kind:"connector.ready",version:1});
            readyDevices.set(socketKey(entry.owner,entry.device),{socket:ws,entry});
            return;
          }
          // A result is meaningful only if this same authenticated socket
          // has an outstanding, pre-authorized server-originated request.
          if(entry.phase==="ready"&&entry.awaiting){
            const pending=entry.awaiting;
            entry.awaiting=undefined;
            entry.validating=pending;
            // Do not cancel the 12s request watchdog while the final
            // database grant check is still awaiting a response. Otherwise
            // a stalled query can hold the HTTP relay promise indefinitely.
            const decoded=readResult.safeParse(raw);
            if(!decoded.success||Date.now()>=pending.deadline||
               performance.now()>=pending.monotonicDeadline||
               decoded.data.result.requestId!==pending.requestId||
               decoded.data.result.projectId!==pending.projectId||
               decoded.data.result.operation!==pending.operation){
              entry.validating=undefined;
              clearTimeout(pending.timer);
              pending.resolve(null);fail();return;
            }
            // Revocation between request and result must discard the answer.
            // The OAuth authority is bound in the pending closure below.
            const allowed=await options.connections.authorizeOutgoingSummary(
              ws,waitingOAuth.get(pending)!,pending.projectId);
            entry.validating=undefined;
            clearTimeout(pending.timer);
            // The database grant check is asynchronous. Neither its start
            // time nor a previously valid socket extends the signed request
            // deadline or the device session lease.
            if(!allowed||closed()||ws.readyState!==WebSocket.OPEN||
               Date.now()>=pending.deadline||
               performance.now()>=pending.monotonicDeadline||
               performance.now()>=(entry.sessionDeadline??0)){
              pending.resolve(null);fail();return;
            }
            send({kind:"connector.read_ack",version:1,sequence:1,
              requestId:pending.requestId});
            pending.resolve(decoded.data.result);
            ws.close(1000,"read_completed");
            return;
          }
          // No native operation, unsolicited result, or arbitrary frame.
          fail();
        }
        expire(INITIAL_TIMEOUT);
        ws.on("pong",()=>{entry.lastPong=Date.now();});
        ws.on("message",(data,isBinary)=>{
          if(closed()){fail();return;}
          entry.queued++;
          if(entry.queued>4){fail();return;}
          const bytes=Buffer.isBuffer(data)?data:Buffer.from(data as ArrayBuffer);
          entry.pending=entry.pending.then(()=>frame(bytes,isBinary))
            .catch(()=>{fail();}).finally(()=>{entry.queued--;});
        });
        ws.on("close",()=>{
          entry.phase="closed";
          if(entry.timer)clearTimeout(entry.timer);
          sockets.delete(ws);
          const key=socketKey(entry.owner,entry.device);
          if(readyDevices.get(key)?.socket===ws)readyDevices.delete(key);
          if(entry.awaiting){
            clearTimeout(entry.awaiting.timer);
            entry.awaiting.resolve(null);
            entry.awaiting=undefined;
          }
          if(entry.validating){
            clearTimeout(entry.validating.timer);
            entry.validating.resolve(null);
            entry.validating=undefined;
          }
          const count=(ipOpen.get(ip)??1)-1;
          if(count<=0)ipOpen.delete(ip);else ipOpen.set(ip,count);
          void Promise.allSettled([
            cancelChallenge(),
            options.connections.disconnect(ws)
          ]);
        });
        ws.on("error",()=>{fail();});
      });
    }catch{denyUpgrade(socket);}
  };
  httpServer.on("upgrade",upgrade);
  const heartbeat=setInterval(()=>{
    const now=performance.now();
    for(const ws of sockets){
      // ping/pong checks transport liveness, NOT extension of DB lease.
      const e=(ws as WebSocket & {isAlive?:boolean});
      if(e.isAlive===false){reject(ws);continue;}
      e.isAlive=false;
      ws.once("pong",()=>{e.isAlive=true;});
      if(ws.readyState===WebSocket.OPEN)ws.ping();
    }
    if(ipWindows.size>1024)for(const [ip,b] of ipWindows)
      if(now-b.start>=MINUTE)ipWindows.delete(ip);
    if(deviceWindows.size>1024)for(const [id,b] of deviceWindows)
      if(now-b.start>=MINUTE)deviceWindows.delete(id);
  },30_000);
  heartbeat.unref();
  /**
   * Prepare the exact owner-facing intent BEFORE a browser WebAuthn ceremony.
   * Server-side only: no Cloud HTTP route and no bearer-token semantics.
   */
  function prepareRead(oauth:TrustedOAuthReadIdentity,
    deviceId:string,projectId:string,operation:ReadOperation):PreparedRead|null{
    if(operation==="run_drc"&&!(options.operatorLocalOnce&&options.operatorNativeDrcOnce))
      return null;
    if(stopped||(!options.ownerConsent&&!options.operatorLocalOnce)||!oauth||
       typeof oauth.ownerSub!=="string"||!oauth.ownerSub||
       typeof oauth.clientId!=="string"||!oauth.clientId||
       !/^[0-9a-f-]{36}$/i.test(deviceId)||
       !/^[0-9a-f-]{36}$/i.test(projectId))return null;
    const active=readyDevices.get(socketKey(oauth.ownerSub,deviceId));
    if(!active||active.entry.phase!=="ready"||active.entry.readSent||
       active.entry.awaiting||active.socket.readyState!==WebSocket.OPEN||
       (active.entry.sessionDeadline??0)-performance.now()<40_000||
       reservedSockets.has(active.socket))return null;
    const intent=Object.freeze({
      requestId:randomUUID(),ownerSub:oauth.ownerSub,clientId:oauth.clientId,
      deviceId,projectId,origin:options.publicOrigin,
      operation,expiresAtUnixMs:Date.now()+30_000
    }) as PreparedRead;
    preparedIntents.set(intent,{
      socket:active.socket,
      scope:JSON.stringify([oauth.ownerSub,oauth.clientId,deviceId,projectId]),
      deadline:performance.now()+30_000
    });
    reservedSockets.set(active.socket,intent);
    const timeout=setTimeout(()=>{
      if(reservedSockets.get(active.socket)===intent)
        reservedSockets.delete(active.socket);
    },30_000);
    timeout.unref();
    return intent;
  }

  function prepareOwnerSummary(oauth:TrustedOAuthReadIdentity,
    deviceId:string,projectId:string):PreparedOwnerSummary|null{
    return prepareRead(oauth,deviceId,projectId,"project_summary") as PreparedOwnerSummary|null;
  }
  function prepareOwnerDrc(oauth:TrustedOAuthReadIdentity,
    deviceId:string,projectId:string):PreparedOwnerDrc|null{
    return prepareRead(oauth,deviceId,projectId,"run_drc") as PreparedOwnerDrc|null;
  }

  async function requestRead(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedRead|undefined,
    operation:ReadOperation):Promise<ReadResult|null>{
    if(operation==="run_drc"&&!(options.operatorLocalOnce&&options.operatorNativeDrcOnce))
      return null;
    if(stopped||(!options.ownerConsent&&!options.operatorLocalOnce)||!oauth||typeof oauth.ownerSub!=="string"||
      !/^[0-9a-f-]{36}$/i.test(deviceId)||
      !/^[0-9a-f-]{36}$/i.test(projectId))return null;
    const active=readyDevices.get(socketKey(oauth.ownerSub,deviceId));
    if(!active)return null;
    const {socket,entry}=active;
    // Never dispatch using the old direct-consent shortcut.
    if(!prepared||typeof prepared!=="object")return null;
    const reserved=preparedIntents.get(prepared);
    if(!reserved)return null;
    // A prepared consent identity can be presented only once, even if
    // its object was paired with a different OAuth client or device.
    preparedIntents.delete(prepared);
    if(reservedSockets.get(reserved.socket)===prepared)
      reservedSockets.delete(reserved.socket);
    if(reserved.socket!==socket||
       reserved.scope!==JSON.stringify([
         oauth.ownerSub,oauth.clientId,deviceId,projectId
       ])||
       prepared.ownerSub!==oauth.ownerSub||
       prepared.clientId!==oauth.clientId||
       prepared.deviceId!==deviceId||prepared.projectId!==projectId||
       prepared.origin!==options.publicOrigin||
       prepared.operation!==operation||
       reserved.deadline<=performance.now()||
       prepared.expiresAtUnixMs<=Date.now())return null;
    const requestId=prepared.requestId;
    const ownerExpiresAtUnixMs=prepared.expiresAtUnixMs;
    const ownerExpiresAtMonotonic=reserved.deadline;
    if(entry.phase!=="ready"||entry.readSent||entry.awaiting||
      socket.readyState!==WebSocket.OPEN||
      (entry.sessionDeadline??0)-performance.now()<10_000)return null;
    entry.readSent=true; // Reserve before any async authorization awaits.
    // A registered verifier must consume a freshly owner-authenticated,
    // one-shot assertion; OAuth and device signatures cannot replace it.
    let consentTimer:ReturnType<typeof setTimeout>|undefined;
    let consentTimedOut=false;
    let onConsentDisconnect:()=>void=()=>{};
    const consentDisconnected=new Promise<boolean>(resolve=>{
      onConsentDisconnect=()=>resolve(false);
      socket.once("close",onConsentDisconnect);
    });
    let consented:boolean;
    try{
      consented=await Promise.race([
        options.operatorLocalOnce ? Promise.resolve(true) :
          options.ownerConsent!.consume({oauth,deviceId,projectId,requestId,
            origin:options.publicOrigin,operation:"project_summary",
            expiresAtUnixMs:ownerExpiresAtUnixMs}),
        new Promise<boolean>(resolve=>{
          consentTimer=setTimeout(()=>{consentTimedOut=true;resolve(false);},8_000);
          consentTimer.unref();
        }),
        consentDisconnected
      ]).finally(()=>{
        if(consentTimer)clearTimeout(consentTimer);
        socket.off("close",onConsentDisconnect);
      });
    }catch{reject(socket);return null;}
    if(!consented||consentTimedOut||entry.phase!=="ready"||
      socket.readyState!==WebSocket.OPEN||
      performance.now()>=ownerExpiresAtMonotonic||
      Date.now()>=ownerExpiresAtUnixMs){
      reject(socket);return null;
    }
    let preflightTimer:ReturnType<typeof setTimeout>|undefined;
    let preflightTimedOut=false;
    let onDisconnect:()=>void=()=>{};
    // A stalled *initial* database grant check must not leave the HTTP
    // request pending before the 12-second read watchdog even exists.
    // A disconnected device must release that wait immediately as well.
    const disconnected=new Promise<boolean>(resolve=>{
      onDisconnect=()=>resolve(false);
      socket.once("close",onDisconnect);
    });
    let allowed:boolean;
    try{
      allowed=await Promise.race([
        options.connections.authorizeOutgoingSummary(socket,oauth,projectId),
        new Promise<boolean>(resolve=>{
          preflightTimer=setTimeout(()=>{preflightTimedOut=true;resolve(false);},8_000);
          preflightTimer.unref();
        }),
        disconnected
      ]).finally(()=>{
        if(preflightTimer)clearTimeout(preflightTimer);
        socket.off("close",onDisconnect);
      });
    }catch{
      // Database failures are authorization denial, not an open or
      // retryable remote read capability. Never leave a ready socket.
      reject(socket);return null;
    }
    if(preflightTimedOut){reject(socket);return null;}
    if(!allowed||entry.phase!=="ready"||socket.readyState!==WebSocket.OPEN||
      (entry.sessionDeadline??0)-performance.now()<10_000)return null;
    if(performance.now()>=ownerExpiresAtMonotonic||Date.now()>=ownerExpiresAtUnixMs){
      reject(socket);return null;
    }
    return new Promise<ReadResult|null>(resolve=>{
      const timer=setTimeout(()=>{
        entry.awaiting=undefined;
        entry.validating=undefined;
        resolve(null);reject(socket);
      },12_000);
      timer.unref();
      // Wall milliseconds remain in the wire frame; local authorization cannot
      // be extended by changing the host system clock.
      const deadline=Math.min(Date.now()+8_000,ownerExpiresAtUnixMs);
      const monotonicDeadline=Math.min(performance.now()+8_000,ownerExpiresAtMonotonic);
      if(deadline<=Date.now()||monotonicDeadline<=performance.now()){
        clearTimeout(timer);resolve(null);reject(socket);return;
      }
      const pending:PendingRead={requestId,projectId,operation,
        deadline,monotonicDeadline,resolve,timer};
      waitingOAuth.set(pending,oauth);
      entry.awaiting=pending;
      try{socket.send(JSON.stringify({
        kind:"connector.authorized_read",version:1,sequence:1,
        request:{kind:"connector.read_request",version:1,requestId,
          deviceId,projectId,operation,deadlineUnixMs:deadline}
      }));}catch{
        clearTimeout(timer);entry.awaiting=undefined;resolve(null);reject(socket);
      }
    });
  }

  async function requestSummary(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared?:PreparedOwnerSummary):Promise<SummaryReadResult|null>{
    const result=await requestRead(oauth,deviceId,projectId,prepared,"project_summary");
    return result?.operation==="project_summary"?result:null;
  }
  async function requestDrc(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared?:PreparedOwnerDrc):Promise<DrcReadResult|null>{
    const result=await requestRead(oauth,deviceId,projectId,prepared,"run_drc");
    return result?.operation==="run_drc"?result:null;
  }

  return {prepareOwnerSummary,requestSummary,prepareOwnerDrc,requestDrc,close:async()=>{
    if(stopped)return;
    stopped=true;
    clearInterval(heartbeat);
    httpServer.off("upgrade",upgrade);
    for(const ws of sockets)ws.terminate();
    await new Promise<void>(resolve=>wss.close(()=>resolve()));
  }};
}
