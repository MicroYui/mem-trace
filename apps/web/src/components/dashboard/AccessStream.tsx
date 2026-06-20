import type { ReactElement } from "react";
import type { AccessSummaryView } from "../../api/viewModels";
import { StrategyToken } from "../ui/StrategyToken";
import { TimelineRow } from "../ui/TimelineRow";
import { TokenMeter } from "../ui/TokenMeter";

export interface AccessStreamProps {
  accesses: AccessSummaryView[];
}

export function AccessStream({ accesses }: AccessStreamProps): ReactElement {
  return (
    <section className="panel access-stream" id="recent-accesses">
      <div className="panel-header">
        <div>
          <h2>Recent accesses</h2>
        </div>
      </div>
      <div className="access-stream-list">
        {accesses.length === 0 ? (
          <div className="inline-empty-state">
            <strong>No retrieval accesses returned</strong>
            <span>Retrieval and replay rows will appear after context is requested.</span>
          </div>
        ) : accesses.map((access) => (
          <TimelineRow
            eyebrow={access.workspaceId}
            key={access.accessId}
            meta={[access.accessId, access.gateRatioLabel]}
            statusLabel={`${access.accepted}/${access.accepted + access.rejected} accepted`}
            statusTone={access.rejected > access.accepted ? "warning" : "good"}
            title={access.query}
          >
            <div className="access-row-extra">
              <StrategyToken strategy={access.strategy} />
              <TokenMeter actual={access.actualTokens} budget={access.tokenBudget} />
              <a className="command-button secondary compact" href={`/access/${encodeURIComponent(access.accessId)}`}>Replay</a>
            </div>
          </TimelineRow>
        ))}
      </div>
    </section>
  );
}
