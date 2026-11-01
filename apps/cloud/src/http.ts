import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { Config } from "./config.js";
import type { Inventory } from "./store.js";
import { createCloudMcpHandler } from "./mcp.js";
import type { Verifier } from "./auth.js";
import type { GrantManagement, AccessMode } from "./grants.js";
import type { Identity } from "./identity.js";
import { browserResponse } from "./browser.js";
import { consentResponse } from "./consent.js";
import { connectionsResponse } from "./connections.js";
import {devicesResponse,type DeviceManagementPort} from "./devices.js";
import {pairingBrowserResponse} from "./pairing-browser.js";
import type {PairingReviewPort} from "./pairing-review.js";
import {handlePairingDeviceRequest} from "./pairing-device-http.js";
import type {PairingDevicePort} from "./pairing-device-api.js";
import type {RequestSourceResolver} from "./trusted-ingress.js";
import { oauthProviderResponse } from "./oauth-error.js";
import { renderLanding } from "./browser-ui.js";
import { uiCss } from "./ui-styles.js";
import {pairingReviewClient} from "./pairing-review-client.js";
import type {TrustedOAuthReadIdentity} from "./connector-read-gate.js";
import type {PreparedOwnerSummary,SummaryReadResult,PreparedOwnerDrc,DrcReadResult,
  PreparedOwnerInspection,InspectionReadResult,
  PreparedOwnerBoardCounts,BoardCountsReadResult,
  PreparedOwnerSchematicCounts,SchematicCountsReadResult} from "./connector-ws.js";
import {OwnerSummaryHttpPreparations} from "./owner-summary-http-preparations.js";

