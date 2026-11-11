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
  {task:"check_project_files",category:"project",tool:"get_project_presence"},
  {task:"inspect_engine",category:"project",tool:"get_project_engine_status"},
  {task:"inspect_schematic",category:"schematic",tool:"get_project_schematic_counts"},
  {task:"inspect_board",category:"pcb",tool:"get_project_board_counts"},
  {task:"check_board_drc",category:"validation",tool:"get_project_drc_counts"}
] as const;
export type CloudReadTask=(typeof CLOUD_READ_CAPABILITIES)[number]["task"];
export const CLOUD_READ_TASKS = CLOUD_READ_CAPABILITIES.map(c=>c.task) as [
  CloudReadTask, ...CloudReadTask[]
];

type ConfiguredReaderMap = Readonly<Record<CloudReadTask,boolean>>;

/** Not an execution grant: a signed socket alone does not authorize a KiCad action. */
export function listConfiguredCloudCapabilities(
  readers:ConfiguredReaderMap, connectorConnected:boolean, filter?:CloudReadCategory
) {
  return CLOUD_READ_CATEGORIES
    .filter(category=>!filter||category===filter)
    .map(category=>({
      category,
      tools:CLOUD_READ_CAPABILITIES
        .filter(c=>c.category===category&&readers[c.task])
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
