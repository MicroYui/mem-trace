import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { DetailDrawer } from "../src/components/ui/DetailDrawer";
import { ErrorState } from "../src/components/ui/ErrorState";
import { ScoreBar } from "../src/components/ui/ScoreBar";
import { StrategyToken } from "../src/components/ui/StrategyToken";
import { TimelineRow } from "../src/components/ui/TimelineRow";
import { TokenMeter } from "../src/components/ui/TokenMeter";

describe("WEB-C UI primitives", () => {
  test("render dense inspection controls with accessible labels", () => {
    const html = renderToStaticMarkup(
      <section>
        <ScoreBar label="Accepted candidates" value={0.75} tone="good" />
        <TokenMeter actual={188} budget={420} label="Token pressure" />
        <StrategyToken strategy="variant_2" label="State-aware + gate" />
        <TimelineRow
          eyebrow="completed"
          title="Recover from failed npm branch"
          meta={["ws_showcase", "2 accesses"]}
          statusLabel="completed"
          statusTone="good"
        />
        <DetailDrawer title="Run detail" subtitle="run_showcase" actions={<button type="button">Open run</button>}>
          <p>Drawer content</p>
        </DetailDrawer>
        <ErrorState state={{ kind: "forbidden", message: "owner credentials required" }} />
      </section>,
    );

    expect(html).toContain('aria-label="Accepted candidates 75%"');
    expect(html).toContain('aria-label="Token pressure 188 of 420 tokens"');
    expect(html).toContain("State-aware + gate");
    expect(html).toContain("Recover from failed npm branch");
    expect(html).toContain("Run detail");
    expect(html).toContain("owner credentials required");
  });
});
