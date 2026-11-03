import { createRemoteJWKSet, jwtVerify } from "jose";
import type { JWTVerifyGetKey } from "jose";
import type { Config } from "./config.js";

export interface Actor {
  sub: string;
  clientId: string;
  scopes: ReadonlySet<string>;
  issuedAt: number;
}
export type Verifier = (value: string) => Promise<Actor>;

export function createVerifier(config: Pick<Config, "jwksUrl" | "issuer" | "audience">,
  jwks: JWTVerifyGetKey = createRemoteJWKSet(new URL(config.jwksUrl), { timeoutDuration: 5000 })): Verifier {
  return async (token: string) => {
    const { payload } = await jwtVerify(token, jwks, {
      issuer: config.issuer, audience: config.audience,
      algorithms: ["RS256", "ES256", "PS256"], clockTolerance: 5
    });
    if (payload.cnf !== undefined) throw new Error("Proof-of-possession bound access tokens require DPoP verification");
    if (typeof payload.iat !== "number" || !Number.isSafeInteger(payload.iat) || payload.iat > Math.floor(Date.now()/1000)+5) throw new Error("Token missing valid issuance time");
    if (typeof payload.exp !== "number") throw new Error("Token missing expiry");
    if (typeof payload.sub !== "string" || payload.sub.length < 1) throw new Error("Token missing subject");
    const scope = typeof payload.scope === "string" ? payload.scope : "";
    const scopes = new Set(scope.split(/\s+/).filter(Boolean));
    if (!scopes.has("projects:read")) throw new Error("Missing projects:read permission");
    if (typeof payload.client_id !== "string" || !payload.client_id) throw new Error("Token missing client_id");
    return {
      sub: payload.sub,
      clientId: payload.client_id,
      scopes,
      issuedAt: payload.iat
    };
  };
}
