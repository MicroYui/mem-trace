import type { ReactElement } from "react";
import type { RunGalleryItemView } from "../../api/viewModels";
import { StrategyToken } from "../ui/StrategyToken";
import { TimelineRow } from "../ui/TimelineRow";
import { TokenMeter } from "../ui/TokenMeter";

export interface RunGalleryProps {
  runs: RunGalleryItemView[];
  selectedRunId?: string | undefined;
  onSelectRun: (runId: string) => void;
}

export function RunGallery({ onSelectRun, runs, selectedRunId }: RunGalleryProps): ReactElement {
  return (
    <section className="panel run-gallery" id="recent-runs">
      <div className="panel-header">
        <div>
          <h2>Run gallery</h2>
        </div>
      </div>
      <div className="run-gallery-list">
        {runs.length === 0 ? (
          <div className="inline-empty-state">
            <strong>No runs returned</strong>
            <span>Connect a workspace with trace data or switch to fixture mode.</span>
          </div>
        ) : runs.map((run) => (
          <TimelineRow
            actions={(
              <button
                className={run.runId === selectedRunId ? "command-button secondary compact active" : "command-button secondary compact"}
                onClick={() => onSelectRun(run.runId)}
                type="button"
              >
                Open run details
              </button>
            )}
            eyebrow={run.durationLabel}
            key={run.runId}
            meta={[
              run.workspaceId,
              run.accessCount.kind === "available" ? `${run.accessCount.value} accesses` : "Access count unavailable",
            ]}
            statusLabel={run.status}
            statusTone={run.status === "completed" ? "good" : run.status === "failed" ? "danger" : "neutral"}
            title={run.task}
          >
            {run.latestAccess === null ? (
              <span className="muted-inline">No retrieval access returned</span>
            ) : (
              <div className="run-access-summary">
                <StrategyToken
                  label={run.dominantStrategy?.label}
                  strategy={run.dominantStrategy?.strategy ?? run.latestAccess.strategy}
                />
                <span>{run.latestAccess.gateRatioLabel}</span>
                <TokenMeter actual={run.latestAccess.actualTokens} budget={run.latestAccess.tokenBudget} />
              </div>
            )}
          </TimelineRow>
        ))}
      </div>
    </section>
  );
}
