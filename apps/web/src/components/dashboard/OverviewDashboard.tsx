import { ArrowRight, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { ReactElement } from "react";
import type { CapabilityState, DashboardOverviewResult, RunGalleryItemView } from "../../api/viewModels";
import { AccessStream } from "./AccessStream";
import { RunGallery } from "./RunGallery";
import { SignalPanel } from "./SignalPanel";
import { StrategyComparison } from "./StrategyComparison";
import { DetailDrawer } from "../ui/DetailDrawer";
import { ErrorState } from "../ui/ErrorState";
import { MetricCard } from "../ui/MetricCard";
import { StatusPill } from "../ui/StatusPill";
import { StrategyToken } from "../ui/StrategyToken";

export interface OverviewDashboardProps {
  overview: DashboardOverviewResult;
}

export function OverviewDashboard({ overview }: OverviewDashboardProps): ReactElement {
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);

  if (overview.data === undefined) {
    return <ErrorState state={overview.requestState} />;
  }

  const { data } = overview;
  const selectedRun = data.runGallery.find((run) => run.runId === selectedRunId) ?? data.runGallery[0];

  return (
    <div className="overview-grid">
      <section className="hero-band">
        <div>
          <StatusPill label={data.source === "fixture" ? "Fixture mode" : "Live mode"} tone="info" />
          <h1>Workspace overview</h1>
          <div className="summary-meta" aria-label="Overview totals">
            <span>{data.workspaceIds[0] ?? "No workspace"}</span>
            <span>{data.recentRuns.length} recent runs</span>
            <span>{data.recentAccesses.length} recent accesses</span>
          </div>
        </div>
        <div className="hero-actions">
          <a className="command-button primary" href="#recent-runs">
            Runs
            <ArrowRight aria-hidden="true" size={18} />
          </a>
          <a className="command-button secondary" href="#recent-accesses">Accesses</a>
        </div>
      </section>

      <section className="metric-strip" aria-label="Workspace metrics">
        <MetricCard metric={data.metrics.runs} />
        <MetricCard metric={data.metrics.accesses} />
        <MetricCard metric={data.metrics.accepted} />
        <MetricCard metric={data.metrics.rejected} />
        <MetricCard metric={data.metrics.degraded} />
        <MetricCard metric={data.metrics.compactionEvents} />
        <MetricCard metric={data.metrics.safetySignals} />
      </section>

      <div className="overview-primary-grid">
        <div className="overview-main-column">
          <StrategyComparison strategies={data.benchmarkStrategies} />
          <RunGallery
            onSelectRun={setSelectedRunId}
            runs={data.runGallery}
            selectedRunId={selectedRun?.runId}
          />
          <AccessStream accesses={data.recentAccesses} />
        </div>

        <div className="overview-side-column">
          <SignalPanel signals={data.safetySignals} title="Safety signals" />
          <SignalPanel signals={data.compactionSignals} title="Compaction evidence" />
          <SignalPanel signals={data.negativeEvidenceSignals} title="Negative evidence" />
          {selectedRun === undefined ? null : <RunDetailDrawer run={selectedRun} />}
          <OpsPanel capability={data.opsCapability} />
        </div>
      </div>
    </div>
  );
}

interface RunDetailDrawerProps {
  run: RunGalleryItemView;
}

function RunDetailDrawer({ run }: RunDetailDrawerProps): ReactElement {
  return (
    <DetailDrawer
      actions={<a className="command-button secondary compact" href={`/runs/${encodeURIComponent(run.runId)}`}>Run Explorer</a>}
      subtitle={run.runId}
      title="Run detail"
    >
      <dl className="detail-list">
        <div>
          <dt>Task</dt>
          <dd>{run.task}</dd>
        </div>
        <div>
          <dt>Workspace</dt>
          <dd>{run.workspaceId}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{run.durationLabel}</dd>
        </div>
        <div>
          <dt>Accesses</dt>
          <dd>{run.accessCount.kind === "available" ? run.accessCount.value : "Unavailable"}</dd>
        </div>
      </dl>
      {run.latestAccess === null ? (
        <p className="muted-inline">No retrieval access returned for this run.</p>
      ) : (
        <div className="drawer-access-summary">
          <span>Latest access</span>
          <strong>{run.latestAccess.query}</strong>
          <div className="drawer-inline">
            <StrategyToken
              label={run.dominantStrategy?.label}
              strategy={run.dominantStrategy?.strategy ?? run.latestAccess.strategy}
            />
            <span>{run.latestAccess.gateRatioLabel}</span>
          </div>
          <a className="command-button primary compact" href={`/access/${encodeURIComponent(run.latestAccess.accessId)}`}>Replay access</a>
        </div>
      )}
    </DetailDrawer>
  );
}

interface OpsPanelProps {
  capability: CapabilityState;
}

function OpsPanel({ capability }: OpsPanelProps): ReactElement {
  return (
    <section className="panel ops-panel">
      <div className="panel-header">
        <div>
          <h2>Ops read-only</h2>
        </div>
        <ShieldAlert aria-hidden="true" size={20} />
      </div>
      <p className="ops-message">{opsCapabilityMessage(capability)}</p>
    </section>
  );
}

function opsCapabilityMessage(capability: CapabilityState): string {
  if (capability.kind === "authorized") return `Owner credentials are active; ${capability.rowCount} operations rows are available.`;
  return capability.message;
}
