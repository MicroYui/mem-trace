import { describe, expect, test } from "bun:test";
import { fileURLToPath } from "node:url";

import { MCP_CONFIG_TEMPLATES } from "../src/templates";

const SECRET_MARKERS = [
  "sk-",
  "Bearer ",
  "hunter2",
  "plain-token",
  "secret-token",
  "Authorization",
  "password",
  "raw_payload_ref",
];

function repoPath(relativePath: string): string {
  return fileURLToPath(new URL(`../../../${relativePath}`, import.meta.url));
}

async function readTemplate(relativePath: string): Promise<unknown> {
  return JSON.parse(await Bun.file(repoPath(relativePath)).text()) as unknown;
}

function stringify(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function assertTemplateUsesEnvPlaceholders(template: unknown): void {
  const text = stringify(template);
  expect(text).toContain("MEMTRACE_BASE_URL");
  expect(text).toContain("MEMTRACE_API_KEY");
  expect(text).toContain("${MEMTRACE_BASE_URL}");
  expect(text).toContain("${MEMTRACE_API_KEY}");
  expect(text).toContain("packages/mcp-server/src/server.ts");
}

function assertTemplateHasExactLocalDevShape(template: unknown): void {
  expect(template).toEqual({
    mcpServers: {
      memtrace: {
        command: "bun",
        args: ["packages/mcp-server/src/server.ts"],
        env: {
          MEMTRACE_BASE_URL: "${MEMTRACE_BASE_URL}",
          MEMTRACE_API_KEY: "${MEMTRACE_API_KEY}",
        },
      },
    },
  });
}

function assertTemplateHasNoRealSecrets(template: unknown): void {
  const text = stringify(template);
  for (const marker of SECRET_MARKERS) {
    expect(text).not.toContain(marker);
  }
}

describe("MCP config templates", () => {
  test("exports Claude Code and Cursor config templates with env placeholders", () => {
    expect(Object.keys(MCP_CONFIG_TEMPLATES).sort()).toEqual(["claudeCode", "cursor"]);
    for (const template of Object.values(MCP_CONFIG_TEMPLATES)) {
      assertTemplateHasExactLocalDevShape(template);
      assertTemplateUsesEnvPlaceholders(template);
      assertTemplateHasNoRealSecrets(template);
    }
  });

  test("example JSON template files match exported templates", async () => {
    const claudeCode = await readTemplate("examples/mcp/claude-code.json");
    const cursor = await readTemplate("examples/mcp/cursor.json");

    expect(claudeCode).toEqual(MCP_CONFIG_TEMPLATES.claudeCode);
    expect(cursor).toEqual(MCP_CONFIG_TEMPLATES.cursor);
  });
});
