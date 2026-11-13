import {randomBytes,timingSafeEqual} from "node:crypto";
import {makeSignature} from "better-auth/crypto";
import type {Pool} from "pg";
import type {BrowserIdentity} from "./browser.js";
import {htmlHeaders} from "./browser.js";
import {cliReturnCookie,validCliReturnId} from "./owner-cli-return.js";
import {renderPage} from "./ui-shell.js";
import type {DeviceManagementPort} from "./devices.js";
import type {GrantManagement,BrowserGrantSummary} from "./grants.js";
import type {PgUsage,UsageEvent} from "./usage.js";
import {hashToken} from "./usage.js";

const OPAQUE_CHARS="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-";
function validRequestId(value:unknown):value is string{
  return typeof value==="string"&&value.length===43&&
    [...value].every(char=>OPAQUE_CHARS.includes(char));
}
const TOKEN_PREFIX="kmpc1_";

const ALLOWED_LABEL="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ._()-";
function validLabel(label:string):boolean{
  if(label.length<1||label.length>64)return false;
  const first=label.charCodeAt(0);
  if(!((first>=48&&first<=57)||(first>=65&&first<=90)||(first>=97&&first<=122)))
    return false;
  return [...label].every(char=>ALLOWED_LABEL.includes(char));
}
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REQUEST_TTL_MS=10*60_000;
const MAX_PENDING=50;
const MAX_POLLS=240;
const TOKEN_TTL_DAYS=30;

export type DeviceConnectionLookup=(ownerSub:string,deviceId:string)=>boolean;

/** Owns command-line pairing state and issued management tokens. */
export class PgOwnerApiAccess {
  constructor(private readonly pool:Pool){}

  /** A CLI-open request starts pending and anonymous; only browser approval
   * binds an owner, and only that approval can mint one token, once. */
  async startRequest(requestId:string,label:string):Promise<boolean>{
    if(!validRequestId(requestId)||!validLabel(label))return false;
    const db=await this.pool.connect();
    try{
      await db.query("BEGIN");
      // Bound the pending backlog so anonymous traffic cannot grow it forever.
      await db.query(
        "DELETE FROM owner_api_cli_requests WHERE state='pending' "+
        "AND created_at < statement_timestamp() - interval '10 minutes'");
      const backlog=await db.query<{n:string}>(
        "SELECT count(*)::text AS n FROM owner_api_cli_requests WHERE state='pending'");
      if(Number(backlog.rows[0]?.n??"0")>=MAX_PENDING){await db.query("ROLLBACK");return false;}
      const inserted=await db.query(
        "INSERT INTO owner_api_cli_requests(request_id,label,state) VALUES($1,$2,'pending') "+
        "ON CONFLICT (request_id) DO NOTHING RETURNING request_id",[requestId,label]);
      await db.query("COMMIT");
      return inserted.rowCount===1;
    }catch(error){
      await db.query("ROLLBACK");
      throw error;
    }finally{db.release();}
  }

  async getRequest(requestId:string):Promise<{state:string;label:string}|null>{
    if(!validRequestId(requestId))return null;
    const rows=await this.pool.query<{state:string;label:string;created_at:Date;poll_count:number}>(
      "SELECT state,label,created_at,poll_count FROM owner_api_cli_requests "+
      "WHERE request_id=$1",[requestId]);
    const row=rows.rows[0];
    if(!row)return null;
    if(row.state==="pending" &&
       (Date.now()-row.created_at.getTime()>REQUEST_TTL_MS || row.poll_count>MAX_POLLS)){
      await this.pool.query(
        "UPDATE owner_api_cli_requests SET state='expired',updated_at=statement_timestamp() "+
        "WHERE request_id=$1 AND state='pending'",[requestId]);
      return {state:"expired",label:row.label};
    }
    return {state:row.state,label:row.label};
  }

  /** Owner-browser approval binds exactly one account, once, atomically. */
  async approveRequest(ownerSub:string,requestId:string):Promise<boolean>{
    if(!ownerSub||ownerSub.length>256||!validRequestId(requestId))return false;
    const rows=await this.pool.query(
      "UPDATE owner_api_cli_requests SET owner_sub=$1,state='approved',updated_at=statement_timestamp() "+
      "WHERE request_id=$2 AND state='pending' "+
      "AND created_at >= statement_timestamp() - interval '10 minutes' "+
      "RETURNING request_id",[ownerSub,requestId]);
    return rows.rowCount===1;
  }

