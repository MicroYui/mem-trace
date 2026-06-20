#!/usr/bin/env node
import { spawnSync } from "node:child_process";

const baseUrl = process.env.MEMTRACE_WEB_SCREENSHOT_URL ?? "http://127.0.0.1:5173";
const outputPrefix = process.env.MEMTRACE_WEB_SCREENSHOT_PREFIX ?? "/tmp/memtrace-web-showcase";

const routes = [
  ["/showcase", "showcase"],
  ["/", "overview"],
  ["/runs/run_showcase_bun_recovery", "run"],
  ["/access/acc_showcase_gate", "access"],
  ["/benchmark", "benchmark"],
  ["/memories", "memories"],
  ["/ops", "ops"],
];

const viewports = [
  ["desktop", { width: 1440, height: 1000 }],
  ["mobile", { width: 390, height: 1200 }],
];

for (const [viewportName, viewport] of viewports) {
  for (const [route, label] of routes) {
    const url = new URL(route, baseUrl).toString();
    const path = `${outputPrefix}-${label}-${viewportName}.png`;
    const result = spawnSync("playwright", [
      "screenshot",
      "--full-page",
      `--viewport-size=${viewport.width},${viewport.height}`,
      url,
      path,
    ], { encoding: "utf8" });
    if (result.status !== 0) {
      console.error("Unable to capture screenshots.");
      console.error("Start the web app, then run:");
      console.error("MEMTRACE_WEB_SCREENSHOT_URL=http://127.0.0.1:5173 npm exec --yes --package playwright -- node apps/web/scripts/capture-showcase-screenshots.mjs");
      console.error(result.stderr.trim() || result.stdout.trim() || "playwright screenshot failed");
      process.exit(result.status ?? 1);
    }
  }
}

console.log(`showcase screenshots written to ${outputPrefix}-*.png`);
