import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";
import Docker from "dockerode";
import { z } from "zod";
import { Readable } from "stream";

// Initialize Dockerode to connect to local Docker daemon
// Works on Unix sockets, Windows named pipes, or custom DOCKER_HOST env configurations
const docker = new Docker();

// Utility to stream Docker outputs to a single string
const streamToString = (stream: Readable): Promise<string> => {
  return new Promise((resolve, reject) => {
    let data = "";
    stream.on("data", (chunk) => {
      data += chunk.toString("utf8");
    });
    stream.on("end", () => resolve(data));
    stream.on("error", (err) => reject(err));
  });
};

// Initialize MCP Server
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

// Define Schemas for Tool Inputs using Zod
const ListContainersSchema = z.object({
  all: z.boolean().optional().default(false),
  limit: z.number().optional(),
  filters: z.string().optional().describe("JSON string filtering condition (e.g., '{\"status\":[\"running\"]}')"),
});

const RunContainerSchema = z.object({
  image: z.string().describe("The Docker image to run (e.g., 'nginx:latest')"),
  name: z.string().optional().describe("Optional container name"),
  cmd: z.array(z.string()).optional().describe("Commands to pass to the container"),
  env: z.array(z.string()).optional().describe("Environment variables in KEY=VALUE format"),
  ports: z.record(z.string(), z.string()).optional().describe("Port mappings, format: {'80/tcp': '8080'}"),
  binds: z.array(z.string()).optional().describe("Volume bindings, format: ['/host/path:/container/path']"),
  networkMode: z.string().optional().describe("Network mode (e.g., 'bridge', 'host')"),
});

const ContainerActionSchema = z.object({
  containerId: z.string().describe("The ID or name of the target container"),
});

const ExecCommandSchema = z.object({
  containerId: z.string().describe("The ID or name of the running container"),
  cmd: z.array(z.string()).describe("Command split into array parts (e.g., ['ls', '-la'])"),
  attachStdout: z.boolean().optional().default(true),
  attachStderr: z.boolean().optional().default(true),
  user: z.string().optional().describe("User context to run command inside container"),
  workingDir: z.string().optional().describe("Working directory inside the container"),
});

const PullImageSchema = z.object({
  image: z.string().describe("Image name with tag (e.g., 'redis:alpine' or 'postgres:15')"),
});

const RemoveImageSchema = z.object({
  imageId: z.string().describe("The ID or name of the image to remove"),
  force: z.boolean().optional().default(false),
});

const CreateNetworkSchema = z.object({
  name: z.string().describe("Name of the docker network"),
  driver: z.string().optional().default("bridge").describe("Driver type (bridge, overlay, macvlan, etc.)"),
});

const CreateVolumeSchema = z.object({
  name: z.string().describe("Name of the docker volume"),
  driver: z.string().optional().default("local"),
  driverOpts: z.record(z.string(), z.string()).optional(),
});

const GetLogsSchema = z.object({
  containerId: z.string().describe("The ID or name of the container"),
  tail: z.number().optional().default(100).describe("Number of lines to show from the end of the logs"),
  stdout: z.boolean().optional().default(true),
  stderr: z.boolean().optional().default(true),
  timestamps: z.boolean().optional().default(false).describe("Show timestamps in the logs"),
});

