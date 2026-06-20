import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { normalizeRunExplorer } from "../src/api/normalizers";
import { App } from "../src/App";
import { RunExplorerPageContent } from "../src/components/runs/RunExplorerPage";
import { showcaseFixture } from "../src/fixtures/showcase";
import type { ShowcaseRunRouteFixture } from "../src/fixtures/types";

describe("WEB-E run explorer", () => {
  test("normalizes route-specific run data without overview state", () => {
    const run = requireRunFixture("run_showcase_bun_recovery");
    const view = normalizeRunExplorer({
      runId: "run_showcase_bun_recovery",
      timeline: run.timeline,
      stateTree: run.stateTree,
      steps: run.steps,
      profile: run.profile,
    });

    expect(view.runId).toBe("run_showcase_bun_recovery");
    expect(view.timeline.map((event) => event.sequenceNo)).toEqual([1, 2, 3, 4]);
    expect(view.stateNodes.map((node) => node.nodeType)).toContain("recovery");
    expect(view.steps.map((step) => step.status)).toContain("rolled_back");
    expect(view.profilePhases.map((phase) => phase.phase)).toContain("context_packing");
    expect(view.profileTotals.actualTokens).toBe(188);
  });

  test("renders timeline, state tree, steps, profile, and event detail evidence", () => {
    const run = requireRunFixture("run_showcase_bun_recovery");
    const view = normalizeRunExplorer({
      runId: "run_showcase_bun_recovery",
      timeline: run.timeline,
      stateTree: run.stateTree,
      steps: run.steps,
      profile: run.profile,
    });

    const html = renderToStaticMarkup(<RunExplorerPageContent view={view} />);

    expect(html).toContain("Run Explorer");
    expect(html).toContain("Sequence timeline");
    expect(html).toContain("State tree");
    expect(html).toContain("Step list");
    expect(html).toContain("Profile phases");
    expect(html).toContain("npm failed on rolled-back branch");
    expect(html).toContain("recovery");
    expect(html).toContain("context_packing");
    expect(html).toContain("Event detail");
  });

  test("loads the run explorer from a direct fixture route", () => {
    const html = renderToStaticMarkup(
      <App initialMode="fixture" initialPath="/runs/run_showcase_bun_recovery" />,
    );

    expect(html).toContain("Run Explorer");
    expect(html).toContain("run_showcase_bun_recovery");
    expect(html).toContain("npm failed on rolled-back branch");
  });
});

function requireRunFixture(runId: string): ShowcaseRunRouteFixture {
  const run = showcaseFixture.routes.runs[runId];
  if (run === undefined) {
    throw new Error(`missing fixture run ${runId}`);
  }
  return run;
}
