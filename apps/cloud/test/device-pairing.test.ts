import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash, generateKeyPairSync, randomBytes, sign } from "node:crypto";
import {
  issuePairing, reviewPairing, redeemPairing, redemptionProof,
  pairingApprovalState,pairingStatusProof,
  PAIRING_TTL_MS, MAX_USER_CODE_ATTEMPTS
} from "../src/device-pairing.js";

const serverKey = randomBytes(32);
const now = 1_780_000_000_000;

function fixture() {
  const device = generateKeyPairSync("ed25519");
  const der = device.publicKey.export({ format: "der", type: "spki" }) as Buffer;
  const issued = issuePairing(serverKey, now, "My KiCad PC", der);
  return { ...issued, privateKey: device.privateKey };
}

test("creates high-entropy separate secrets and stores only keyed hashes", () => {
  const a = fixture();
  const b = fixture();
  assert.match(a.userCode, /^[0-9A-HJKMNP-TV-Z]{6}-[0-9A-HJKMNP-TV-Z]{6}$/);
  assert.equal(a.deviceCode.length, 43);
  assert.notEqual(a.deviceCode, b.deviceCode);
  assert.notEqual(a.userCode, b.userCode);
  const serialized = JSON.stringify(a.record);
  assert.ok(!serialized.includes(a.userCode));
  assert.ok(!serialized.includes(a.deviceCode));
  assert.equal(a.record.deviceFingerprint, createHash("sha256")
    .update(Buffer.from(a.record.devicePublicKeyDer, "base64")).digest("hex"));
  assert.equal(a.record.ownerSub, null);
  assert.equal(a.record.state, "pending");
  assert.equal(a.record.expiresAtMs, now + PAIRING_TTL_MS);
});

test("browser approval requires matching code, explicit owner and decision", () => {
  const a = fixture();
  assert.equal(reviewPairing(a.record, serverKey, now, "", a.userCode, "approve").kind, "unavailable");
  const wrong = reviewPairing(a.record, serverKey, now, "owner-a", "WRONG-000000", "approve");
  assert.equal(wrong.kind, "invalid_code");
  const approved = reviewPairing(wrong.record, serverKey, now + 100, "owner-a", a.userCode.toLowerCase(), "approve");
  assert.equal(approved.kind, "approved");
  if (approved.kind !== "approved") return;
  assert.equal(approved.record.ownerSub, "owner-a");
  assert.equal(reviewPairing(approved.record, serverKey, now + 101, "owner-b", a.userCode, "approve").kind, "unavailable");
  assert.equal(reviewPairing(a.record, serverKey, now + PAIRING_TTL_MS, "owner-a", a.userCode, "approve").kind, "unavailable");
});

test("user-code brute-force budget locks after five failed attempts", () => {
  const issued = fixture();
  let record = issued.record;
  for (let i = 1; i <= MAX_USER_CODE_ATTEMPTS; i++) {
    const result = reviewPairing(record, serverKey, now + i, "owner-a", "000000-000000", "approve");
    record = result.record;
    assert.equal(result.kind, i === MAX_USER_CODE_ATTEMPTS ? "locked" : "invalid_code");
  }
  assert.equal(reviewPairing(record, serverKey, now + 100, "owner-a", issued.userCode, "approve").kind, "unavailable");
});

test("denial is terminal; no browser code alone can redeem", () => {
  const a = fixture();
  const denied = reviewPairing(a.record, serverKey, now, "owner-a", a.userCode, "deny");
  assert.equal(denied.kind, "denied");
  const proof = sign(null, redemptionProof(a.record.id, a.deviceCode), a.privateKey);
  assert.equal(redeemPairing(denied.record, serverKey, now + 1, a.deviceCode, proof).kind, "unavailable");
  assert.equal(redeemPairing(a.record, serverKey, now + 1, a.deviceCode, proof).kind, "unavailable");
});