  async countPoll(requestId:string):Promise<void>{
    await this.pool.query(
      "UPDATE owner_api_cli_requests SET poll_count=poll_count+1,updated_at=statement_timestamp() "+
      "WHERE request_id=$1 AND state='pending'",[requestId]);
  }

  /** Exactly one token is ever issued per approved request. */
  async issueToken(requestId:string):Promise<{token:string;expiresAt:Date}|null>{
    if(!validRequestId(requestId))return null;
    const db=await this.pool.connect();
    try{
      await db.query("BEGIN");
      const request=await db.query<{owner_sub:string;label:string}>(
        "SELECT owner_sub,label FROM owner_api_cli_requests WHERE request_id=$1 AND state='approved' "+
        "FOR UPDATE",[requestId]);
      const row=request.rows[0];
      if(!row||!row.owner_sub){await db.query("ROLLBACK");return null;}
      const token=TOKEN_PREFIX+randomBytes(32).toString("base64url");
      const expires=new Date(Date.now()+TOKEN_TTL_DAYS*24*3600_000);
      await db.query(
        "UPDATE owner_api_cli_requests SET state='claimed',token_hash=$1,updated_at=statement_timestamp() "+
        "WHERE request_id=$2",[hashToken(token),requestId]);
      await db.query(
        "INSERT INTO owner_api_tokens(token_hash,owner_sub,label,expires_at) VALUES($1,$2,$3,$4)",
        [hashToken(token),row.owner_sub,row.label,expires]);
      await db.query("COMMIT");
      return {token,expiresAt:expires};
    }catch(error){
      await db.query("ROLLBACK");
      throw error;
    }finally{db.release();}
  }

  async verifyToken(token:string):Promise<string|null>{
    if(!token.startsWith(TOKEN_PREFIX)||!validRequestId(token.slice(TOKEN_PREFIX.length)))
      return null;
    const rows=await this.pool.query<{owner_sub:string}>(
      "SELECT owner_sub FROM owner_api_tokens WHERE token_hash=$1 AND revoked_at IS NULL "+
      "AND expires_at > statement_timestamp()",[hashToken(token)]);
    const owner=rows.rows[0]?.owner_sub??null;
    if(owner){
      // Best-effort liveness stamp; a failed update never blocks the call.
      try{
        await this.pool.query(
          "UPDATE owner_api_tokens SET last_used_at=statement_timestamp() WHERE token_hash=$1",
          [hashToken(token)]);
      }catch{/* liveness stamping is advisory */}
    }
    return owner;
  }

  /** Revoke by plaintext token (logout); deleting local copies is CLI-side. */
  async revokeToken(token:string):Promise<boolean>{
    if(!token.startsWith(TOKEN_PREFIX))return false;
    const rows=await this.pool.query(
      "UPDATE owner_api_tokens SET revoked_at=COALESCE(revoked_at,statement_timestamp()) "+
      "WHERE token_hash=$1 AND revoked_at IS NULL RETURNING token_hash",[hashToken(token)]);
    return rows.rowCount===1;
  }

  /** Enabled, non-disabled OAuth clients that hold a projects:read consent. */
  async listClients(ownerSub:string):Promise<Array<{clientId:string;consentedAt:string}>>{
    if(!ownerSub||ownerSub.length>256)return [];
    const present=await this.pool.query<{present:string|null}>(
      "SELECT to_regclass('\"oauthConsent\"')::text AS present");
    if(!present.rows[0]?.present)return [];
    const rows=await this.pool.query<{client_id:string;consented_at:Date}>(
      'SELECT DISTINCT c."clientId" AS client_id,c."createdAt" AS consented_at '+
      'FROM "oauthConsent" c JOIN "oauthClient" o ON o."clientId"=c."clientId" '+
      'WHERE c."userId"=$1 AND c."scopes" @> $2::jsonb '+
      'AND o."disabled" IS DISTINCT FROM true '+
      "ORDER BY consented_at DESC LIMIT 100",
      [ownerSub,JSON.stringify(["projects:read"])]);
    return rows.rows.map(r=>({
      clientId:r.client_id,consentedAt:r.consented_at.toISOString()}));
  }

