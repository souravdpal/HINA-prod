import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  {
    name: "docker-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "calculate",
        description: "Perform basic arithmetic operations inside the container environment",
        inputSchema: {
          type: "object",
          properties: {
            operation: {
              type: "string",
              enum: ["add", "subtract", "multiply", "divide"],
              description: "The arithmetic operation to perform"
            },
            a: { type: "number" },
            b: { type: "number" }
          },
          required: ["operation", "a", "b"]
        },
      },
      {
        name: "get_container_system_info",
        description: "Get details about the running Docker container container OS, arch, and uptime",
        inputSchema: {
          type: "object",
          properties: {}
        }
      }
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "calculate") {
    const { operation, a, b } = args as { operation: string; a: number; b: number };
    let result: number;
    switch (operation) {
      case "add": result = a + b; break;
      case "subtract": result = a - b; break;
      case "multiply": result = a * b; break;
      case "divide":
        if (b === 0) {
          return {
            isError: true,
            content: [{ type: "text", text: "Error: Division by zero" }]
          };
        }
        result = a / b;
        break;
      default:
        return {
          isError: true,
          content: [{ type: "text", text: `Unknown operation: ${operation}` }]
        };
    }
    return {
      content: [{ type: "text", text: `Result: ${result}` }]
    };
  }

  if (name === "get_container_system_info") {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            platform: process.platform,
            arch: process.arch,
            nodeVersion: process.version,
            uptimeSeconds: Math.floor(process.uptime()),
            memoryUsage: process.memoryUsage(),
          }, null, 2),
        },
      ],
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Docker MCP Server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error in main():", error);
  process.exit(1);
});