// Register Tool Definitions
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "list_containers",
        description: "List Docker containers with statuses, ports, names, and IDs.",
        inputSchema: {
          type: "object",
          properties: {
            all: { type: "boolean", description: "Show all containers (default shows only running)" },
            limit: { type: "number", description: "Limit number of returned containers" },
            filters: { type: "string", description: "JSON encoded filters (e.g. '{\"status\": [\"exited\"]}')" },
          },
        },
      },
      {
        name: "run_container",
        description: "Create and start a new Docker container with rich configurations.",
        inputSchema: {
          type: "object",
          required: ["image"],
          properties: {
            image: { type: "string", description: "Docker image to run" },
            name: { type: "string", description: "Optional name of the container" },
            cmd: { type: "array", items: { type: "string" }, description: "Command array" },
            env: { type: "array", items: { type: "string" }, description: "Environment variables like 'KEY=VALUE'" },
            ports: { type: "object", description: "Port bindings, key is port/protocol inside container, value is host port (e.g., {'80/tcp': '8080'})" },
            binds: { type: "array", items: { type: "string" }, description: "Volume mapping ('/host:/container')" },
            networkMode: { type: "string", description: "Network configuration ('bridge', 'host', etc.)" },
          },
        },
      },
      {
        name: "stop_container",
        description: "Stop a running Docker container.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "ID or name of the container" },
          },
        },
      },
      {
        name: "start_container",
        description: "Start an existing stopped Docker container.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "ID or name of the container" },
          },
        },
      },
      {
        name: "restart_container",
        description: "Restart an existing Docker container.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "ID or name of the container" },
          },
        },
      },
      {
        name: "remove_container",
        description: "Remove an existing container. Will force stop if container is running.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "ID or name of the container" },
          },
        },
      },
      {
        name: "inspect_container",
        description: "Inspect detailed low-level configuration of a container.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "ID or name of the container" },
          },
        },
      },
      {
        name: "get_container_logs",
        description: "Fetch stdout and stderr logs from a container.",
        inputSchema: {
          type: "object",
          required: ["containerId"],
          properties: {
            containerId: { type: "string", description: "Container ID or name" },
            tail: { type: "number", description: "Number of logs lines to return" },
            stdout: { type: "boolean", description: "Include stdout stream" },
            stderr: { type: "boolean", description: "Include stderr stream" },
            timestamps: { type: "boolean", description: "Include timestamps" },
          },
        },
      },
      {
        name: "execute_command",
        description: "Execute a command inside a running Docker container and get output.",
        inputSchema: {
          type: "object",
          required: ["containerId", "cmd"],
          properties: {
            containerId: { type: "string", description: "Container ID or name" },
            cmd: { type: "array", items: { type: "string" }, description: "Command to execute as an array" },
            attachStdout: { type: "boolean", description: "Capture stdout" },
            attachStderr: { type: "boolean", description: "Capture stderr" },
            user: { type: "string", description: "User to execute command as" },
            workingDir: { type: "string", description: "Working directory context" },
          },
        },
      },
      {
        name: "list_images",
        description: "List available Docker images locally.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "pull_image",
        description: "Pull an image from Docker Hub or registry.",
        inputSchema: {
          type: "object",
          required: ["image"],
          properties: {
            image: { type: "string", description: "Name of the image (e.g. node:18-alpine)" },
          },
        },
      },
      {
        name: "remove_image",
        description: "Remove a local Docker image.",
        inputSchema: {
          type: "object",
          required: ["imageId"],
          properties: {
            imageId: { type: "string", description: "Image ID or Tag to remove" },
            force: { type: "boolean", description: "Force removal of the image" },
          },
        },
      },
      {
        name: "list_networks",
        description: "List Docker networks.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "create_network",
        description: "Create a new Docker network.",
        inputSchema: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string", description: "Network name" },
            driver: { type: "string", description: "Network driver" },
          },
        },
      },
      {
        name: "list_volumes",
        description: "List Docker volumes.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "create_volume",
        description: "Create a new Docker volume.",
        inputSchema: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string", description: "Volume name" },
            driver: { type: "string", description: "Volume driver" },
            driverOpts: { type: "object", description: "Driver key-value options" },
          },
        },
      },
      {
        name: "get_system_info",
        description: "Get general Docker daemon and system statistics/information.",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
    ],
  };
});