type SummaryRelay={
  prepareOwnerSummary:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerSummary|null;
  requestSummary:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedOwnerSummary)=>Promise<SummaryReadResult|null>;
  prepareOwnerDrc?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerDrc|null;
  requestDrc?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedOwnerDrc)=>Promise<DrcReadResult|null>;
  prepareOwnerInspection?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerInspection|null;
  requestInspection?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedOwnerInspection)=>Promise<InspectionReadResult|null>;
  prepareOwnerBoardCounts?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerBoardCounts|null;
  requestBoardCounts?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedOwnerBoardCounts)=>Promise<BoardCountsReadResult|null>;
  prepareOwnerSchematicCounts?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string)=>PreparedOwnerSchematicCounts|null;
  requestSchematicCounts?:(oauth:TrustedOAuthReadIdentity,deviceId:string,
    projectId:string,prepared:PreparedOwnerSchematicCounts)=>Promise<SchematicCountsReadResult|null>;
};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const MAX_BODY = 1024 * 1024;
const noCache = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
function json(res: ServerResponse, code: number, body: object, headers: Record<string,string> = {}) {
  res.writeHead(code, { ...noCache, ...headers, "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}
function deny(res: ServerResponse, code: number, error: string) {
  json(res, code, { error });
}
function bearerChallenge(config: Config) {
  return 'Bearer resource_metadata="' + config.publicOrigin + '/.well-known/oauth-protected-resource", scope="projects:read"';
}
async function requestBody(req: IncomingMessage): Promise<Buffer> {
  let length = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    length += data.length;
    if (length > MAX_BODY) throw new Error("REQUEST_TOO_LARGE");
    chunks.push(data);
  }
  return Buffer.concat(chunks);
}
function validHost(req: IncomingMessage, publicOrigin: string): boolean {
  const expected = new URL(publicOrigin);
  const host = req.headers.host;
  if (typeof host !== "string" || host.includes(",") || host.includes("@")) return false;
  if (host === expected.host) return true;
  if (expected.hostname === "127.0.0.1") return /^127\.0\.0\.1:[0-9]{1,5}$/.test(host);
  if (expected.hostname === "localhost") return /^localhost:[0-9]{1,5}$/.test(host);
  return false;
}
function validOrigin(req: IncomingMessage, config: Config): boolean {
  const origin = req.headers.origin;
  return origin === undefined || (typeof origin === "string" &&
    (origin === config.publicOrigin || config.allowedOrigins.includes(origin)));
}

export type CloudHttpServices={
  grants?:GrantManagement;
  identity?:Pick<Identity,"handler">;
  devices?:DeviceManagementPort;
  pairings?:PairingReviewPort;
  pairingDevice?:PairingDevicePort;
  deviceSource?:RequestSourceResolver;
  summaryRelay?:()=>SummaryRelay|null;
  // Metadata-only, owner-granted + manually started local one-shot pilot.
  // Never enable this from an untrusted request or merely from WS presence.
  mcpProjectPresenceEnabled?:boolean;
  // Extra, default-OFF owner-foreground native DRC *counts only*.
  mcpProjectNativeDrcEnabled?:boolean;
  mcpProjectInspectionEnabled?:boolean;
  mcpProjectBoardCountsEnabled?:boolean;
  mcpProjectSchematicCountsEnabled?:boolean;
  // Trusted Cloud-to-owner HTTPS delivery only. If absent, /prepare
  // cannot claim success; a bearer client must never self-register scope.
  ownerIntentDelivery?:(scope:PreparedOwnerSummary)=>Promise<string|null>;
};

/** Named optional services prevent misleading positional dependency wiring. */
export function createHttpServer(
  config:Config,inventory:Inventory,verify:Verifier,services:CloudHttpServices={}
):Server{
  const preparations=new OwnerSummaryHttpPreparations();
  return createServer((req,res)=>{
    void handleRequest(req,res,config,inventory,verify,services,preparations).catch(()=>{
      if(!res.headersSent)deny(res,500,"internal_error");
      else res.end();
    });
  });
}

async function handleRequest(
  req:IncomingMessage,res:ServerResponse,config:Config,inventory:Inventory,
  verify:Verifier,services:CloudHttpServices,
  preparations:OwnerSummaryHttpPreparations
):Promise<void>{
    const {grants,identity,devices,pairings,pairingDevice,deviceSource,summaryRelay}=services;
    try {
      const path = new URL(req.url ?? "/", config.publicOrigin).pathname;
      // These GET routes only render the public sign-in form or redirect to it.
      // Navigation is safe even if an extension attaches an opaque Origin.
      // Stateful POSTs, OAuth callbacks and all other routes keep strict Origin checks.
      const publicLoginNavigation = req.method === "GET" &&
        (path === "/sign-in" || path === "/auth/start/github" || path === "/auth/start/google");
      if (!validHost(req, config.publicOrigin) ||
          (!publicLoginNavigation && !validOrigin(req, config))) {
        deny(res, 403, "origin_or_host_not_allowed");
        return;
      }
      if(pairingDevice&&await handlePairingDeviceRequest(req,res,pairingDevice,
        deviceSource??(()=>null),config.publicOrigin))return;
      if (path === "/assets/pairing-review.js" && req.method === "GET") {
        res.writeHead(200,{...noCache,"Content-Type":"text/javascript; charset=utf-8",
          "Referrer-Policy":"no-referrer"});
        res.end(pairingReviewClient);
        return;
      }
      if (path === "/assets/ui.css" && req.method === "GET") {
        res.writeHead(200,{...noCache,"Content-Type":"text/css; charset=utf-8"});
        res.end(uiCss);
        return;
      }
      if (identity && (path === "/sign-in" || path === "/account" || path === "/consent" || path === "/connections" || path === "/connections/revoke" || path === "/devices" || path === "/devices/revoke" || path === "/devices/enable" || path === "/devices/projects/create" || path === "/devices/projects/grant" || path === "/devices/pairing" || path === "/devices/pairing/review" || path.startsWith("/auth/start/"))) {
        const method=req.method??"GET";
        const headers=new Headers();
        for (const [name,value] of Object.entries(req.headers)) {
          if (typeof value==="string" && !["host","connection","content-length","transfer-encoding"].includes(name)){
            headers.set(name,value);
          }
        }
        const body=method==="GET" || method==="HEAD" ? undefined : await requestBody(req);
        const browserRequest=new Request(config.publicOrigin+(req.url??"/"),{
          method,headers,body:body?.toString("utf8")
        });
        let answer: Response | null;
        if (path==="/consent") {
          answer=await consentResponse(browserRequest,identity,config.publicOrigin,config.managementClientId);
        } else if (path==="/connections" || path==="/connections/revoke") {
          answer=await connectionsResponse(browserRequest,identity,config.publicOrigin,grants);
        } else if(path==="/devices" || path==="/devices/revoke" || path==="/devices/enable" || path==="/devices/projects/create" || path==="/devices/projects/grant"){
          answer=await devicesResponse(browserRequest,identity,config.publicOrigin,devices,Boolean(pairingDevice),grants);
        } else if(path==="/devices/pairing" || path==="/devices/pairing/review"){
          answer=await pairingBrowserResponse(browserRequest,identity,config.publicOrigin,pairings);
        } else {
          answer=await browserResponse(browserRequest,identity,config.publicOrigin);
        }
        if (answer) {
          const responseHeaders=Object.fromEntries(answer.headers);
          delete responseHeaders["set-cookie"];
          res.writeHead(answer.status,{
            ...noCache,...responseHeaders,
            ...(answer.headers.getSetCookie().length?{"Set-Cookie":answer.headers.getSetCookie()}:{})
          });
          res.end(Buffer.from(await answer.arrayBuffer()));
          return;
        }
      }
      if (path === "/health" && req.method === "GET") {
        json(res, 200, { status: "ok", mcp: "/mcp", remoteConnector: services.mcpProjectPresenceEnabled
          ? "operator_one_shot_presence" : "not_implemented",
          revision: /^[0-9a-f]{40}$/.test(process.env.APP_REVISION ?? "") ? process.env.APP_REVISION : "unknown" });
        return;
      }
      if ((path === "/.well-known/oauth-protected-resource" || path === "/.well-known/oauth-protected-resource/mcp") && req.method === "GET") {
        json(res, 200, {
          resource: config.audience,
          authorization_servers: [config.issuer],
          scopes_supported: ["projects:read"],
          bearer_methods_supported: ["header"]
        });
        return;
      }
      if (path === "/" && req.method === "GET") {
        res.writeHead(200,{...noCache,
          "Content-Type":"text/html; charset=utf-8",
          "Referrer-Policy":"no-referrer",
          "Content-Security-Policy":"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self'"
        });
        res.end(renderLanding(Boolean(identity)));
        return;
      }
      const authPath = path === "/api/auth" || path.startsWith("/api/auth/") ||
        path === "/.well-known/oauth-authorization-server" ||
        path.startsWith("/.well-known/oauth-authorization-server/") ||
        path === "/.well-known/openid-configuration" ||
        path.startsWith("/.well-known/openid-configuration/");
      if (authPath && identity) {
        const method=req.method ?? "GET";
        const headers=new Headers();
        for (const [name,value] of Object.entries(req.headers)) {
          if (typeof value === "string" && !["host","connection","transfer-encoding","content-length"].includes(name)) {
            headers.set(name,value);
          }
        }
        const payload=method==="GET" || method==="HEAD" ? undefined : await requestBody(req);
        const forwarded=new Request(config.publicOrigin + (req.url ?? "/"),{
          method,headers,body:payload?.toString("utf8")
        });
        const reply=await oauthProviderResponse(forwarded,request=>identity.handler(request));
        const outgoing=Object.fromEntries(reply.headers);
        delete outgoing["set-cookie"];
        delete outgoing["content-length"];
        const cookies=reply.headers.getSetCookie();
        res.writeHead(reply.status, {
          ...noCache, ...outgoing,
          ...(cookies.length ? {"Set-Cookie":cookies} : {})
        });
        res.end(Buffer.from(await reply.arrayBuffer()));
        return;
      }
      const grantRoute = /^\/api\/v1\/projects\/([0-9a-f-]{36})\/grants$/.exec(path);
      if (grantRoute && req.method === "PUT" && grants) {
        const header = req.headers.authorization;
        const matched = typeof header === "string" ? /^Bearer ([A-Za-z0-9._~+/-]+={0,2})$/.exec(header) : null;
        if (!matched) { deny(res, 401, "authentication_required"); return; }
        let actor;
        try { actor = await verify(matched[1]); }
        catch { deny(res, 401, "invalid_access_token"); return; }
        if (!(await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))) {
          deny(res,401,"revoked_access_token"); return;
        }
        if (!config.managementClientId || actor.clientId !== config.managementClientId || !actor.scopes.has("projects:manage")) {
          deny(res, 403, "forbidden"); return;
        }
        if (req.headers["content-type"]?.split(";")[0]?.trim() !== "application/json") {
          deny(res, 415, "unsupported_media_type"); return;
        }
        let body: unknown;
        try { body = JSON.parse((await requestBody(req)).toString("utf8")); }
        catch { deny(res, 400, "invalid_json"); return; }
        if (!body || Array.isArray(body) || typeof body !== "object") {
          deny(res, 400, "invalid_grant"); return;
        }
        const fields = body as Record<string,unknown>;
        const mode = fields.maxMode;
        const clientId = fields.clientId;
        const enabled = fields.enabled;
        if (Object.keys(fields).length !== 3 || !["clientId","enabled","maxMode"].every(key => Object.hasOwn(fields,key)) ||
            typeof clientId !== "string" || clientId.length < 1 || clientId.length > 1024 ||
            typeof enabled !== "boolean" ||
            (mode !== "readonly" && mode !== "write" && mode !== "manufacturing")) {
          deny(res, 400, "invalid_grant"); return;
        }
        try {
          const ok = await grants.setGrant(actor.sub, actor.clientId, grantRoute[1], {
            clientId, enabled, maxMode: mode as AccessMode
          });
          if (!ok) { deny(res, 404, "not_found"); return; }
          json(res, 200, {updated:true}); return;
        } catch (error) {
          if (error instanceof Error && error.message === "POLICY_EXCEEDS_PROJECT") {
            deny(res, 409, "grant_exceeds_project_policy"); return;
          }
          throw error;
        }
      }
      // The relay is absent unless connector WS is explicitly enabled. The
      // bearer JWT, revocation cutoff and project grant are enforced before
      // any server-to-device request; no browser/session cookie is accepted.
      const isSummaryPrepare=path==="/api/v1/connector/project-summary/prepare";
      if ((isSummaryPrepare||path==="/api/v1/connector/project-summary") &&
          req.method==="POST"&&summaryRelay?.()) {
        const header=req.headers.authorization;
        const matched=typeof header==="string" ?
          /^Bearer ([A-Za-z0-9._~+/-]+={0,2})$/.exec(header) : null;
        if(!matched){deny(res,401,"authentication_required");return;}
        let actor;
        try{actor=await verify(matched[1]);}
        catch{deny(res,401,"invalid_access_token");return;}
        if(!actor.sub||!actor.scopes.has("projects:read")||
          !await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt)){
          deny(res,403,"forbidden");return;
        }
        if(req.headers["content-type"]?.split(";")[0]?.trim()!=="application/json"){
          deny(res,415,"unsupported_media_type");return;
        }
        const data=await requestBody(req);
        if(data.length>512){deny(res,400,"invalid_request");return;}
        let body:unknown;
        try{body=JSON.parse(data.toString("utf8"));}
        catch{deny(res,400,"invalid_request");return;}
        if(!body||typeof body!=="object"||Array.isArray(body)){
          deny(res,400,"invalid_request");return;
        }
        const fields=body as Record<string,unknown>;
        const requiredKeys=isSummaryPrepare
          ? ["deviceId","projectId"]
          : ["deviceId","projectId","requestId"];
        if(Object.keys(fields).length!==requiredKeys.length||
          !requiredKeys.every(key=>Object.hasOwn(fields,key))||
          typeof fields.deviceId!=="string"||!UUID.test(fields.deviceId)||
          typeof fields.projectId!=="string"||!UUID.test(fields.projectId)||
          (!isSummaryPrepare&&
            (typeof fields.requestId!=="string"||!UUID.test(fields.requestId)))){
          deny(res,400,"invalid_request");return;
        }
        const relay=summaryRelay();
        if(!relay){deny(res,404,"not_available");return;}
        const oauth={
          ownerSub:actor.sub,clientId:actor.clientId,
          accessTokenIssuedAtSeconds:actor.issuedAt
        };
        if(isSummaryPrepare){
          // Never publish a request for a project not owned by this client
          // and device. Recheck token after the awaited SQL grant lookup.
          const project=await inventory.getProject(actor.sub,actor.clientId,
            fields.projectId);
          if(!project||project.deviceId!==fields.deviceId){
            deny(res,403,"forbidden");return;
          }
          try{await verify(matched[1]);}
          catch{deny(res,403,"forbidden");return;}
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt)){
            deny(res,403,"forbidden");return;
          }
          const intent=preparations.prepare(matched[1],oauth,
            fields.deviceId,fields.projectId,
            ()=>relay.prepareOwnerSummary(oauth,fields.deviceId as string,fields.projectId as string));
          if(!intent||!services.ownerIntentDelivery){
            deny(res,404,"not_available");return;
          }
          let reviewUrl:string|null;
          try{reviewUrl=await services.ownerIntentDelivery(intent);}
          catch{reviewUrl=null;}
          if(!reviewUrl||intent.expiresAtUnixMs<=Date.now()){
            deny(res,404,"not_available");return;
          }
          json(res,200,{reviewUrl,requestId:intent.requestId,
            ownerSub:intent.ownerSub,clientId:intent.clientId,
            deviceId:intent.deviceId,projectId:intent.projectId,
            operation:intent.operation,origin:intent.origin,
            expiresAtUnixMs:intent.expiresAtUnixMs});
          return;
        }
        const prepared=preparations.take(fields.requestId as string,
          matched[1],oauth,fields.deviceId,fields.projectId);
        if(!prepared){deny(res,404,"not_available");return;}
        const result=await relay.requestSummary(oauth,
          fields.deviceId,fields.projectId,prepared);
        if(!result||result.requestId!==prepared.requestId){
          deny(res,404,"not_available");return;
        }
        // Reverify JWT expiry and cutoff before returning the data, not just
        // before dispatch. A token can expire during a local read.
        try{await verify(matched[1]);}
        catch{deny(res,403,"forbidden");return;}
        if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt)){
          deny(res,403,"forbidden");return;
        }
        // Device/project grants may be revoked after the socket-side check
        // but before this HTTP response is written. Re-evaluate the current
        // owner/client grant and device binding, never only the token cutoff.
        const currentProject=await inventory.getProject(actor.sub,actor.clientId,fields.projectId);
        if(!currentProject||currentProject.deviceId!==fields.deviceId){
          deny(res,403,"forbidden");return;
        }
        // This last grant lookup is also asynchronous. The access token can
        // expire while it runs, after the prior post-relay JWT verification.
        // Do not release any project-presence bytes without a fresh token
        // check immediately before constructing the HTTP response.
        try{await verify(matched[1]);}
        catch{deny(res,403,"forbidden");return;}
        // The final project lookup also awaits PostgreSQL. A client token
        // may be revoked while that query is in flight even when its JWT
        // signature and expiration are still valid. Check the cutoff at
        // the final response authorization point as well.
        if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt)){
          deny(res,403,"forbidden");return;
        }
        json(res,200,result);return;
      }
      if (path !== "/mcp") {
        deny(res, 404, "not_found");
        return;
      }
      if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        deny(res, 405, "method_not_allowed");
        return;
      }
      const header = req.headers.authorization;
      const matched = typeof header === "string" ? /^Bearer ([A-Za-z0-9._~+/-]+={0,2})$/.exec(header) : null;
      if (!matched) {
        json(res, 401, { error: "authentication_required" }, { "WWW-Authenticate": bearerChallenge(config) });
        return;
      }
      let actor;
      try {
        actor = await verify(matched[1]);
      } catch {
        json(res, 401, { error: "invalid_access_token" }, { "WWW-Authenticate": bearerChallenge(config) });
        return;
      }
      if (!(await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))) {
        json(res,401,{error:"revoked_access_token"},{ "WWW-Authenticate":bearerChallenge(config) });
        return;
      }
      if (!actor.scopes.has("projects:read") || !actor.sub) {
        deny(res, 403, "insufficient_scope");
        return;
      }
      if (req.headers["content-type"]?.split(";")[0]?.trim() !== "application/json") {
        deny(res, 415, "unsupported_media_type");
        return;
      }
      const bytes = await requestBody(req);
      const headers = new Headers();
      for (const [name, value] of Object.entries(req.headers)) {
        if (typeof value === "string") headers.set(name, value);
      }
      // Authorization was checked above; do not forward the bearer token to the SDK.
      headers.delete("authorization");
      const request = new Request(config.publicOrigin + "/mcp", {
        method: "POST", headers, body: bytes.toString("utf8")
      });
      const presenceReader=services.mcpProjectPresenceEnabled&&summaryRelay?.()
        ? async(deviceId:string,projectId:string)=>{
          // The MCP tool never accepts paths, owner IDs or OAuth client IDs.
          // All identities come from the verified bearer and Cloud inventory.
          const project=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!project||project.deviceId!==deviceId)return null;
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          try{await verify(matched[1]);}catch{return null;}
          const relay=summaryRelay();
          if(!relay)return null;
          const oauth={ownerSub:actor.sub,clientId:actor.clientId,
            accessTokenIssuedAtSeconds:actor.issuedAt};
          const intent=relay.prepareOwnerSummary(oauth,deviceId,projectId);
          if(!intent)return null;
          const result=await relay.requestSummary(oauth,deviceId,projectId,intent);
          if(!result||result.requestId!==intent.requestId||
            result.projectId!==projectId||result.operation!=="project_summary")
            return null;
          // Revocation or expiry during the remote request cannot release a
          // stale project presence result, even if the local socket answered.
          const current=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!current||current.deviceId!==deviceId)return null;
          try{await verify(matched[1]);}catch{return null;}
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          const {projectPresent,boardPresent,schematicPresent}=result.files;
          return {projectPresent,boardPresent,schematicPresent};
        } : undefined;
      const drcReader=services.mcpProjectNativeDrcEnabled&&summaryRelay?.()
        ? async(deviceId:string,projectId:string)=>{
          const project=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!project||project.deviceId!==deviceId)return null;
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          try{await verify(matched[1]);}catch{return null;}
          const relay=summaryRelay();
          if(!relay?.prepareOwnerDrc||!relay.requestDrc)return null;
          const oauth={ownerSub:actor.sub,clientId:actor.clientId,
            accessTokenIssuedAtSeconds:actor.issuedAt};
          const intent=relay.prepareOwnerDrc(oauth,deviceId,projectId);
          if(!intent)return null;
          const result=await relay.requestDrc(oauth,deviceId,projectId,intent);
          if(!result||result.requestId!==intent.requestId||
            result.projectId!==projectId||result.operation!=="run_drc")return null;
          const current=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!current||current.deviceId!==deviceId)return null;
          try{await verify(matched[1]);}catch{return null;}
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          return result.counts;
        } : undefined;
      const inspectionReader=services.mcpProjectInspectionEnabled&&summaryRelay?.()
        ? async(deviceId:string,projectId:string)=>{
          // Same real OAuth client/project/device authorization, without
          // accepting client-supplied filesystem paths or operation names.
          const project=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!project||project.deviceId!==deviceId)return null;
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          try{await verify(matched[1]);}catch{return null;}
          const relay=summaryRelay();
          if(!relay?.prepareOwnerInspection||!relay.requestInspection)return null;
          const oauth={ownerSub:actor.sub,clientId:actor.clientId,
            accessTokenIssuedAtSeconds:actor.issuedAt};
          const intent=relay.prepareOwnerInspection(oauth,deviceId,projectId);
          if(!intent)return null;
          const result=await relay.requestInspection(oauth,deviceId,projectId,intent);
          if(!result||result.requestId!==intent.requestId||
             result.projectId!==projectId||
             result.operation!=="project_worker_inspection")return null;
          const current=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!current||current.deviceId!==deviceId)return null;
          try{await verify(matched[1]);}catch{return null;}
          if(!await inventory.isAccessTokenAllowed(
            actor.sub,actor.clientId,actor.issuedAt))return null;
          return result.status;
        } : undefined;
      const boardReader=services.mcpProjectBoardCountsEnabled&&summaryRelay?.()
        ? async(deviceId:string,projectId:string)=>{
          const project=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!project||project.deviceId!==deviceId)return null;
          if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))
            return null;
          try{await verify(matched[1]);}catch{return null;}
          const relay=summaryRelay();
          if(!relay?.prepareOwnerBoardCounts||!relay.requestBoardCounts)return null;
          const oauth={ownerSub:actor.sub,clientId:actor.clientId,
            accessTokenIssuedAtSeconds:actor.issuedAt};
          const intent=relay.prepareOwnerBoardCounts(oauth,deviceId,projectId);
          if(!intent)return null;
          const result=await relay.requestBoardCounts(oauth,deviceId,projectId,intent);
          if(!result||result.requestId!==intent.requestId||
             result.projectId!==projectId||result.operation!=="project_board_counts")
            return null;
          const current=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!current||current.deviceId!==deviceId)return null;
          try{await verify(matched[1]);}catch{return null;}
          if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))
            return null;
          return {...result.counts,source:result.source};
        } : undefined;
      const schematicReader=services.mcpProjectSchematicCountsEnabled&&summaryRelay?.()
        ? async(deviceId:string,projectId:string)=>{
          const project=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!project||project.deviceId!==deviceId)return null;
          if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))
            return null;
          try{await verify(matched[1]);}catch{return null;}
          const relay=summaryRelay();
          if(!relay?.prepareOwnerSchematicCounts||!relay.requestSchematicCounts)return null;
          const oauth={ownerSub:actor.sub,clientId:actor.clientId,
            accessTokenIssuedAtSeconds:actor.issuedAt};
          const intent=relay.prepareOwnerSchematicCounts(oauth,deviceId,projectId);
          if(!intent)return null;
          const result=await relay.requestSchematicCounts(oauth,deviceId,projectId,intent);
          if(!result||result.requestId!==intent.requestId||
             result.projectId!==projectId||result.operation!=="project_schematic_counts")
            return null;
          const current=await inventory.getProject(actor.sub,actor.clientId,projectId);
          if(!current||current.deviceId!==deviceId)return null;
          try{await verify(matched[1]);}catch{return null;}
          if(!await inventory.isAccessTokenAllowed(actor.sub,actor.clientId,actor.issuedAt))
            return null;
          return result.counts;
        } : undefined;
      const handler=createCloudMcpHandler(
        inventory,actor,presenceReader,drcReader,inspectionReader,boardReader,schematicReader);
      let output: Response;
      try {
        output = await handler.fetch(request);
      } finally {
        await handler.close();
      }
      const outHeaders = Object.fromEntries(output.headers);
      delete outHeaders["set-cookie"];
      res.writeHead(output.status, { ...noCache, ...outHeaders });
      res.end(Buffer.from(await output.arrayBuffer()));
    } catch (error) {
      if (!res.headersSent) {
        deny(res, error instanceof Error && error.message === "REQUEST_TOO_LARGE" ? 413 : 500,
          error instanceof Error && error.message === "REQUEST_TOO_LARGE" ? "request_too_large" : "internal_error");
      } else {
        res.end();
      }
    }
}
