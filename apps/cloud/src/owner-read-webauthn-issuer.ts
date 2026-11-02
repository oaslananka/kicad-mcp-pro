import {createHash,timingSafeEqual} from "node:crypto";
import {generateAuthenticationOptions,verifyAuthenticationResponse,
  type AuthenticationResponseJSON} from "@simplewebauthn/server";
import type {Pool} from "pg";

/**
 * Inert standalone issuer core: no HTTP routes, browser enrollment, credentials,
 * or production wiring. The caller MUST be an independently authenticated
 * owner authority, not the Cloud connector or the OAuth client being approved.
 * Its PostgreSQL login may INSERT approvals but MUST NOT consume them.
 */
export type OwnerReadApprovalIntent=Readonly<{
  requestId:string;ownerSub:string;clientId:string;deviceId:string;
  projectId:string;origin:string;expiresAtUnixMs:number;
}>;
type Challenge={
  owner_sub:string;client_id:string;device_id:string;project_id:string;
  cloud_origin:string;credential_id:string;challenge_digest:Buffer;
  expires_at:Date;
};
type Credential={owner_sub:string;public_key:Buffer;sign_count:string;enabled:boolean};
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CREDENTIAL_ID=/^[A-Za-z0-9_-]{24,1024}$/;
function checkIntent(intent:OwnerReadApprovalIntent,now:number):boolean{
  if(!intent||!UUID.test(intent.requestId)||!UUID.test(intent.deviceId)||
    !UUID.test(intent.projectId)||
    typeof intent.ownerSub!=="string"||!intent.ownerSub||intent.ownerSub.length>256||
    typeof intent.clientId!=="string"||!intent.clientId||intent.clientId.length>1024||
    !Number.isSafeInteger(intent.expiresAtUnixMs)||
    intent.expiresAtUnixMs-now<5_000||intent.expiresAtUnixMs-now>30_000)return false;
  try{
    const url=new URL(intent.origin);
    return url.protocol==="https:"&&url.origin===intent.origin&&
      url.pathname==="/"&&!url.username&&!url.password&&!url.search&&!url.hash&&
      intent.origin.length<=256;
  }catch{return false;}
}
function validAuthorityOrigin(input:string):URL{
  const uri=new URL(input);
  if(uri.protocol!=="https:"||uri.origin!==input||
    uri.pathname!=="/"||uri.search||uri.hash||uri.username||uri.password||
    input.length>256)throw Error("Passkey issuer requires exact HTTPS authority origin");
  return uri;
}
function digest(challenge:string):Buffer|null{
  if(!/^[A-Za-z0-9_-]{43}$/.test(challenge))return null;
  const bytes=Buffer.from(challenge,"base64url");
  if(bytes.length!==32||bytes.toString("base64url")!==challenge)return null;
  return createHash("sha256").update(bytes).digest();
}

export class PgOwnerReadWebAuthnIssuer{
  private readonly authorityRPID:string;
  constructor(private readonly db:Pool,private readonly authorityOrigin:string){
    this.authorityRPID=validAuthorityOrigin(authorityOrigin).hostname;
  }

  /** Startup preflight and per-request least-privilege fence.
   * An issuer can sign/insert owner receipts but cannot activate passkeys,
   * consume receipts, or create arbitrary credentials.
   */
  async verifyRestrictedRole():Promise<boolean>{
    const privilege=await this.db.query<{allowed:boolean}>(
      "SELECT has_table_privilege(current_user,'owner_read_approvals','INSERT')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','DELETE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','TRUNCATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','consumed_at','UPDATE')"+
      " AND has_table_privilege(current_user,'owner_read_passkeys','SELECT')"+
      " AND has_column_privilege(current_user,'owner_read_passkeys','sign_count','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_passkeys','enabled','UPDATE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_passkeys','public_key','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_passkeys','INSERT')"+
      " AND NOT has_table_privilege(current_user,'owner_read_passkeys','DELETE')"+
      " AND has_table_privilege(current_user,'owner_read_webauthn_challenges','SELECT')"+
      " AND has_table_privilege(current_user,'owner_read_webauthn_challenges','INSERT')"+
      " AND has_column_privilege(current_user,'owner_read_webauthn_challenges','used_at','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_webauthn_challenges','DELETE')"+
      " AS allowed"
    );
    return privilege.rows[0]?.allowed===true;
  }

