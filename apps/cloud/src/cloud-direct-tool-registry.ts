import {fromJsonSchema, type McpServer} from "@modelcontextprotocol/server";
import {CLOUD_DIRECT_TOOLS} from "./cloud-direct-tool-contracts.generated.js";

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
        // Cloud resolves only opaque, owner-granted project identifiers.
        project_id:{type:"string",format:"uuid",
          description:"Granted Cloud project UUID; optional when exactly one is accessible"}
      }
    };
    const isRead=tool.accessMode==="readonly";
    server.registerTool(tool.name,{
      description:tool.description,
      inputSchema:fromJsonSchema<Record<string,unknown>>(
        inputSchema as Parameters<typeof fromJsonSchema>[0]),
      annotations:{
        readOnlyHint:isRead,destructiveHint:!isRead,
        idempotentHint:isRead,openWorldHint:false
      },
      _meta:{securitySchemes:[{
        type:"oauth2",scopes:isRead?["projects:read"]:["projects:read","projects:write"]
      }]}
    },args=>execute(tool,args));
  }
}
