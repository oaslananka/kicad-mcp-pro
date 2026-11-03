import { bench, describe } from "vitest";
import { generateKeyPairSync, sign } from "node:crypto";
import {
  issuePairing, redeemPairing, redemptionProof, reviewPairing
} from "../src/device-pairing.js";

const serverKey = Buffer.alloc(32, 7);
const now = 1_780_000_000_000;
const device = generateKeyPairSync("ed25519");
const publicKeyDer = device.publicKey.export({ format: "der", type: "spki" }) as Buffer;

const issued = issuePairing(serverKey, now, "My KiCad PC", publicKeyDer);
const approved = reviewPairing(issued.record, serverKey, now + 1_000, "owner-1", issued.userCode, "approve");
if (approved.kind !== "approved") throw new Error("fixture pairing was not approved");
const signature = sign(null, redemptionProof(approved.record.id, issued.deviceCode), device.privateKey);

describe("device pairing", () => {
  bench("issuePairing", () => {
    issuePairing(serverKey, now, "My KiCad PC", publicKeyDer);
  });

  bench("reviewPairing (approve with valid code)", () => {
    reviewPairing(issued.record, serverKey, now + 1_000, "owner-1", issued.userCode, "approve");
  });

  bench("reviewPairing (invalid code)", () => {
    reviewPairing(issued.record, serverKey, now + 1_000, "owner-1", "ABCDEF-GHJKMN", "approve");
  });

  bench("redeemPairing (ed25519 signature)", () => {
    redeemPairing(approved.record, serverKey, now + 2_000, issued.deviceCode, signature);
  });
});
