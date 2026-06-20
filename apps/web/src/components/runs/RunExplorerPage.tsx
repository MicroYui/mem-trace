import { Activity, GitBranch, ListTree, TimerReset } from "lucide-react";
import type { MemTraceClient } from "@memtrace/sdk";
import type { ReactElement } from "react";
import { useRunExplorer } from "../../api/queries";
import type { DashboardMode, RunExplorerResult, RunExplorerView } from "../../api/viewModels";
import { StateTreeGraph } from "../graph/StateTreeGraph";
import { DetailDrawer } from "../ui/DetailDrawer";
import { ErrorState } from "../ui/ErrorState";
import { MetricCard } from "../ui/MetricCard";
import { StatusPill } from "../ui/StatusPill";
import { TimelineRow } from "../ui/TimelineRow";

export interface RunExplorerPageProps {
  client: MemTraceClient;
  mode: DashboardMode;
  runId?: string | undefined;
}

export function RunExplorerPage({ client, mode, runId }: RunExplorerPageProps): ReactElement {
  const result = useRunExplorer({ client, mode, runId });
  return <RunExplorerPageState result={result} />;
}

interface RunExplorerPageStateProps {
  result: RunExplorerResult;
}

function RunExplorerPageState({ result }: RunExplorerPageStateProps): ReactElement {
  if (result.data === undefined) {
    return <ErrorState state={result.requestState} />;
  }
  return <RunExplorerPageContent view={result.data} />;
}

export interface RunExplorerPageContentProps {
  view: RunExplorerView;
}

export function RunExplorerPageContent({ view }: RunExplorerPageContentProps): ReactElement {
  const selectedEvent = view.timeline[0];

  return (
    <div className="route-page run-explorer-page">
      <section className="hero-band route-hero">
        <div>
          <StatusPill label="Run Explorer" tone="info" />
          <h1>{view.runId}</h1>
          <div className="summary-meta" aria-label="Run evidence totals">
            <span>{view.timeline.length} events</span>
            <span>{view.steps.length} steps</span>
            <span>{view.stateNodes.length} state nodes</span>
            <span>{view.profilePhases.length} profile phases</span>
          </div>
        </div>
        <div className="route-hero-meter">
          <StatusPill label={`${view.profileTotals.actualTokens} profile tokens`} tone="info" />
        </div>
      </section>

      <section className="metric-strip route-metric-strip" aria-label="Run profile totals">
        <MetricCard metric={{ kind: "available", label: "Latency ms", value: view.profileTotals.latencyMs, tone: "info" }} />
        <MetricCard metric={{ kind: "available", label: "Profile tokens", value: view.profileTotals.actualTokens, tone: "info" }} />
        <MetricCard metric={{ kind: "available", label: "Candidates", value: view.profileTotals.candidateCount }} />
        <MetricCard metric={{ kind: "available", label: "Accepted", value: view.profileTotals.acceptedCount, tone: "good" }} />
        <MetricCard metric={{ kind: "available", label: "Rejected", value: view.profileTotals.rejectedCount, tone: "danger" }} />
      </section>

      <div className="route-grid">
        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Sequence timeline</h2>
              <p>Ordered by persisted run sequence number.</p>
            </div>
            <Activity aria-hidden="true" size={20} />
          </div>
          <div className="run-timeline-list">
            {view.timeline.map((event) => (
              <TimelineRow
                eyebrow={`Sequence ${event.sequenceNo}`}
                key={event.eventId}
                meta={event.meta}
                statusLabel={event.statusLabel}
                statusTone={event.statusTone}
                title={event.title}
              >
                <p className="route-evidence-text">{event.content}</p>
              </TimelineRow>
            ))}
          </div>
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>State tree</h2>
              <p>Execution branch status and recovery placement.</p>
            </div>
            <GitBranch aria-hidden="true" size={20} />
          </div>
          <StateTreeGraph nodes={view.stateNodes} />
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Step list</h2>
              <p>Runtime steps grouped by state node identity.</p>
            </div>
            <ListTree aria-hidden="true" size={20} />
          </div>
          <div className="compact-list">
            {view.steps.map((step) => (
              <article className="compact-row" key={step.stepId}>
                <div>
                  <h3>{step.intent}</h3>
                  <p>{step.stepId}</p>
                  {step.recoveryFromStepId === null ? null : <p>recovery from {step.recoveryFromStepId}</p>}
                  {step.errorMessage === null ? null : <p className="danger-inline">{step.errorMessage}</p>}
                </div>
                <div className="compact-row-side">
                  <StatusPill label={step.status} tone={step.statusTone} />
                  <span>{step.durationLabel}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Profile phases</h2>
              <p>Recorded retrieval, gate, and context packing phases.</p>
            </div>
            <TimerReset aria-hidden="true" size={20} />
          </div>
          <div className="phase-strip">
            {view.profilePhases.map((phase) => (
              <article className={`phase-card ${phase.tone}`} key={phase.profileId}>
                <span>{phase.phase}</span>
                <strong>{phase.latencyMs}ms</strong>
                <small>{phase.operation}</small>
              </article>
            ))}
          </div>
        </section>

        {selectedEvent === undefined ? null : (
          <DetailDrawer subtitle={selectedEvent.eventId} title="Event detail">
            <dl className="detail-list">
              <div>
                <dt>Sequence</dt>
                <dd>{selectedEvent.sequenceNo}</dd>
              </div>
              <div>
                <dt>Step</dt>
                <dd>{selectedEvent.stepId}</dd>
              </div>
              <div>
                <dt>State node</dt>
                <dd>{selectedEvent.stateNodeId ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt>Digest</dt>
                <dd>{selectedEvent.contentDigest ?? "Unavailable"}</dd>
              </div>
            </dl>
            <p className="route-evidence-text">{selectedEvent.content}</p>
          </DetailDrawer>
        )}
      </div>
    </div>
  );
}
