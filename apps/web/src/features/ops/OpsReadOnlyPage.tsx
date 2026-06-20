import { Boxes, FileClock, Gauge, ShieldAlert } from "lucide-react";
import type { ReactElement } from "react";
import type { OpsReadOnlyResult, OpsReadOnlyView } from "../../api/viewModels";
import { ErrorState } from "../../components/ui/ErrorState";
import { MetricCard } from "../../components/ui/MetricCard";
import { StatusPill } from "../../components/ui/StatusPill";

export interface OpsReadOnlyPageProps {
  ops: OpsReadOnlyResult;
}

export function OpsReadOnlyPage({ ops }: OpsReadOnlyPageProps): ReactElement {
  if (ops.data === undefined) {
    return <ErrorState state={ops.requestState} />;
  }
  return <OpsReadOnlyPageContent view={ops.data} />;
}

export interface OpsReadOnlyPageContentProps {
  view: OpsReadOnlyView;
}

export function OpsReadOnlyPageContent({ view }: OpsReadOnlyPageContentProps): ReactElement {
  return (
    <div className="ops-layout">
      <section className="hero-band route-hero">
        <div>
          <StatusPill label={view.source === "fixture" ? "Fixture mode" : "Live mode"} tone="info" />
          <h1>Ops Read-Only</h1>
          <div className="summary-meta" aria-label="Ops table capability">
            <span>{capabilityLabel(view)}</span>
            <span>No admin mutations</span>
            <span>Owner-gated tables only</span>
          </div>
        </div>
        <div className="benchmark-hero-icon" aria-hidden="true">
          <Boxes size={34} />
        </div>
      </section>

      <section className="metric-strip route-metric-strip" aria-label="Ops metrics">
        <MetricCard metric={view.summary.maintenanceRuns} />
        <MetricCard metric={view.summary.taskAttempts} />
        <MetricCard metric={view.summary.adminAudits} />
        <MetricCard metric={view.summary.quotaLimits} />
      </section>

      {view.capability.kind === "authorized" ? null : (
        <section className="panel locked-panel">
          <div className="panel-header">
            <div>
              <h2>Owner-gated state</h2>
            </div>
            <ShieldAlert aria-hidden="true" size={20} />
          </div>
          <p>{view.capability.message}</p>
        </section>
      )}

      <div className="ops-grid">
        <section className="panel">
          <TableHeader icon={<FileClock aria-hidden="true" size={20} />} title="Maintenance runs" />
          <div className="ops-table" role="table" aria-label="Maintenance runs">
            <div className="ops-table-row ops-table-head" role="row">
              <span role="columnheader">Run</span>
              <span role="columnheader">Status</span>
              <span role="columnheader">Operations</span>
              <span role="columnheader">Summary</span>
            </div>
            {view.maintenanceRuns.map((run) => (
              <div className="ops-table-row" key={run.schedulerRunId} role="row">
                <div role="cell">
                  <strong>{run.schedulerRunId}</strong>
                  <small>{run.reason}</small>
                </div>
                <span role="cell"><StatusPill label={run.status} tone={run.status === "completed" ? "good" : "warning"} /></span>
                <span role="cell">{run.operations.join(", ")}</span>
                <span role="cell">{run.summaryPreview}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <TableHeader icon={<Gauge aria-hidden="true" size={20} />} title="Task attempts" />
          <div className="ops-card-list">
            {view.taskAttempts.map((attempt) => (
              <div className="compact-row" key={attempt.attemptId}>
                <div>
                  <span className="timeline-eyebrow">{attempt.schedulerRunId}</span>
                  <h3>{attempt.operation}</h3>
                  <p>{attempt.resultPreview}</p>
                </div>
                <StatusPill label={attempt.status} tone={attempt.status === "completed" ? "good" : "warning"} />
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <TableHeader title="Admin action audits" />
          <div className="ops-card-list">
            {view.adminAudits.map((audit) => (
              <div className="compact-row" key={audit.adminActionId}>
                <div>
                  <span className="timeline-eyebrow">{audit.targetType}</span>
                  <h3>{audit.action}</h3>
                  <p>{audit.metadataPreview}</p>
                </div>
                <StatusPill label={audit.principalId} tone="info" />
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <TableHeader title="Quota limits" />
          <div className="ops-card-list">
            {view.quotaLimits.map((quota) => (
              <div className="compact-row" key={quota.quotaLimitId}>
                <div>
                  <span className="timeline-eyebrow">{quota.workspaceId}</span>
                  <h3>{quota.unit}</h3>
                  <p>{quota.limit} per {quota.windowSeconds}s window</p>
                </div>
                <StatusPill label={quota.principalId === null ? "workspace" : "principal"} tone="info" />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function TableHeader({ icon, title }: { icon?: ReactElement; title: string }): ReactElement {
  return (
    <div className="panel-header">
      <div>
        <h2>{title}</h2>
      </div>
      {icon}
    </div>
  );
}

function capabilityLabel(view: OpsReadOnlyView): string {
  if (view.capability.kind === "authorized") return `${view.capability.rowCount} owner rows returned`;
  return view.capability.kind.replaceAll("_", " ");
}
