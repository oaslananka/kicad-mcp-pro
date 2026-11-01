import { createHash, createHmac, createPublicKey, randomBytes, randomUUID, timingSafeEqual, verify } from "node:crypto";

const USER_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const USER_CODE_LENGTH = 12;
export const PAIRING_TTL_MS = 5 * 60 * 1_000;
export const MAX_USER_CODE_ATTEMPTS = 5;

export type PairingStatus = "pending" | "approved" | "denied" | "locked" | "consumed" | "expired";

export interface PairingRecord {
  readonly id: string;
  readonly deviceAlias: string;
  readonly devicePublicKeyDer: string;
  readonly deviceFingerprint: string;
  readonly userCodeMac: string;
  readonly deviceCodeMac: string;
  readonly expiresAtMs: number;
  readonly state: PairingStatus;
  readonly attempts: number;
  readonly ownerSub: string | null;
}

export interface IssuedPairing {
  readonly record: PairingRecord;
  readonly userCode: string;
  readonly deviceCode: string;
}

export type ApprovalResult =
  | { readonly kind: "approved" | "denied"; readonly record: PairingRecord }
  | { readonly kind: "invalid_code" | "locked" | "unavailable"; readonly record: PairingRecord };

export type RedeemResult =
  | { readonly kind: "redeemed"; readonly record: PairingRecord; readonly ownerSub: string }
  | { readonly kind: "unavailable"; readonly record: PairingRecord };

function validClock(nowMs: number): boolean {
  return Number.isSafeInteger(nowMs) && nowMs > 0 && nowMs <= Number.MAX_SAFE_INTEGER - PAIRING_TTL_MS;
}

function requireServerKey(serverKey: Buffer): void {
  if (!Buffer.isBuffer(serverKey) || serverKey.length < 32) {
    throw new Error("PAIRING_SERVER_KEY_TOO_SHORT");
  }
}

function mac(serverKey: Buffer, domain: "user" | "device", value: string): Buffer {
  return createHmac("sha256", serverKey).update("kicad-pairing-v1").update("\0")
    .update(domain).update("\0").update(value).digest();
}

function matches(serverKey: Buffer, domain: "user" | "device", value: string, hex: string): boolean {
  if (!/^[a-f0-9]{64}$/.test(hex)) return false;
  return timingSafeEqual(mac(serverKey, domain, value), Buffer.from(hex, "hex"));
}

function normalizedUserCode(value: string): string | null {
  if (typeof value !== "string" || value.length > 20) return null;
  const normalized = value.replace(/[ -]/g, "").toUpperCase();
  if (normalized.length !== USER_CODE_LENGTH ||
      [...normalized].some(letter => !USER_ALPHABET.includes(letter))) return null;
  return normalized;
}

function stateAt(record: PairingRecord, nowMs: number): PairingRecord {
  if (record.state === "pending" || record.state === "approved") {
    if (nowMs >= record.expiresAtMs) return { ...record, state: "expired" };
  }
  return record;
}

export function issuePairing(
  serverKey: Buffer, nowMs: number, deviceAlias: string, publicKeyDer: Buffer
): IssuedPairing {
  requireServerKey(serverKey);
  if (!validClock(nowMs)) throw new Error("INVALID_PAIRING_CLOCK");
  if (typeof deviceAlias !== "string" || !/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(deviceAlias)) {
    throw new Error("INVALID_DEVICE_ALIAS");
  }
  if (!Buffer.isBuffer(publicKeyDer) || publicKeyDer.length < 32 || publicKeyDer.length > 128) {
    throw new Error("INVALID_DEVICE_KEY");
  }
  let publicKey;
  try {
    publicKey = createPublicKey({ key: publicKeyDer, format: "der", type: "spki" });
  } catch {
    throw new Error("INVALID_DEVICE_KEY");
  }
  if (publicKey.asymmetricKeyType !== "ed25519") throw new Error("DEVICE_KEY_MUST_BE_ED25519");

  const bytes = randomBytes(USER_CODE_LENGTH);
  const rawCode = [...bytes].map(byte => USER_ALPHABET[byte & 31]).join("");
  const userCode = rawCode.slice(0, 6) + "-" + rawCode.slice(6);
  const deviceCode = randomBytes(32).toString("base64url");
  const devicePublicKeyDer = publicKey.export({ format: "der", type: "spki" }) as Buffer;
  const fingerprint = createHash("sha256").update(devicePublicKeyDer).digest("hex");
  const record: PairingRecord = {
    id: randomUUID(),
    deviceAlias,
    devicePublicKeyDer: devicePublicKeyDer.toString("base64"),
    deviceFingerprint: fingerprint,
    userCodeMac: mac(serverKey, "user", rawCode).toString("hex"),
    deviceCodeMac: mac(serverKey, "device", deviceCode).toString("hex"),
    expiresAtMs: nowMs + PAIRING_TTL_MS,
    state: "pending",
    attempts: 0,
    ownerSub: null
  };
  return { record, userCode, deviceCode };
}

