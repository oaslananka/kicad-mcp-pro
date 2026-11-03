import {createHash,randomUUID,timingSafeEqual} from "node:crypto";
import {generateAuthenticationOptions,verifyAuthenticationResponse,
  type AuthenticationResponseJSON} from "@simplewebauthn/server";
import type {Pool} from "pg";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CRED=/^[a-zA-Z0-9_-]{24,1024}$/;
function authority(input:string){
  const uri=new URL(input);
  if(uri.protocol!=="https:"||uri.origin!==input||uri.pathname!=="/"||
    uri.username||uri.password||uri.search||uri.hash||input.length>256)
    throw Error("Passkey activation requires exact HTTPS authority");
  return uri;
}
function hash(challenge:string):Buffer|null{
  if(!/^[A-Za-z0-9_-]{43}$/.test(challenge))return null;
  const bytes=Buffer.from(challenge,"base64url");
  if(bytes.length!==32||bytes.toString("base64url")!==challenge)return null;
  return createHash("sha256").update(bytes).digest();
}
type Pending={
  owner_sub:string;credential_id:string;challenge_digest:Buffer;
};
type Passkey={owner_sub:string;public_key:Buffer;sign_count:string;enabled:boolean};

/**
 * Standalone draft-only activation service. The owner identity passed here
 * MUST originate from an independent, authenticated owner-session verifier.
 * No HTTP handler, production role, feature flag or session is wired.
 * This requires a fresh user-verified passkey signature even after registration.
 */
export class PgOwnerReadPasskeyActivation{
  private readonly rpID:string;
  constructor(private readonly pool:Pool,private readonly origin:string){
    this.rpID=authority(origin).hostname;
  }
  private async authorized():Promise<boolean>{
    const result=await this.pool.query<{allowed:boolean}>(
      "SELECT has_table_privilege(current_user,'owner_read_passkey_activations','INSERT')"+
      " AND has_column_privilege(current_user,'owner_read_passkeys','enabled','UPDATE')"+
      " AND has_column_privilege(current_user,'owner_read_passkeys','sign_count','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_passkeys','INSERT')"+
      " AND NOT has_table_privilege(current_user,'owner_read_passkeys','DELETE')"+
      " AND NOT has_column_privilege(current_user,'owner_read_passkeys','public_key','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','INSERT')"+
      " AND NOT has_column_privilege(current_user,'owner_read_approvals','consumed_at','UPDATE')"+
      " AS allowed");
    return result.rows[0]?.allowed===true;
  }
  async begin(ownerSub:string,credentialId:string){
    if(typeof ownerSub!=="string"||ownerSub.length<1||ownerSub.length>256||
       !CRED.test(credentialId)||!await this.authorized())return null;
    const selected=await this.pool.query(
      "SELECT credential_id FROM owner_read_passkeys "+
      "WHERE owner_sub=$1 AND credential_id=$2 AND enabled=false",
      [ownerSub,credentialId]);
    if(selected.rowCount!==1)return null;
    const options=await generateAuthenticationOptions({
      rpID:this.rpID,allowCredentials:[{id:credentialId}],
      userVerification:"required",timeout:120_000
    });
    const digest=hash(options.challenge);
    if(!digest)return null;
    const requestId=randomUUID();
    await this.pool.query(
      "INSERT INTO owner_read_passkey_activations"+
      "(request_id,owner_sub,credential_id,challenge_digest,created_at,expires_at)"+
      " VALUES($1,$2,$3,$4,statement_timestamp(),"+
      "statement_timestamp()+interval '120 seconds')",
      [requestId,ownerSub,credentialId,digest]);
    return {requestId,options};
  }
  async complete(ownerSub:string,requestId:string,challenge:string,
    assertion:AuthenticationResponseJSON):Promise<boolean>{
    if(typeof ownerSub!=="string"||ownerSub.length<1||ownerSub.length>256||
       !UUID.test(requestId)||!await this.authorized())return false;
    const client=await this.pool.connect();
    let transaction=false,signatureChecked=false;
    try{
      await client.query("BEGIN");transaction=true;
      // Burn the challenge immediately; do not allow a failed signature to
      // re-arm it through a rollback. PostgreSQL trigger blocks direct reset.
      const claim=await client.query<Pending>(
        "UPDATE owner_read_passkey_activations SET used_at=clock_timestamp() "+
        "WHERE request_id=$1 AND owner_sub=$2 AND used_at IS NULL "+
        "AND expires_at>clock_timestamp() RETURNING "+
        "owner_sub,credential_id,challenge_digest",[requestId,ownerSub]);
      const pending=claim.rows[0];
      if(!pending){await client.query("COMMIT");transaction=false;return false;}
      const incoming=hash(challenge);
      if(!incoming||pending.challenge_digest.length!==incoming.length||
         !timingSafeEqual(pending.challenge_digest,incoming)||
         assertion?.id!==pending.credential_id||
         assertion.rawId!==pending.credential_id){
        await client.query("COMMIT");transaction=false;return false;
      }
      const record=await client.query<Passkey>(
        "SELECT owner_sub,public_key,sign_count,enabled "+
        "FROM owner_read_passkeys WHERE credential_id=$1 FOR UPDATE",
        [pending.credential_id]);
      const passkey=record.rows[0];
      if(!passkey||passkey.owner_sub!==ownerSub||passkey.enabled){
        await client.query("COMMIT");transaction=false;return false;
      }
      let counter:number;
      try{
        const verified=await verifyAuthenticationResponse({
          response:assertion,expectedChallenge:challenge,
          expectedOrigin:this.origin,expectedRPID:this.rpID,
          credential:{id:pending.credential_id,
            publicKey:Uint8Array.from(passkey.public_key),
            counter:Number(passkey.sign_count)},requireUserVerification:true
        });
        if(!verified.verified||!verified.authenticationInfo.userVerified){
          await client.query("COMMIT");transaction=false;return false;
        }
        counter=verified.authenticationInfo.newCounter;
      }catch{
        await client.query("COMMIT");transaction=false;return false;
      }
      signatureChecked=true;
      if(!Number.isSafeInteger(counter)||counter<0){
        await client.query("COMMIT");transaction=false;return false;
      }
      const activated=await client.query(
        "UPDATE owner_read_passkeys SET enabled=true,sign_count=$1 "+
        "WHERE credential_id=$2 AND owner_sub=$3 AND enabled=false "+
        "AND (sign_count=0 OR $1>sign_count) RETURNING credential_id",
        [counter,pending.credential_id,ownerSub]);
      if(activated.rowCount!==1){
        await client.query("COMMIT");transaction=false;return false;
      }
      await client.query("COMMIT");transaction=false;
      return true;
    }catch{
      if(transaction){
        await client.query(signatureChecked?"ROLLBACK":"COMMIT");
        transaction=false;
      }
      return false;
    }finally{client.release();}
  }
}