test("redemption requires device code and private-key possession and is one-use within a serialized state", () => {
  const a = fixture();
  const approved = reviewPairing(a.record, serverKey, now, "owner-a", a.userCode, "approve");
  assert.equal(approved.kind, "approved");
  const proof = sign(null, redemptionProof(a.record.id, a.deviceCode), a.privateKey);
  assert.equal(redeemPairing(approved.record, serverKey, now + 1, "invalid", proof).kind, "unavailable");
  const attacker = generateKeyPairSync("ed25519");
  const badProof = sign(null, redemptionProof(a.record.id, a.deviceCode), attacker.privateKey);
  assert.equal(redeemPairing(approved.record, serverKey, now + 1, a.deviceCode, badProof).kind, "unavailable");
  const redeemed = redeemPairing(approved.record, serverKey, now + 1, a.deviceCode, proof);
  assert.equal(redeemed.kind, "redeemed");
  if (redeemed.kind !== "redeemed") return;
  assert.equal(redeemed.ownerSub, "owner-a");
  assert.equal(redeemPairing(redeemed.record, serverKey, now + 2, a.deviceCode, proof).kind, "unavailable");
  assert.equal(redeemPairing(approved.record, serverKey, now + PAIRING_TTL_MS, a.deviceCode, proof).kind, "unavailable");
});

test("input and key policy reject unsafe aliases, non-Ed25519 keys and weak server keys", () => {
  const a = fixture();
  const key = Buffer.from(a.record.devicePublicKeyDer, "base64");
  assert.throws(() => issuePairing(Buffer.alloc(8), now, "PC", key), /PAIRING_SERVER_KEY_TOO_SHORT/);
  assert.throws(() => issuePairing(serverKey, now, "../PC", key), /INVALID_DEVICE_ALIAS/);
  assert.throws(() => issuePairing(serverKey, now, "PC", Buffer.from("not a key")), /INVALID_DEVICE_KEY/);
  const rsa = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const rsaDer = rsa.publicKey.export({ format: "der", type: "spki" }) as Buffer;
  assert.throws(() => issuePairing(serverKey, now, "PC", rsaDer));
  assert.throws(() => issuePairing(serverKey, -1, "PC", key), /INVALID_PAIRING_CLOCK/);
});


test("signed status only reports owner-approved state, never consumes enrollment",()=>{
  const issued=fixture();
  const id=issued.record.id;
  const proof=sign(null,pairingStatusProof(id,issued.deviceCode),issued.privateKey);
  assert.equal(pairingApprovalState(issued.record,serverKey,now+1,issued.deviceCode,proof),false);
  const reviewed=reviewPairing(issued.record,serverKey,now+2,"owner",issued.userCode,"approve");
  assert.equal(reviewed.kind,"approved");
  assert.equal(pairingApprovalState(reviewed.record,serverKey,now+3,issued.deviceCode,proof),true);
  const wrong=randomBytes(32).toString("base64url");
  assert.equal(pairingApprovalState(reviewed.record,serverKey,now+3,wrong,proof),null);
  const outsider=generateKeyPairSync("ed25519");
  assert.equal(pairingApprovalState(reviewed.record,serverKey,now+3,issued.deviceCode,
    sign(null,pairingStatusProof(id,issued.deviceCode),outsider.privateKey)),null);
  const redemption=sign(null,redemptionProof(id,issued.deviceCode),issued.privateKey);
  assert.equal(pairingApprovalState(reviewed.record,serverKey,now+3,issued.deviceCode,redemption),null);
  assert.equal(pairingApprovalState(reviewed.record,serverKey,now+PAIRING_TTL_MS,
    issued.deviceCode,proof),false);
  assert.equal(redeemPairing(reviewed.record,serverKey,now+4,issued.deviceCode,redemption).kind,"redeemed");
  assert.equal(reviewed.record.state,"approved","status must never consume approval");
});