// Implement Tool Handler Actions
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "list_containers": {
        const validated = ListContainersSchema.parse(args);
        const options: any = { all: validated.all };
        if (validated.limit) options.limit = validated.limit;
        if (validated.filters) options.filters = JSON.parse(validated.filters);

        const containers = await docker.listContainers(options);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(containers, null, 2),
            },
          ],
        };
      }

      case "run_container": {
        const validated = RunContainerSchema.parse(args);

        // Map simplified port input to Dockerode ExposedPorts and PortBindings structures
        const exposedPorts: Record<string, {}> = {};
        const portBindings: Record<string, any[]> = {};

        if (validated.ports) {
          for (const [containerPort, hostPort] of Object.entries(validated.ports)) {
            exposedPorts[containerPort] = {};
            portBindings[containerPort] = [{ HostPort: hostPort }];
          }
        }

        const createOptions: Docker.ContainerCreateOptions = {
          Image: validated.image,
          name: validated.name,
          Cmd: validated.cmd,
          Env: validated.env,
          ExposedPorts: exposedPorts,
          HostConfig: {
            PortBindings: portBindings,
            Binds: validated.binds,
            NetworkMode: validated.networkMode,
          },
        };

        const container = await docker.createContainer(createOptions);
        await container.start();
        const inspection = await container.inspect();

        return {
          content: [
            {
              type: "text",
              text: `Successfully initialized and started container!\nID: ${container.id}\nName: ${inspection.Name}\nStatus: ${inspection.State.Status}`,
            },
          ],
        };
      }

      case "stop_container": {
        const validated = ContainerActionSchema.parse(args);
        const container = docker.getContainer(validated.containerId);
        await container.stop();
        return {
          content: [{ type: "text", text: `Container '${validated.containerId}' has been successfully stopped.` }],
        };
      }

      case "start_container": {
        const validated = ContainerActionSchema.parse(args);
        const container = docker.getContainer(validated.containerId);
        await container.start();
        return {
          content: [{ type: "text", text: `Container '${validated.containerId}' was successfully started.` }],
        };
      }

      case "restart_container": {
        const validated = ContainerActionSchema.parse(args);
        const container = docker.getContainer(validated.containerId);
        await container.restart();
        return {
          content: [{ type: "text", text: `Container '${validated.containerId}' successfully restarted.` }],
        };
      }

      case "remove_container": {
        const validated = ContainerActionSchema.parse(args);
        const container = docker.getContainer(validated.containerId);
        try {
          // Attempt to remove directly
          await container.remove({ force: true });
        } catch (err: any) {
          // Fallback manual stopping if required
          await container.stop().catch(() => {});
          await container.remove();
        }
        return {
          content: [{ type: "text", text: `Container '${validated.containerId}' removed successfully.` }],
        };
      }

      case "inspect_container": {
        const validated = ContainerActionSchema.parse(args);
        const container = docker.getContainer(validated.containerId);
        const details = await container.inspect();
        return {
          content: [{ type: "text", text: JSON.stringify(details, null, 2) }],
        };
      }

      case "get_container_logs": {
        const validated = GetLogsSchema.parse(args);
        const container = docker.getContainer(validated.containerId);

        const logStream = await container.logs({
          follow: false,
          stdout: validated.stdout,
          stderr: validated.stderr,
          tail: validated.tail,
          timestamps: validated.timestamps,
        });

        const logs = logStream.toString("utf8");
        // Docker logs streams usually prefixed with dynamic headers (Multiplexing)
        // clean up the binary headers for readability in text format
        const cleanLogs = logs.replace(/[\x00-\x1F\x7F-\x9F]/g, "");

        return {
          content: [{ type: "text", text: cleanLogs || "(No logs found or stdout is closed)" }],
        };
      }

      case "execute_command": {
        const validated = ExecCommandSchema.parse(args);
        const container = docker.getContainer(validated.containerId);

        const execInstance = await container.exec({
          Cmd: validated.cmd,
          AttachStdout: validated.attachStdout,
          AttachStderr: validated.attachStderr,
          User: validated.user,
          WorkingDir: validated.workingDir,
        });

        const stream = await execInstance.start({});
        // Wait for output aggregation
        const rawOutput = await streamToString(stream);
        const cleanOutput = rawOutput.replace(/[\x00-\x1F\x7F-\x9F]/g, "");

        return {
          content: [
            {
              type: "text",
              text: cleanOutput || "Command completed with empty output stream.",
            },
          ],
        };
      }

      case "list_images": {
        const images = await docker.listImages();
        return {
          content: [{ type: "text", text: JSON.stringify(images, null, 2) }],
        };
      }

      case "pull_image": {
        const validated = PullImageSchema.parse(args);
        const stream = await docker.pull(validated.image);

        // Await full registry stream pull complete event
        await new Promise((resolve, reject) => {
          docker.modem.followProgress(stream, (err, res) => (err ? reject(err) : resolve(res)));
        });

        return {
          content: [{ type: "text", text: `Successfully pulled image: '${validated.image}'` }],
        };
      }

      case "remove_image": {
        const validated = RemoveImageSchema.parse(args);
        const image = docker.getImage(validated.imageId);
        const output = await image.remove({ force: validated.force });
        return {
          content: [{ type: "text", text: JSON.stringify(output, null, 2) }],
        };
      }

      case "list_networks": {
        const networks = await docker.listNetworks();
        return {
          content: [{ type: "text", text: JSON.stringify(networks, null, 2) }],
        };
      }

      case "create_network": {
        const validated = CreateNetworkSchema.parse(args);
        const network = await docker.createNetwork({
          Name: validated.name,
          Driver: validated.driver,
        });
        return {
          content: [{ type: "text", text: `Created network '${validated.name}' with ID: ${network.id}` }],
        };
      }

      case "list_volumes": {
        const volumes = await docker.listVolumes();
        return {
          content: [{ type: "text", text: JSON.stringify(volumes, null, 2) }],
        };
      }

      case "create_volume": {
        const validated = CreateVolumeSchema.parse(args);
        const volume = await docker.createVolume({
          Name: validated.name,
          Driver: validated.driver,
          DriverOpts: validated.driverOpts,
        });
        return {
          content: [{ type: "text", text: `Created volume: ${volume.name}` }],
        };
      }

      case "get_system_info": {
        const systemInfo = await docker.info();
        const version = await docker.version();
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                {
                  versionInfo: version,
                  daemonInfo: systemInfo,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      default:
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool execution query: ${name}`);
    }
  } catch (error: any) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    return {
      isError: true,
      content: [
        {
          type: "text",
          text: `Docker error while executing '${name}': ${errorMessage}`,
        },
      ],
    };
  }
});

// Run server using stdio transport
async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Docker MCP Server running on Standard IO");
}

run().catch((error) => {
  console.error("Fatal initialization error in Docker MCP server:", error);
  process.exit(1);
});
