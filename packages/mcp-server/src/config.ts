export interface McpConfig {
  baseUrl: string;
  apiKey?: string;
}

export class McpConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "McpConfigError";
  }
}

function cleanEnvValue(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed.length === 0 ? undefined : trimmed;
}

export function loadMcpConfig(env: Record<string, string | undefined> = process.env): McpConfig {
  const baseUrl = cleanEnvValue(env.MEMTRACE_BASE_URL);
  if (baseUrl === undefined) {
    throw new McpConfigError("MEMTRACE_BASE_URL is required for @memtrace/mcp-server");
  }

  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    throw new McpConfigError("MEMTRACE_BASE_URL must be a valid URL");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new McpConfigError("MEMTRACE_BASE_URL must use http or https");
  }
  if (url.username.length > 0 || url.password.length > 0) {
    throw new McpConfigError("MEMTRACE_BASE_URL must not include credentials");
  }

  const apiKey = cleanEnvValue(env.MEMTRACE_API_KEY);
  return apiKey === undefined ? { baseUrl } : { baseUrl, apiKey };
}
