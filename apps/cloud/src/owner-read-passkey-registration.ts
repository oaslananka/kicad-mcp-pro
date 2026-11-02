import {createHash,randomBytes,timingSafeEqual} from "node:crypto";
import {generateRegistrationOptions,verifyRegistrationResponse,
  type RegistrationResponseJSON} from "@simplewebauthn/server";
import type {Pool} from "pg";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function fingerprint(challenge:string):Buffer|null{
  if(!/^[a-zA-Z0-9_-]{43}$/.test(challenge))return null;
  const bytes=Buffer.from(challenge,"base64url");
  if(bytes.length!==32||bytes.toString("base64url")!==challenge)return null;
  return createHash("sha256").update(bytes).digest();
}
function validOrigin(origin:string):URL{
  const uri=new URL(origin);
  if(uri.protocol!=="https:"||uri.origin!==origin||
    uri.pathname!=="/"||uri.username||uri.password||uri.search||uri.hash||
    origin.length>256)throw Error("Exact HTTPS passkey authority origin required");
  return uri;
}
type RegistrationClaim={owner_sub:string;challenge_digest:Buffer};
export type PasskeyRegistrationResult="registered_inactive"|"denied";

/**
 * Non-production standalone passkey enrollment primitive.
 * Trusted independent owner-session verification MUST happen outside this
 * class for BOTH calls. Neither caller identity nor public HTTP endpoints
 * can be derived from the untrusted request body. A registration SQL role
 * may INSERT only non-enabled credentials; separate authorized human owner
 * approval is required before the credential can issue a read receipt.
 */
export class PgOwnerReadPasskeyRegistration{
  private readonly rpID:string;
  constructor(private readonly db:Pool,private readonly authorityOrigin:string){
    this.rpID=validOrigin(authorityOrigin).hostname;
  }
  /** Startup preflight and per-request enforcement of the same DB role fence. */
  async verifyRestrictedRole():Promise<boolean>{
    const query=await this.db.query<{allowed:boolean}>(
      "SELECT "+
      "has_table_privilege(current_user,'owner_read_passkey_registrations','INSERT')"+
      " AND has_column_privilege(current_user,'owner_read_passkeys','public_key','INSERT')"+
      " AND NOT has_column_privilege(current_user,'owner_read_passkeys','enabled','INSERT')"+
      " AND NOT has_column_privilege(current_user,'owner_read_passkeys','enabled','UPDATE')"+
      " AND NOT has_table_privilege(current_user,'owner_read_approvals','INSERT')"+
      " AND NOT has_table_privilege(current_user,'owner_read_passkeys','DELETE')"+
      " AS allowed");
    return query.rows[0]?.allowed===true;
  }
  async begin(ownerSub:string,requestId:string){
    if(!UUID.test(requestId)||typeof ownerSub!=="string"||
       ownerSub.length<1||ownerSub.length>256||
       !await this.verifyRestrictedRole())return null;
    const registered=await this.db.query<{credential_id:string}>(
      "SELECT credential_id FROM owner_read_passkeys WHERE owner_sub=$1",
      [ownerSub]);
    const options=await generateRegistrationOptions({
      rpName:"KiCad Cloud owner approval",rpID:this.rpID,
      userName:ownerSub,userID:Uint8Array.from(randomBytes(32)),
      attestationType:"none",timeout:120_000,
      authenticatorSelection:{residentKey:"preferred",userVerification:"required"},
      supportedAlgorithmIDs:[-7], // ES256: explicit support/verification contract.
      excludeCredentials:registered.rows.map(row=>({id:row.credential_id}))
    });
    const hashed=fingerprint(options.challenge);
    if(!hashed)return null;
    await this.db.query(
      "INSERT INTO owner_read_passkey_registrations"+
      "(request_id,owner_sub,challenge_digest,created_at,expires_at)"+
      " VALUES($1,$2,$3,statement_timestamp(),"+
      "statement_timestamp()+interval '120 seconds')",
      [requestId,ownerSub,hashed]);
    return options;
  }
  async complete(ownerSub:string,requestId:string,
    response:RegistrationResponseJSON):Promise<PasskeyRegistrationResult>{
    if(!UUID.test(requestId)||typeof ownerSub!=="string"||
       ownerSub.length<1||ownerSub.length>256||
       !await this.verifyRestrictedRole())return "denied";
    const conn=await this.db.connect();
    let started=false;
    try{
      await conn.query("BEGIN");started=true;
      // Even invalid submissions consume the challenge. A later correct
      // assertion with the same challenge cannot change the verdict.
      const claimed=await conn.query<RegistrationClaim>(
        "UPDATE owner_read_passkey_registrations "+
        "SET used_at=clock_timestamp() "+
        "WHERE request_id=$1 AND owner_sub=$2 AND used_at IS NULL "+
        "AND expires_at>clock_timestamp() "+
        "RETURNING owner_sub,challenge_digest",[requestId,ownerSub]);
      const row=claimed.rows[0];
      if(!row){
        await conn.query("COMMIT");started=false;return "denied";
      }
      let challenge="";
      try{
        if(typeof response?.response?.clientDataJSON!=="string"||
          response.response.clientDataJSON.length>16_384)throw Error("invalid client data");
        const body=JSON.parse(Buffer.from(response.response.clientDataJSON,
          "base64url").toString("utf8")) as {challenge?:unknown};
        if(typeof body.challenge!=="string")throw Error("invalid challenge");
        challenge=body.challenge;
      }catch{
        await conn.query("COMMIT");started=false;return "denied";
      }
      const hashed=fingerprint(challenge);
      if(!hashed||row.challenge_digest.length!==hashed.length||
         !timingSafeEqual(row.challenge_digest,hashed)){
        await conn.query("COMMIT");started=false;return "denied";
      }
      // A malformed WebAuthn attestation must not roll back its already
      // claimed one-use challenge. Database write failures, however, must
      // roll back the complete credential insert transaction.
      let signatureChecked=false;
      try{
        const verified=await verifyRegistrationResponse({
          response,expectedChallenge:challenge,
          expectedOrigin:this.authorityOrigin,expectedRPID:this.rpID,
          requireUserPresence:true,requireUserVerification:true,
          supportedAlgorithmIDs:[-7]
        });
        signatureChecked=true;
        if(!verified.verified||!verified.registrationInfo.userVerified){
          await conn.query("COMMIT");started=false;return "denied";
        }
        const {id,publicKey,counter}=verified.registrationInfo.credential;
        if(!/^[a-zA-Z0-9_-]{24,1024}$/.test(id)||
          publicKey.length<32||publicKey.length>2048||
          !Number.isSafeInteger(counter)||counter<0){
          await conn.query("COMMIT");started=false;return "denied";
        }
        const created=await conn.query(
          "INSERT INTO owner_read_passkeys "+
          "(credential_id,owner_sub,public_key,sign_count) "+
          "VALUES($1,$2,$3,$4) ON CONFLICT(credential_id) DO NOTHING "+
          "RETURNING credential_id",[id,ownerSub,Buffer.from(publicKey),counter]);
        await conn.query("COMMIT");started=false;
        return created.rowCount===1?"registered_inactive":"denied";
      }catch{
        if(started){
          // Invalid signatures may throw inside SimpleWebAuthn. Consume the
          // claimed challenge even then; only storage failures roll back.
          await conn.query(signatureChecked?"ROLLBACK":"COMMIT");
          started=false;
        }
        return "denied";
      }
    }catch{
      if(started)await conn.query("ROLLBACK");
      return "denied";
    }finally{conn.release();}
  }
}