/**
 * Must only be called after an actual authenticated browser session,
 * CSRF check, ownership confirmation and request rate limits.
 */
export function reviewPairing(
  record: PairingRecord,
  serverKey: Buffer,
  nowMs: number,
  authenticatedOwnerSub: string,
  enteredCode: string,
  decision: "approve" | "deny"
): ApprovalResult {
  requireServerKey(serverKey);
  if (!validClock(nowMs)) return { kind: "unavailable", record };
  const current = stateAt(record, nowMs);
  if (current.state !== "pending" || !authenticatedOwnerSub || authenticatedOwnerSub.length > 256 ||
      (decision !== "approve" && decision !== "deny")) {
    return { kind: "unavailable", record: current };
  }
  const code = normalizedUserCode(enteredCode);
  if (!code || !matches(serverKey, "user", code, current.userCodeMac)) {
    const attempts = current.attempts + 1;
    const next = { ...current, attempts, state: attempts >= MAX_USER_CODE_ATTEMPTS ? "locked" as const : "pending" as const };
    return { kind: next.state === "locked" ? "locked" : "invalid_code", record: next };
  }
  const next = { ...current, ownerSub: authenticatedOwnerSub, state: decision === "approve" ? "approved" as const : "denied" as const };
  return { kind: next.state, record: next };
}

/** A different signature domain than one-use redeem; never grants enrollment. */
export function pairingStatusProof(id:string,deviceCode:string):Buffer{
  return Buffer.from("kicad-cloud-pairing-status-v1\0"+id+"\0"+deviceCode,"utf8");
}

/** Only a device holding BOTH the issued secret and its Ed25519 key may read this bit. */
export function pairingApprovalState(
  record:PairingRecord,serverKey:Buffer,nowMs:number,
  deviceCode:string,signature:Buffer
):boolean|null{
  requireServerKey(serverKey);
  if(!validClock(nowMs)||typeof deviceCode!=="string"||deviceCode.length!==43||
     !Buffer.isBuffer(signature)||signature.length!==64||
     !matches(serverKey,"device",deviceCode,record.deviceCodeMac))return null;
  try{
    const key=createPublicKey({key:Buffer.from(record.devicePublicKeyDer,"base64"),
      format:"der",type:"spki"});
    if(key.asymmetricKeyType!=="ed25519"||
       !verify(null,pairingStatusProof(record.id,deviceCode),key,signature))return null;
  }catch{return null;}
  return record.state==="approved"&&nowMs<record.expiresAtMs;
}

export function redemptionProof(id: string, deviceCode: string): Buffer {
  return Buffer.from("kicad-cloud-pairing-proof-v1\0" + id + "\0" + deviceCode, "utf8");
}

/**
 * Returns only an approved-owner binding. Credential issuance and atomic
 * one-use CAS belong to a future persistent authenticated transport layer.
 */
export function redeemPairing(
  record: PairingRecord, serverKey: Buffer, nowMs: number,
  deviceCode: string, signature: Buffer
): RedeemResult {
  requireServerKey(serverKey);
  if (!validClock(nowMs)) return { kind: "unavailable", record };
  const current = stateAt(record, nowMs);
  if (current.state !== "approved" || !current.ownerSub ||
      typeof deviceCode !== "string" || deviceCode.length > 128 ||
      !Buffer.isBuffer(signature) || signature.length !== 64 ||
      !matches(serverKey, "device", deviceCode, current.deviceCodeMac)) {
    return { kind: "unavailable", record: current };
  }
  try {
    const key = createPublicKey({ key: Buffer.from(current.devicePublicKeyDer, "base64"), format: "der", type: "spki" });
    if (key.asymmetricKeyType !== "ed25519" || !verify(null, redemptionProof(current.id, deviceCode), key, signature)) {
      return { kind: "unavailable", record: current };
    }
  } catch {
    return { kind: "unavailable", record: current };
  }
  return { kind: "redeemed", record: { ...current, state: "consumed" }, ownerSub: current.ownerSub };
}
