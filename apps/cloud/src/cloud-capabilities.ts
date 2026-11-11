import type {ConnectorCapabilityClaim} from "./connector-capability-claim.js";

/** Cloud's actually callable, owner-scoped pilot capabilities.
 *
 * This is a narrow Cloud exposure layer, not a copy of the local 388-tool catalog.
 * Each entry must have a registered, executable Cloud MCP handler. Future local
 * capability adapters must use the same source of truth after verification.
 */
export const CLOUD_READ_CATEGORIES = [
  "project", "schematic", "pcb", "validation"
] as const;
export type CloudReadCategory = (typeof CLOUD_READ_CATEGORIES)[number];

export const CLOUD_READ_CAPABILITIES = [
  {task:"check_project_files",category:"project",tool:"get_project_presence",operation:"project_summary"},
  {task:"inspect_engine",category:"project",tool:"get_project_engine_status",operation:"project_worker_inspection"},
  {task:"inspect_schematic",category:"schematic",tool:"get_project_schematic_counts",operation:"project_schematic_counts"},
  {task:"inspect_board",category:"pcb",tool:"get_project_board_counts",operation:"project_board_counts"},
  {task:"check_board_drc",category:"validation",tool:"get_project_drc_counts",operation:"run_drc"}
] as const;
export type CloudReadTask=(typeof CLOUD_READ_CAPABILITIES)[number]["task"];
export const CLOUD_READ_TASKS = CLOUD_READ_CAPABILITIES.map(c=>c.task) as [
  CloudReadTask, ...CloudReadTask[]
];

type ConfiguredReaderMap = Readonly<Record<CloudReadTask,boolean>>;

/** A signed Connector claim only narrows configured operations; it never grants any. */
export function configuredReadersForClaim(
  readers:ConfiguredReaderMap,
  claim:Pick<ConnectorCapabilityClaim,"operations">|null|undefined
):ConfiguredReaderMap {
  const advertised=claim===null||claim===undefined?null:new Set(claim.operations);
  return Object.fromEntries(CLOUD_READ_CAPABILITIES.map(capability=>[
    capability.task,
    readers[capability.task] && (advertised===null||advertised.has(capability.operation))
  ])) as Record<CloudReadTask,boolean>;
}


/** Not an execution grant: a signed socket alone does not authorize a KiCad action. */
export function listConfiguredCloudCapabilities(
  readers:ConfiguredReaderMap, connectorConnected:boolean, filter?:CloudReadCategory,
  claim?:Pick<ConnectorCapabilityClaim,"operations">|null
) {
  const supported=configuredReadersForClaim(readers,claim);
  return CLOUD_READ_CATEGORIES
    .filter(category=>!filter||category===filter)
    .map(category=>({
      category,
      tools:CLOUD_READ_CAPABILITIES
        .filter(c=>c.category===category&&supported[c.task])
        .map(c=>({
          task:c.task,
          tool:c.tool,
          mode:"readonly" as const,
          canExecuteNow:false as const,
          state:connectorConnected?"owner_session_required" as const:"device_not_connected" as const,
          requiresOwnerSession:true as const
        }))
    }))
    .filter(group=>group.tools.length>0);
}
