import { describe, expect, test } from "bun:test";
import { dashboardQueryKeys } from "../src/api/queries";

describe("dashboard query keys", () => {
  test("names every existing read-only dashboard API surface with stable inputs", () => {
    expect(dashboardQueryKeys.dashboardTables("ws_1")).toEqual(["dashboard-tables", "ws_1"]);
    expect(dashboardQueryKeys.observabilitySummary({ workspaceId: "ws_1", runId: "run_1" })).toEqual([
      "observability-summary",
      "ws_1",
      "run_1",
    ]);
    expect(dashboardQueryKeys.runTimeline("run_1")).toEqual(["run-timeline", "run_1"]);
    expect(dashboardQueryKeys.stateTree("run_1")).toEqual(["state-tree", "run_1"]);
    expect(dashboardQueryKeys.runSteps("run_1")).toEqual(["run-steps", "run_1"]);
    expect(dashboardQueryKeys.runProfile("run_1")).toEqual(["run-profile", "run_1"]);
    expect(dashboardQueryKeys.accessInspection("acc_1")).toEqual(["access-inspection", "acc_1"]);
    expect(dashboardQueryKeys.replayAccess("acc_1")).toEqual(["replay-access", "acc_1"]);
    expect(dashboardQueryKeys.replayRun("run_1")).toEqual(["replay-run", "run_1"]);
    expect(dashboardQueryKeys.memories({ workspaceId: "ws_1", runId: "run_1" })).toEqual(["memories", "ws_1", "run_1"]);
    expect(dashboardQueryKeys.memoryVersions("mem_1")).toEqual(["memory-versions", "mem_1"]);
    expect(dashboardQueryKeys.memoryConflicts({ workspaceId: "ws_1", memoryId: "mem_1", status: "open" })).toEqual([
      "memory-conflicts",
      "ws_1",
      "mem_1",
      "open",
    ]);
  });
});
