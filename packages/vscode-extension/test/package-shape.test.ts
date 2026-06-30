import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageDir = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));

describe("memtrace-vscode extension shape", () => {
  test("is a well-formed VS Code extension manifest", () => {
    expect(pkg.private).toBe(true);
    expect(pkg.license).toBe("Apache-2.0");
    expect(pkg.engines.vscode).toBeDefined();
    expect(pkg.main).toBe("./src/extension.ts");
    expect(pkg.repository.url).toBe("git+https://github.com/MicroYui/mem-trace.git");
  });

  test("contributes thin /v1-backed commands and config", () => {
    const commandIds = pkg.contributes.commands.map((c: { command: string }) => c.command);
    expect(commandIds).toEqual(
      expect.arrayContaining([
        "memtrace.retrieveContext",
        "memtrace.showRunTimeline",
        "memtrace.inspectAccess",
      ]),
    );
    expect(pkg.contributes.configuration.properties["memtrace.baseUrl"]).toBeDefined();
    expect(pkg.contributes.configuration.properties["memtrace.apiKey"]).toBeDefined();
  });

  test("is a thin layer over the SDK, not a runtime reimplementation", () => {
    expect(pkg.dependencies["@memtrace/sdk"]).toBe("workspace:*");
    const source = readFileSync(join(packageDir, "src", "extension.ts"), "utf8");
    // Must go through the SDK HTTP client; must not import the Python runtime or
    // embed real secrets.
    expect(source).toContain('from "@memtrace/sdk"');
    expect(source).toContain("MemTraceClient");
    expect(source).not.toMatch(/sk-[a-zA-Z0-9]{8,}/);
  });

  test("manifest ships no secrets", () => {
    expect(pkg.contributes.configuration.properties["memtrace.apiKey"].default).toBe("");
    expect(JSON.stringify(pkg)).not.toMatch(/sk-[a-zA-Z0-9]{8,}/);
  });
});
