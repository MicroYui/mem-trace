import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { normalizeAccessReplay } from "../src/api/normalizers";
import { App } from "../src/App";
import { AccessReplayPageContent } from "../src/components/access/AccessReplayPage";
import { showcaseFixture } from "../src/fixtures/showcase";
import type { ShowcaseAccessRouteFixture } from "../src/fixtures/types";

describe("WEB-F access replay and memory flow", () => {
  test("normalizes inspect and replay payloads into explicit gate and context flow", () => {
    const access = requireAccessFixture("acc_showcase_gate");
    const view = normalizeAccessReplay({
      accessId: "acc_showcase_gate",
      inspection: access.inspection,
      replay: access.replay,
    });

    expect(view.accessId).toBe("acc_showcase_gate");
    expect(view.decisionGroups.accept.count).toBe(2);
    expect(view.decisionGroups.degrade.count).toBe(1);
    expect(view.decisionGroups.reject.count).toBe(2);
    expect(view.contextBlocks.map((block) => block.type)).toContain("avoided_attempts");
    expect(view.negativeEvidenceBlocks).toHaveLength(1);
    expect(view.replayDrift.severityLabel).toBe("No replay drift");
    expect(view.policy.policyVersion).toBe("retrieval-policy-v2");
  });

  test("renders candidates, gate matrix, context preview, replay drift, and memory flow", () => {
    const access = requireAccessFixture("acc_showcase_gate");
    const view = normalizeAccessReplay({
      accessId: "acc_showcase_gate",
      inspection: access.inspection,
      replay: access.replay,
    });

    const html = renderToStaticMarkup(<AccessReplayPageContent view={view} />);

    expect(html).toContain("Access Replay");
    expect(html).toContain("Memory flow");
    expect(html).toContain("Gate decision matrix");
    expect(html).toContain("Context pack preview");
    expect(html).toContain("Replay drift");
    expect(html).toContain("avoid repeating npm install");
    expect(html).toContain("Relevance");
    expect(html).toContain("State match");
    expect(html).toContain("Freshness");
    expect(html).toContain("Trust");
    expect(html).toContain("Risk");
    expect(html).toContain("degrade");
    expect(html).not.toContain("Degraded positive context");
  });

  test("loads access replay from a direct fixture route", () => {
    const html = renderToStaticMarkup(
      <App initialMode="fixture" initialPath="/access/acc_showcase_gate" />,
    );

    expect(html).toContain("Access Replay");
    expect(html).toContain("acc_showcase_gate");
    expect(html).toContain("avoid repeating npm install");
  });
});

function requireAccessFixture(accessId: string): ShowcaseAccessRouteFixture {
  const access = showcaseFixture.routes.accesses[accessId];
  if (access === undefined) {
    throw new Error(`missing fixture access ${accessId}`);
  }
  return access;
}
