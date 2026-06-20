import { MemTraceClient } from "@memtrace/sdk";
import type { FetchLike, MemTraceClientOptions } from "@memtrace/sdk";

export interface CreateDashboardClientOptions {
  baseUrl?: string;
  apiKey?: string | undefined;
  fetch?: FetchLike | undefined;
}

export function resolveApiBaseUrl(rawValue: string | undefined): string {
  const value = rawValue?.trim() ?? "";
  if (value.length === 0) {
    return "";
  }

  if (value.startsWith("//")) {
    throw new Error("VITE_MEMTRACE_API_BASE_URL must not use protocol-relative URLs");
  }

  const withoutTrailingSlash = value.replace(/\/+$/, "");
  if (withoutTrailingSlash.length === 0 && value.startsWith("/")) {
    return "";
  }
  if (withoutTrailingSlash.startsWith("/")) {
    return withoutTrailingSlash;
  }

  let parsed: URL;
  try {
    parsed = new URL(withoutTrailingSlash);
  } catch {
    throw new Error("VITE_MEMTRACE_API_BASE_URL must be same-origin, a relative path, or an absolute HTTP(S) URL");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("VITE_MEMTRACE_API_BASE_URL must use http or https");
  }
  if (parsed.username.length > 0 || parsed.password.length > 0) {
    throw new Error("VITE_MEMTRACE_API_BASE_URL must not include credentials");
  }

  return withoutTrailingSlash;
}

export function createDashboardClient(options: CreateDashboardClientOptions): MemTraceClient {
  const clientOptions: MemTraceClientOptions = {
    baseUrl: options.baseUrl ?? "",
  };
  if (options.apiKey !== undefined) {
    clientOptions.apiKey = options.apiKey;
  }
  if (options.fetch !== undefined) {
    clientOptions.fetch = options.fetch;
  }
  return new MemTraceClient(clientOptions);
}
