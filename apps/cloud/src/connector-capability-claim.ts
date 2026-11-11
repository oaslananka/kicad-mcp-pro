import {z} from "zod";

/**
 * A bounded, optional diagnostic claim from a device. It is not an owner
 * authorization, a signed attestation of installed code, or an execution
 * grant. An absent claim retains the v1 Connector compatibility path.
 */
export const ConnectorCapabilityClaimSchema=z.strictObject({
  schemaVersion:z.literal("1.0.0"),
  catalogRevision:z.string().regex(/^[0-9a-f]{64}$/),
  operations:z.array(z.enum([
    "project_summary","run_drc","project_worker_inspection",
    "project_board_counts","project_schematic_counts"
  ])).max(5).refine(items=>new Set(items).size===items.length,"duplicate operation")
});

export type ConnectorCapabilityClaim=z.infer<typeof ConnectorCapabilityClaimSchema>;

export function parseCapabilityClaim(raw:unknown):ConnectorCapabilityClaim|null {
  if(raw===undefined)return null; // Legacy v1 Connector.
  const result=ConnectorCapabilityClaimSchema.safeParse(raw);
  return result.success?result.data:null;
}

/**
 * A claim may narrow an existing independently granted operation, never
 * grant one. The separate OAuth/project/owner and signed-transport checks
 * remain mandatory at dispatch.
 */
export function allowsClaimedRead(claim:ConnectorCapabilityClaim|null,operation:string):boolean{
  return claim===null||claim.operations.some(candidate=>candidate===operation);
}