  /** Timestamped safe audit trail: tool-call telemetry and grant changes. */
  async activityLog(ownerSub:string,afterIso:string|null,limit=50):Promise<Array<{
    at:string;kind:"tool_call"|"grant";tool?:string;clientId:string;
    status?:string;operation?:string;projectId?:string;
  }>>{
    if(!ownerSub||ownerSub.length>256||!Number.isInteger(limit)||limit<1||limit>100)
      return [];
    let after:Date|null=null;
    if(afterIso!==null){
      if(typeof afterIso!=="string"||afterIso.length>40||Number.isNaN(Date.parse(afterIso)))
        return [];
      after=new Date(afterIso);
      if(Math.abs(Date.now()-after.getTime())>90*24*3600_000)return [];
    }
    const params:unknown[]=[ownerSub];
    const usageFilter=after?" AND occurred_at > $2 ":"";
    const auditFilter=after?" AND created_at > $2 ":"";
    if(after)params.push(after);
    const usageRows=await this.pool.query<{
      occurred_at:Date;tool:string;client_id:string;status:string;
    }>(
      "SELECT occurred_at,tool,client_id,status FROM usage_tool_calls "+
      "WHERE owner_sub=$1"+usageFilter+" ORDER BY occurred_at DESC LIMIT $"+(after?3:2),
      [...params,limit]);
    const auditRows=await this.pool.query<{
      created_at:Date;actor_client_id:string;project_id:string;operation:string;
    }>(
      "SELECT created_at,actor_client_id,project_id,operation FROM client_grant_audit "+
      "WHERE owner_sub=$1"+auditFilter+" ORDER BY created_at DESC LIMIT $"+(after?3:2),
      [...params,limit]);
    type Event={at:Date;kind:"tool_call"|"grant";tool?:string;clientId:string;
      status?:string;operation?:string;projectId?:string};
    const events:Event[]=[
      ...usageRows.rows.map(r=>({at:r.occurred_at,kind:"tool_call" as const,tool:r.tool,
        clientId:r.client_id,status:r.status})),
      ...auditRows.rows.map(r=>({at:r.created_at,kind:"grant" as const,
        clientId:r.actor_client_id,projectId:r.project_id,operation:r.operation}))
    ];
    events.sort((a,b)=>b.at.getTime()-a.at.getTime());
    return events.slice(0,limit).map(e=>({at:e.at.toISOString(),kind:e.kind,
      ...(e.tool?{tool:e.tool}:{}),clientId:e.clientId,
      ...(e.status?{status:e.status}:{}),
      ...(e.operation?{operation:e.operation}:{}),
      ...(e.projectId?{projectId:e.projectId}:{})}));
  }
}

function jsonBody(body:unknown,status=200):Response{
  return new Response(JSON.stringify(body),{status,headers:{
    "Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store",
    "X-Content-Type-Options":"nosniff"}});
}
function apiError(status:number,error:string):Response{
  return jsonBody({error},status);
}
function bearer(request:Request):string|null{
  const header=request.headers.get("authorization");
  const match=typeof header==="string"?/^Bearer ([A-Za-z0-9._~+/-]+={0,2})$/.exec(header):null;
  return match?match[1]!:null;
}
async function readJson(request:Request,maxBytes:number):Promise<Record<string,unknown>|null>{
  const raw=await request.text();
  if(raw.length>maxBytes)return null;
  let parsed:unknown;
  try{parsed=JSON.parse(raw);}catch{return null;}
  if(!parsed||typeof parsed!=="object"||Array.isArray(parsed))return null;
  return parsed as Record<string,unknown>;
}
function sanitizedLabel(value:unknown):string|null{
  if(typeof value!=="string")return null;
  const clean=value.replace(/[\u0000-\u001f\u007f]/g,"").trim();
  return validLabel(clean)?clean:null;
}

