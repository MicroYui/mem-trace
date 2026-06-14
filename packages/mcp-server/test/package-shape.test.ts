import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageDir = dirname(dirname(fileURLToPath(import.meta.url)));
const pkg = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));

describe("@memtrace/mcp-server package shape", () => {
  test("keeps explicit private source-entry release metadata", () => {
    expect(pkg.private).toBe(true);
    expect(pkg.description).toContain("MCP server");
    expect(pkg.license).toBe("Apache-2.0");
    expect(pkg.repository.type).toBe("git");
    expect(pkg.repository.url).toBe("git+https://github.com/MicroYui/mem-trace.git");
    expect(pkg.homepage).toBe("https://github.com/MicroYui/mem-trace#readme");
    expect(pkg.bugs.url).toBe("https://github.com/MicroYui/mem-trace/issues");
    expect(pkg.keywords).toEqual(expect.arrayContaining(["agent-memory", "mcp", "memtrace"]));
    expect(pkg.main).toBe("./src/index.ts");
    expect(pkg.types).toBe("./src/index.ts");
    expect(pkg.exports).toEqual({
      ".": {
        types: "./src/index.ts",
        import: "./src/index.ts",
      },
      "./server": {
        types: "./src/server.ts",
        import: "./src/server.ts",
      },
    });
    expect(pkg.bin).toEqual({ "memtrace-mcp-server": "./src/server.ts" });
    expect(pkg.engines).toEqual({ bun: ">=1.3.14" });
    expect(pkg.files).toEqual(["src"]);

    const serverSource = readFileSync(join(packageDir, "src", "server.ts"), "utf8");
    expect(serverSource.split(/\r?\n/, 1)[0]).toBe("#!/usr/bin/env bun");
  });

  test("does not package generated artifacts or internal-only fixtures", () => {
    const serializedFiles = JSON.stringify(pkg.files);
    for (const forbidden of ["dist", "node_modules", "test", "*.tsbuildinfo", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"]) {
      expect(serializedFiles).not.toContain(forbidden);
    }
  });
});
