import {fromJsonSchema, type McpServer} from "@modelcontextprotocol/server";
import {
  CLOUD_DIRECT_TOOL_REVISION,
  CLOUD_DIRECT_TOOLS,
  CLOUD_PROJECT_ID_SCHEMA
} from "./cloud-direct-tool-contracts.generated.js";

export type DirectCloudTool = (typeof CLOUD_DIRECT_TOOLS)[number];
type DirectResult = Readonly<{
  content: Array<{type:"text";text:string}>;
  structuredContent: object;
  isError?: boolean;
  _meta?: Record<string, unknown>;
}>;

/** Static, reviewed tool names/schemas; no access to a local filesystem. */
export function registerDirectCloudMcpTools(
  server:McpServer,
  execute:(tool:DirectCloudTool,args:Record<string,unknown>)=>Promise<DirectResult>
):void{
  for(const tool of CLOUD_DIRECT_TOOLS){
    const inputSchema={
      ...tool.inputSchema,
      properties:{
        ...tool.inputSchema.properties,
        project_id:CLOUD_PROJECT_ID_SCHEMA
      }
    };
    server.registerTool(tool.name,{
      description:tool.description,
      inputSchema:fromJsonSchema<Record<string,unknown>>(
        inputSchema as Parameters<typeof fromJsonSchema>[0]),
      annotations:tool.annotations,
      _meta:{
        securitySchemes:tool.securitySchemes.map(scheme=>({
          type:scheme.type,scopes:[...scheme.scopes]
        })),
        "com.kicad-mcp-pro.contractRevision":CLOUD_DIRECT_TOOL_REVISION,
        "com.kicad-mcp-pro.maturity":tool.maturity
      }
    },args=>execute(tool,args));
  }
}