export type OwnerApiServices={
  ownerApi:PgOwnerApiAccess;
  devices?:DeviceManagementPort;
  grants?:GrantManagement;
  usage?:PgUsage;
  deviceConnection?:DeviceConnectionLookup;
};

/**
 * Unauthenticated CLI pairing endpoints plus token-authenticated owner
 * management endpoints. Browser pages are handled by cliApproveResponse.
 */
export async function ownerApiResponse(request:Request,origin:string,
  services:OwnerApiServices):Promise<Response|null>{
  const url=new URL(request.url);
  const path=url.pathname;
  const {ownerApi}=services;
  if(path==="/api/owner/cli/start"&&request.method==="POST"){
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,256);
    if(!body)return apiError(400,"invalid_request");
    if(Object.keys(body).length!==2||
       !["requestId","label"].every(key=>Object.hasOwn(body,key)))
      return apiError(400,"invalid_request");
    const {requestId,label}=body;
    if(typeof requestId!=="string"||!validRequestId(requestId))
      return apiError(400,"invalid_request");
    const safeLabel=sanitizedLabel(label);
    if(!safeLabel)return apiError(400,"invalid_request");
    let started:boolean;
    try{started=await ownerApi.startRequest(requestId,safeLabel);}
    catch{return apiError(503,"unavailable");}
    if(!started)return apiError(409,"request_conflict");
    return jsonBody({status:"pending",
      approveUrl:origin+"/api/owner/cli/approve?request_id="+encodeURIComponent(requestId)});
  }
  if(path==="/api/owner/cli/poll"&&request.method==="POST"){
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,128);
    if(!body||Object.keys(body).length!==1||typeof body.requestId!=="string"||
       !validRequestId(body.requestId))
      return apiError(400,"invalid_request");
    const requestId=body.requestId;
    let state:{state:string;label:string}|null;
    try{
      state=await ownerApi.getRequest(requestId);
      if(state?.state==="pending")await ownerApi.countPoll(requestId);
    }catch{return apiError(503,"unavailable");}
    if(!state)return apiError(404,"unknown_request");
    if(state.state==="approved"){
      let issued:{token:string;expiresAt:Date}|null;
      try{issued=await ownerApi.issueToken(requestId);}
      catch{return apiError(503,"unavailable");}
      if(issued)return jsonBody({status:"approved",token:issued.token,
        expiresAt:issued.expiresAt.toISOString()});
      // Another poll already claimed the single token for this request.
      return jsonBody({status:"claimed"});
    }
    return jsonBody({status:state.state});
  }
  // Token-authenticated management surface.
  const token=bearer(request);
  if(!token)return apiError(401,"authentication_required");
  let owner:string|null;
  try{owner=await ownerApi.verifyToken(token);}
  catch{return apiError(503,"unavailable");}
  if(!owner)return apiError(401,"invalid_token");
  const {devices,grants,usage,deviceConnection}=services;
  // Logout revokes exactly the presented management token; project, device
  // and local KiCad registrations are never touched by this endpoint.
  if(path==="/api/owner/v1/logout"&&request.method==="POST"){
    let revoked:boolean;
    try{revoked=await ownerApi.revokeToken(token);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({revoked});
  }
  if(path==="/api/owner/v1/devices"&&request.method==="GET"){
    if(!devices)return apiError(503,"unavailable");
    let rows:Awaited<ReturnType<DeviceManagementPort["list"]>>;
    try{rows=await devices.list(owner);}
    catch{return apiError(503,"unavailable");}
    const payload=[] as Array<{
      id:string;alias:string;enabled:boolean;revoked:boolean;connected:boolean;
      createdAt:string;projects:Array<{id:string;alias:string;enabled:boolean}>;
    }>;
    const projects=devices.listProjects?await devices.listProjects(owner):[];
    for(const device of rows){
      const connected=Boolean(deviceConnection?.(owner,device.id));
      payload.push({
        id:device.id,alias:device.alias,enabled:device.enabled,revoked:device.revoked,
        connected,createdAt:device.createdAt.toISOString(),
        projects:projects.filter(p=>p.deviceId===device.id)
          .map(p=>({id:p.id,alias:p.alias,enabled:p.enabled}))
      });
    }
    return jsonBody({devices:payload});
  }
  if(path==="/api/owner/v1/projects"&&request.method==="POST"){
    if(!devices?.createProject)return apiError(503,"unavailable");
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,512);
    if(!body||Object.keys(body).length!==2||
       !["deviceId","alias"].every(key=>Object.hasOwn(body,key)))
      return apiError(400,"invalid_request");
    const {deviceId,alias}=body;
    if(typeof deviceId!=="string"||!UUID.test(deviceId))return apiError(400,"invalid_request");
    if(typeof alias!=="string")return apiError(400,"invalid_request");
    let created:string|null;
    try{created=await devices.createProject(owner,deviceId,alias);}
    catch{return apiError(503,"unavailable");}
    if(!created)return apiError(404,"not_found");
    return jsonBody({id:created,alias},201);
  }
  const projectAction=/^\/api\/owner\/v1\/projects\/(rename|remove)$/.exec(path);
  if(projectAction&&request.method==="POST"){
    if(!devices)return apiError(503,"unavailable");
    const action=projectAction[1] as "rename"|"remove";
    if((action==="rename"&&!devices.renameProject)||(action==="remove"&&!devices.deleteProject))
      return apiError(503,"unavailable");
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,512);
    const expected=action==="rename"?["projectId","alias"]:["projectId"];
    if(!body||Object.keys(body).length!==expected.length||
       !expected.every(key=>Object.hasOwn(body,key)))
      return apiError(400,"invalid_request");
    if(typeof body.projectId!=="string"||!UUID.test(body.projectId))
      return apiError(400,"invalid_request");
    if(action==="rename"){
      if(typeof body.alias!=="string")return apiError(400,"invalid_request");
      let updated:boolean;
      try{updated=await devices.renameProject!(owner,body.projectId,body.alias);}
      catch{return apiError(503,"unavailable");}
      if(!updated)return apiError(404,"not_found");
      return jsonBody({updated:true});
    }
    let removed:boolean;
    try{removed=await devices.deleteProject!(owner,body.projectId);}
    catch{return apiError(503,"unavailable");}
    if(!removed)return apiError(404,"not_found");
    // Cloud record removal only; local KiCad files are never touched here.
    return jsonBody({removed:true});
  }
  if(path==="/api/owner/v1/clients"&&request.method==="GET"){
    let clients:Array<{clientId:string;consentedAt:string}>;
    try{clients=await ownerApi.listClients(owner);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({clients});
  }
  if(path==="/api/owner/v1/access"&&request.method==="GET"){
    if(!grants?.listBrowserGrants)return apiError(503,"unavailable");
    let saved:BrowserGrantSummary[];
    try{saved=await grants.listBrowserGrants(owner);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({access:saved});
  }
  if(path==="/api/owner/v1/access/set"&&request.method==="POST"){
    if(!grants?.setBrowserGrant)return apiError(503,"unavailable");
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,2048);
    if(!body||Object.keys(body).length!==3||
       !["projectId","clientId","enabled"].every(key=>Object.hasOwn(body,key)))
      return apiError(400,"invalid_request");
    const {projectId,clientId,enabled}=body;
    if(typeof projectId!=="string"||!UUID.test(projectId)||
       typeof clientId!=="string"||clientId.length<1||clientId.length>1024||
       typeof enabled!=="boolean")
      return apiError(400,"invalid_request");
    // setBrowserGrant is readonly-only by construction; no mode is accepted.
    let updated:boolean;
    try{updated=await grants.setBrowserGrant(owner,projectId,clientId,enabled);}
    catch{return apiError(503,"unavailable");}
    if(!updated)return apiError(404,"not_found");
    return jsonBody({updated:true,maxMode:"readonly"});
  }
  if(path==="/api/owner/v1/access/revoke"&&request.method==="POST"){
    if(!grants?.revokeClient)return apiError(503,"unavailable");
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/json")
      return apiError(415,"unsupported_media_type");
    const body=await readJson(request,2048);
    if(!body||Object.keys(body).length!==1||typeof body.clientId!=="string"||
       body.clientId.length<1||body.clientId.length>1024)
      return apiError(400,"invalid_request");
    let revoked:number;
    try{revoked=await grants.revokeClient(owner,body.clientId);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({revokedProjects:revoked});
  }
  if(path==="/api/owner/v1/usage"&&request.method==="GET"){
    if(!usage)return apiError(503,"unavailable");
    const days=Number(url.searchParams.get("days")??"30");
    if(!Number.isInteger(days)||days<1||days>365)return apiError(400,"invalid_request");
    let summary:Awaited<ReturnType<PgUsage["summary"]>>;
    try{summary=await usage.summary(owner,days);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({summary:summary??null});
  }
  if(path==="/api/owner/v1/logs"&&request.method==="GET"){
    if(!usage)return apiError(503,"unavailable");
    const rawAfter=url.searchParams.get("after");
    if(rawAfter!==null&&rawAfter.length>40)return apiError(400,"invalid_request");
    const limit=Number(url.searchParams.get("limit")??"50");
    if(!Number.isInteger(limit)||limit<1||limit>100)return apiError(400,"invalid_request");
    let events;
    try{events=await ownerApi.activityLog(owner,rawAfter,limit);}
    catch{return apiError(503,"unavailable");}
    return jsonBody({events});
  }
  return apiError(404,"not_found");
}

/** Signed browser CSRF, scoped to one CLI request, mirroring device forms. */
function approveCookieName(origin:string):string{
  return origin.startsWith("https://")?"__Host-kicad-cli-approve":"kicad-cli-approve";
}
function approveCookie(req:Request,origin:string):string|null{
  const name=approveCookieName(origin);
  return (req.headers.get("cookie")??"").split(";").map(x=>x.trim())
    .find(x=>x.startsWith(name+"="))?.slice(name.length+1)??null;
}
async function cliCsrf(secret:string,user:string,session:string,requestId:string,
  stamp:string,nonce:string):Promise<string>{
  const value=JSON.stringify(["cli-approve-v1",user,session,requestId,stamp,nonce]);
  return stamp+"."+nonce+"."+Buffer.from(await makeSignature(value,secret),"base64")
    .toString("base64url");
}
async function checkCliCsrf(request:Request,origin:string,secret:string,
  user:{user:string;session:string},requestId:string,sent:string):Promise<Response|null>{
  if(sent.length>250)return apiError(403,"forbidden");
  const [stamp,nonce,sig,...rest]=sent.split(".");
  if(rest.length||!/^\d{13}$/.test(stamp)||
     !/^[a-zA-Z0-9_-]{22}$/.test(nonce)||!/^[a-zA-Z0-9_-]{43}$/.test(sig))
    return apiError(403,"forbidden");
  const expected=Buffer.from(await cliCsrf(secret,user.user,user.session,requestId,
    stamp,nonce));
  const actual=Buffer.from(sent);
  if(expected.length!==actual.length||!timingSafeEqual(expected,actual))
    return apiError(403,"forbidden");
  const created=Number(stamp),now=Date.now();
  if(created>now+5000||now-created>5*60_000)return apiError(403,"forbidden");
  // Double-submit cookie: the signed form must pair with this browser's state.
  if(approveCookie(request,origin)!==stamp+"."+nonce)return apiError(403,"forbidden");
  return null;
}

/**
 * Browser-only approval page for one CLI pairing request. The signed-in owner
 * sees the requesting machine label and explicitly approves once; the CLI
 * never receives a browser session or cookies.
 */
export async function cliApproveResponse(request:Request,
  identity:BrowserIdentity,origin:string,ownerApi:PgOwnerApiAccess):Promise<Response|null>{
  const url=new URL(request.url);
  if(url.pathname!=="/api/owner/cli/approve")return null;
  if(!identity.api||!identity.$context)return apiError(503,"unavailable");
  const requestId=url.searchParams.get("request_id")??"";
  if(!validCliReturnId(requestId))return apiError(400,"invalid_request");
  const session=await identity.api.getSession({headers:request.headers});
  if(!session?.user){
    // The browser returns here after first-time social sign-in. This
    // navigation cookie cannot approve or mint a CLI token by itself.
    return new Response(null,{status:303,headers:{
      "Location":"/sign-in","Cache-Control":"no-store",
      "Set-Cookie":cliReturnCookie(origin,requestId,600)}});
  }
  let state:{state:string;label:string}|null;
  try{state=await ownerApi.getRequest(requestId);}
  catch{return apiError(503,"unavailable");}
  if(!state)return apiError(404,"unknown_request");
  const {secret}=await identity.$context;
  const owner={user:session.user.id,session:session.session.id};
  if(request.method==="GET"){
    if(state.state!=="pending"){
      return new Response(renderPage({
        title:"Command-line access",kind:"consent",
        eyebrow:"Workspace / Command-line access",
        summary:"This pairing request is no longer awaiting approval.",
        userEmail:session.user.email??undefined,
        children:(
          <section className="card detail-card" aria-label="Request state">
            <p>The command-line pairing request was already handled or expired.
              Nothing was changed.</p>
            <p>Start a new request from the computer that needs access.</p>
          </section>
        )
      }),{status:200,headers:htmlHeaders});
    }
    const stamp=String(Date.now()),nonce=randomBytes(16).toString("base64url");
    const csrf=await cliCsrf(secret,owner.user,owner.session,requestId,stamp,nonce);
    return new Response(renderPage({
      title:"Approve command-line access",kind:"consent",
      eyebrow:"Workspace / Command-line access",
      summary:"One-time approval for the KiCad MCP Pro command line on this account.",
      userEmail:session.user.email??undefined,
      children:(
        <section className="card detail-card" aria-label="Approve command-line access">
          <h2>Approve command-line access</h2>
          <p>Requesting machine: <strong>{state.label}</strong></p>
          <p>Approval lets the command line on that machine manage devices,
            projects and read-only client access for this account for 30 days.
            It never grants write access to KiCad files and never exposes
            local project paths.</p>
          <form method="post" action={"/api/owner/cli/approve?request_id="+
            encodeURIComponent(requestId)}>
            <input type="hidden" name="csrf" value={csrf}/>
            <button className="button primary" type="submit">Approve this computer</button>
          </form>
          <p><a href="/devices">Cancel and return to devices</a></p>
        </section>
      )
    }),{status:200,headers:{...htmlHeaders,
      "Set-Cookie":approveCookieName(origin)+"="+stamp+"."+nonce+"; Path=/; HttpOnly; SameSite=Strict; Max-Age=300"+
        (origin.startsWith("https://")?"; Secure":"")}});
  }
  if(request.method==="POST"){
    if(request.headers.get("origin")!==origin)return apiError(403,"forbidden");
    if(request.headers.get("content-type")?.split(";")[0]?.trim()!=="application/x-www-form-urlencoded")
      return apiError(415,"unsupported_media_type");
    const raw=await request.text();
    if(raw.length>2048)return apiError(413,"invalid_request");
    const fields=new URLSearchParams(raw);
    if([...fields.keys()].length!==1||fields.getAll("csrf").length!==1)
      return apiError(400,"invalid_request");
    const csrfIssue=await checkCliCsrf(request,origin,secret,owner,requestId,fields.get("csrf")??"");
    if(csrfIssue)return csrfIssue;
    let approved:boolean;
    try{approved=await ownerApi.approveRequest(owner.user,requestId);}
    catch{return apiError(503,"unavailable");}
    return new Response(renderPage({
      title:approved?"Command-line access approved":"Request already handled",
      kind:"notice",eyebrow:"Workspace / Command-line access",
      summary:approved?"The requesting computer can now complete pairing.":
        "The pairing request was already handled or expired. Nothing was changed.",
      userEmail:session.user.email??undefined,
      children:approved?(
        <section className="card detail-card" aria-label="Approval complete">
          <h2>Approved</h2>
          <p>Return to the terminal on <strong>{state.label}</strong>; it will
            finish pairing automatically. You can revoke command-line access at
            any time from Settings.</p>
        </section>
      ):(
        <section className="card detail-card" aria-label="Request state">
          <p>No change was made.</p>
        </section>
      )
    }),{status:200,headers:htmlHeaders});
  }
  return apiError(405,"method_not_allowed");
}
