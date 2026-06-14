#!/usr/bin/env bun
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { MemTraceClient } from "@memtrace/sdk";

import { loadMcpConfig } from "./config";
import { createMemTraceTools, toolTextResult, toolsByName } from "./tools";

export function unknownToolResult(toolName: string): Record<string, unknown> {
  return toolTextResult(`Unknown MemTrace tool: ${toolName}`, true) as unknown as Record<string, unknown>;
}

export async function createMemTraceMcpServer(): Promise<Server> {
  const config = loadMcpConfig();
  const client = new MemTraceClient(config);
  const tools = createMemTraceTools(client);
  const toolMap = toolsByName(tools);

  const server = new Server(
    { name: "@memtrace/mcp-server", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: tools.map((tool) => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema,
    })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const tool = toolMap.get(request.params.name);
    if (tool === undefined) {
      return unknownToolResult(request.params.name);
    }
    const args = typeof request.params.arguments === "object" && request.params.arguments !== null
      ? (request.params.arguments as Record<string, unknown>)
      : {};
    return (await tool.handler(args)) as unknown as Record<string, unknown>;
  });

  return server;
}

export async function runStdioServer(): Promise<void> {
  const server = await createMemTraceMcpServer();
  await server.connect(new StdioServerTransport());
}

if (import.meta.main) {
  runStdioServer().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Failed to start @memtrace/mcp-server: ${message}`);
    process.exit(1);
  });
}
