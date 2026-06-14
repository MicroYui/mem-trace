export interface LocalMcpServerTemplate {
  command: "bun";
  args: string[];
  env: {
    MEMTRACE_BASE_URL: "${MEMTRACE_BASE_URL}";
    MEMTRACE_API_KEY: "${MEMTRACE_API_KEY}";
  };
}

export interface McpConfigTemplate {
  mcpServers: {
    memtrace: LocalMcpServerTemplate;
  };
}

const LOCAL_MEMTRACE_SERVER: LocalMcpServerTemplate = {
  command: "bun",
  args: ["packages/mcp-server/src/server.ts"],
  env: {
    MEMTRACE_BASE_URL: "${MEMTRACE_BASE_URL}",
    MEMTRACE_API_KEY: "${MEMTRACE_API_KEY}",
  },
};

function localTemplate(): McpConfigTemplate {
  return {
    mcpServers: {
      memtrace: { ...LOCAL_MEMTRACE_SERVER, args: [...LOCAL_MEMTRACE_SERVER.args], env: { ...LOCAL_MEMTRACE_SERVER.env } },
    },
  };
}

export const MCP_CONFIG_TEMPLATES = {
  claudeCode: localTemplate(),
  cursor: localTemplate(),
} as const;
