/**
 * Offline, read-only Cloudflare release prerequisites.
 * Accepts a sanitized observation snapshot; never creates/updates any rule.
 * "PREREQUISITES_MET" is not deployment approval or semantic WAF proof.
 */
const DEVICE_ENDPOINTS=[
  {path:"/api/v1/pairing/device/challenge",method:"POST"},
  {path:"/api/v1/pairing/device/redeem",method:"POST"},
  {path:"/api/v1/connector/ws",method:"GET"}
];
// This is the private *inside-Docker* hop. Public access remains HTTPS.
const TUNNEL_TARGET=["http:","","app:8787"].join("/");
const PRODUCT_ZONE="oaslananka.dev";
const PRODUCT_HOSTNAME="kicad-mcp-pro.oaslananka.dev";
function normalizedHostname(value){
  return typeof value==="string"?value.toLowerCase():"";
}
function matchingEdgePolicy(rule,hostname,{path,method}){
  if(rule?.enabled!==true||rule.action!=="block")return false;
  const expression=rule.expression;
  const characteristics=rule.characteristics;
  if(typeof expression!=="string"||!Array.isArray(characteristics))return false;
  // Necessary, not sufficient: operator must review actual WAF expression
  // semantics, URL normalization, counting and edge propagation.
  const refs=[
    'http.host eq "'+hostname+'"',
    'http.request.uri.path eq "'+path+'"',
    'http.request.method eq "'+method+'"'
  ];
  return refs.every(fragment=>expression.includes(fragment))&&
    characteristics.includes("ip.src")&&
    characteristics.includes("cf.colo.id")&&
    Number.isInteger(rule.period)&&rule.period>=10&&
    Number.isInteger(rule.requestsPerPeriod)&&rule.requestsPerPeriod>=1;
}
function checkRoute(s,issues){
  const hostname=normalizedHostname(s?.hostname);
  if(s?.zoneName!==PRODUCT_ZONE||hostname!==PRODUCT_HOSTNAME)
    issues.add("WRONG_ZONE_OR_HOSTNAME");
  const dns=s?.dns;
  const tunnel=s?.tunnel;
  if(!hostname||!dns||!tunnel){issues.add("INCOMPLETE_ROUTE_INVENTORY");return;}
  if(dns.name!==hostname||dns.proxied!==true||dns.type!=="CNAME"||
     dns.content!==tunnel.id+".cfargotunnel.com")
    issues.add("DNS_TUNNEL_MISMATCH");
  if(tunnel.status!=="healthy"||
     !Number.isInteger(tunnel.connectionCount)||tunnel.connectionCount<=0)
    issues.add("TUNNEL_NOT_HEALTHY");
  const ingress=Array.isArray(tunnel.ingress)?tunnel.ingress:[];
  const route=ingress.filter(x=>normalizedHostname(x.hostname)===hostname);
  if(route.length!==1)issues.add("HOSTNAME_ROUTE_NOT_UNIQUE");
  else if(route[0].service!==TUNNEL_TARGET)
    issues.add("DEDICATED_ORIGIN_ROUTE_NOT_CONFIGURED");
  if(ingress.some(x=>x.hostname&&normalizedHostname(x.hostname)!==hostname)||
     (Number.isInteger(tunnel.otherHostnameCount)&&tunnel.otherHostnameCount>0))
    issues.add("TUNNEL_SHARED_WITH_OTHER_HOSTNAMES");
  if(!s.expectedDedicatedTunnelId||tunnel.id!==s.expectedDedicatedTunnelId)
    issues.add("DEDICATED_TUNNEL_NOT_ACCEPTED");
}
function checkRateRules(s,issues){
  const rate=s?.rateLimiting;
  if(rate?.inventoryStatus!=="verified"||!Array.isArray(rate.rules)){
    issues.add("RATE_LIMIT_INVENTORY_UNKNOWN");return;
  }
  // Cloudflare's published Free-tier rule allowance is one rule in total.
  if(rate.plan==="free"&&rate.rules.length>=1)
    issues.add("FREE_TIER_RATE_RULE_SLOT_EXHAUSTED");
  if(rate.plan!=="free"&&rate.capacityVerified!==true)
    issues.add("PLAN_RULE_CAPACITY_UNVERIFIED");
  for(const end of DEVICE_ENDPOINTS){
    const valid=rate.rules.some(rule=>
      matchingEdgePolicy(rule,s.hostname,end));
    if(!valid){
      let code="WSS_EDGE_RULE_MISSING";
      if(end.path.endsWith("/challenge"))code="CHALLENGE_EDGE_RULE_MISSING";
      else if(end.path.endsWith("/redeem"))code="REDEEM_EDGE_RULE_MISSING";
      issues.add(code);
    }
  }
}
function checkProvenance(s,issues){
  if(s?.workerRoutes?.inventoryStatus!=="verified")
    issues.add("WORKER_ROUTE_INVENTORY_UNKNOWN");
  else if((s.workerRoutes.matchingHostnameCount??0)>0)
    issues.add("WORKER_ROUTE_REQUIRES_REVIEW");
  if(s?.transformRules?.inventoryStatus!=="verified")
    issues.add("TRANSFORM_RULE_INVENTORY_UNKNOWN");
  else if((s.transformRules.sourceHeaderRewriteCount??0)>0)
    issues.add("SOURCE_HEADER_REWRITE_REQUIRES_REVIEW");
  if(s?.originIsolationAccepted!==true)
    issues.add("ORIGIN_ISOLATION_UNVERIFIED");
  if(s?.headerProvenanceAccepted!==true)
    issues.add("SOURCE_HEADER_PROVENANCE_UNVERIFIED");
}
export function auditCloudflareEdge(snapshot){
  const findings=new Set();
  checkRoute(snapshot,findings);
  checkRateRules(snapshot,findings);
  checkProvenance(snapshot,findings);
  const list=[...findings].sort((a,b)=>a.localeCompare(b));
  return {verdict:list.length?"BLOCKED":"CONFIG_PREREQUISITES_MET",findings:list};
}