  async begin(intent:OwnerReadApprovalIntent,credentialId:string){
    if(!checkIntent(intent,Date.now())||!CREDENTIAL_ID.test(credentialId))return null;
    if(!await this.verifyRestrictedRole())return null;
    const registered=await this.db.query<{credential_id:string}>(
      "SELECT credential_id FROM owner_read_passkeys "+
      "WHERE credential_id=$1 AND owner_sub=$2 AND enabled=true",
      [credentialId,intent.ownerSub]);
    if(registered.rowCount!==1)return null;
    // Library-generated challenge is 32 random bytes, encoded exactly once.
    const remaining=intent.expiresAtUnixMs-Date.now();
    if(remaining<5_000)return null;
    const options=await generateAuthenticationOptions({
      rpID:this.authorityRPID,allowCredentials:[{id:credentialId}],
      userVerification:"required",timeout:remaining
    });
    const fingerprint=digest(options.challenge);
    if(!fingerprint)return null;
    // Scope is a *trusted* server request, not user-supplied form contents.
    await this.db.query(
      "INSERT INTO owner_read_webauthn_challenges "+
      "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,"+
      "credential_id,challenge_digest,expires_at) "+
      "VALUES($1,$2,$3,$4,$5,$6,$7,$8,to_timestamp($9::double precision/1000))",
      [intent.requestId,intent.ownerSub,intent.clientId,intent.deviceId,
        intent.projectId,intent.origin,credentialId,fingerprint,intent.expiresAtUnixMs]);
    return options;
  }

  async approve(requestId:string,challenge:string,
    assertion:AuthenticationResponseJSON):Promise<boolean>{
    if(!UUID.test(requestId))return false;
    const db=await this.db.connect();
    let open=false;
    try{
      await db.query("BEGIN");
      open=true;
      // Atomic claim burns the attempt EVEN IF signature or UV fails.
      const claimed=await db.query<Challenge>(
        "UPDATE owner_read_webauthn_challenges SET used_at=clock_timestamp() "+
        "WHERE request_id=$1 AND used_at IS NULL "+
        "AND expires_at>clock_timestamp() "+
        "RETURNING owner_sub,client_id,device_id,project_id,cloud_origin,"+
        "credential_id,challenge_digest,expires_at",[requestId]);
      const request=claimed.rows[0];
      if(!request){
        await db.query("COMMIT");open=false;return false;
      }
      const fingerprint=digest(challenge);
      const matching=fingerprint&&request.challenge_digest.length===fingerprint.length&&
        timingSafeEqual(request.challenge_digest,fingerprint);
      if(!matching||assertion?.id!==request.credential_id||
        assertion.rawId!==request.credential_id){
        await db.query("COMMIT");open=false;return false;
      }
      const keyResult=await db.query<Credential>(
        "SELECT owner_sub,public_key,sign_count,enabled FROM owner_read_passkeys "+
        "WHERE credential_id=$1 FOR UPDATE",[request.credential_id]);
      const key=keyResult.rows[0];
      if(!key?.enabled||key.owner_sub!==request.owner_sub){
        await db.query("COMMIT");open=false;return false;
      }
      let count:number;
      try{
        const result=await verifyAuthenticationResponse({
          response:assertion,expectedChallenge:challenge,
          expectedOrigin:this.authorityOrigin,expectedRPID:this.authorityRPID,
          credential:{id:request.credential_id,publicKey:Uint8Array.from(key.public_key),
            counter:Number(key.sign_count)},
          requireUserVerification:true
        });
        if(!result.verified||!result.authenticationInfo.userVerified){
          await db.query("COMMIT");open=false;return false;
        }
        count=result.authenticationInfo.newCounter;
      }catch{
        await db.query("COMMIT");open=false;return false;
      }
      if(!Number.isSafeInteger(count)||count<0){
        await db.query("COMMIT");open=false;return false;
      }
      const updated=await db.query(
        "UPDATE owner_read_passkeys SET sign_count=$1 "+
        "WHERE credential_id=$2 AND owner_sub=$3 AND enabled=true "+
        "AND (sign_count=0 OR $1>sign_count) RETURNING credential_id",
        [count,request.credential_id,request.owner_sub]);
      if(updated.rowCount!==1){
        await db.query("COMMIT");open=false;return false;
      }
      // The DB enforces 30-second issuance expiry; no other operation is
      // permitted. Never accept a receipt supplied by the OAuth client.
      await db.query(
        "INSERT INTO owner_read_approvals "+
        "(request_id,owner_sub,client_id,device_id,project_id,cloud_origin,"+
        "operation,expires_at) "+
        "VALUES($1,$2,$3,$4,$5,$6,'project_summary',$7)",
        [requestId,request.owner_sub,request.client_id,request.device_id,
          request.project_id,request.cloud_origin,request.expires_at]);
      await db.query("COMMIT");
      open=false;
      return true;
    }catch{
      if(open)await db.query("ROLLBACK");
      return false;
    }finally{
      db.release();
    }
  }
}
