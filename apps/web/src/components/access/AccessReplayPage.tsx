import { GitCompareArrows, Network, ShieldCheck, Workflow } from "lucide-react";
import type { MemTraceClient } from "@memtrace/sdk";
import type { ReactElement } from "react";
import { useAccessReplay } from "../../api/queries";
import type { AccessReplayResult, AccessReplayView, DashboardMode } from "../../api/viewModels";
import { MemoryFlowGraph } from "../graph/MemoryFlowGraph";
import { DetailDrawer } from "../ui/DetailDrawer";
import { ErrorState } from "../ui/ErrorState";
import { ScoreBar } from "../ui/ScoreBar";
import { StatusPill } from "../ui/StatusPill";
import { StrategyToken } from "../ui/StrategyToken";
import { TokenMeter } from "../ui/TokenMeter";

export interface AccessReplayPageProps {
  accessId?: string | undefined;
  client: MemTraceClient;
  mode: DashboardMode;
}

export function AccessReplayPage({ accessId, client, mode }: AccessReplayPageProps): ReactElement {
  const result = useAccessReplay({ accessId, client, mode });
  return <AccessReplayPageState result={result} />;
}

interface AccessReplayPageStateProps {
  result: AccessReplayResult;
}

function AccessReplayPageState({ result }: AccessReplayPageStateProps): ReactElement {
  if (result.data === undefined) {
    return <ErrorState state={result.requestState} />;
  }
  return <AccessReplayPageContent view={result.data} />;
}

export interface AccessReplayPageContentProps {
  view: AccessReplayView;
}

export function AccessReplayPageContent({ view }: AccessReplayPageContentProps): ReactElement {
  const selectedBlock = view.negativeEvidenceBlocks[0] ?? view.contextBlocks[0];

  return (
    <div className="route-page access-replay-page">
      <section className="hero-band route-hero">
        <div>
          <StatusPill label="Access Replay" tone="info" />
          <h1>{view.query}</h1>
          <div className="summary-meta" aria-label="Access replay metadata">
            <span>{view.accessId}</span>
            <span>{view.workspaceId}</span>
            <span>{view.runId ?? "No run id"}</span>
            <span>{view.policy.policyVersion ?? "Policy unavailable"}</span>
          </div>
        </div>
        <div className="route-hero-meter">
          <StrategyToken strategy={view.strategy} />
          <TokenMeter actual={contextTokenTotal(view)} budget={view.tokenBudget} />
        </div>
      </section>

      <div className="route-grid">
        <section className="panel route-panel memory-flow-panel">
          <div className="panel-header">
            <div>
              <h2>Memory flow</h2>
              <p>Candidates move through gate decisions into packed context blocks.</p>
            </div>
            <Workflow aria-hidden="true" size={20} />
          </div>
          <MemoryFlowGraph view={view} />
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Gate decision matrix</h2>
              <p>Candidate rows with layered policy decisions and component scores.</p>
            </div>
            <ShieldCheck aria-hidden="true" size={20} />
          </div>
          <div className="decision-matrix" aria-label="Candidate gate decision matrix">
            {view.gateDecisions.map((decision) => (
              <article className="decision-row" key={`${decision.memoryId}-${decision.layer}`}>
                <div>
                  <span className="timeline-eyebrow">{decision.layer}</span>
                  <h3>{decision.content}</h3>
                  <p>{decision.rejectReason ?? decision.branchStatus ?? "accepted evidence"}</p>
                </div>
                <div className="decision-score">
                  <StatusPill label={decision.decision} tone={decision.tone} />
                  <ScoreBar label="Final score" value={decision.finalScore} />
                  <div className="component-score-grid" aria-label={`Component scores for ${decision.memoryId}`}>
                    <ScoreBar label="Relevance" value={decision.relevanceScore} />
                    <ScoreBar label="State match" value={decision.stateMatchScore} />
                    <ScoreBar label="Freshness" value={decision.freshnessScore} />
                    <ScoreBar label="Trust" value={decision.trustScore} />
                    <ScoreBar label="Risk" value={decision.riskScore} tone="warning" />
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Context pack preview</h2>
              <p>Prompt blocks reconstructed from inspection data.</p>
            </div>
            <Network aria-hidden="true" size={20} />
          </div>
          <div className="context-block-list">
            {view.contextBlocks.map((block) => (
              <article className={block.isNegativeEvidence ? "context-block negative" : "context-block"} key={`${block.index}-${block.type}`}>
                <div>
                  <StatusPill label={block.type} tone={block.isNegativeEvidence ? "warning" : "good"} />
                  <span>{block.tokens} tokens</span>
                </div>
                <p>{block.content}</p>
                {block.reason === null ? null : <small>{block.reason}</small>}
              </article>
            ))}
          </div>
        </section>

        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Replay drift</h2>
              <p>Original inspection compared with replay reconstruction.</p>
            </div>
            <GitCompareArrows aria-hidden="true" size={20} />
          </div>
          <div className="drift-summary">
            <StatusPill
              label={view.replayDrift.severityLabel}
              tone={view.replayDrift.diffCount === 0 ? "good" : "warning"}
            />
            <span>{view.replayDrift.warningCount} warnings</span>
            <span>{view.compactionLogCount} compaction logs</span>
          </div>
        </section>

        {selectedBlock === undefined ? null : (
          <DetailDrawer subtitle={selectedBlock.memoryId ?? view.accessId} title="Selected context block">
            <dl className="detail-list">
              <div>
                <dt>Type</dt>
                <dd>{selectedBlock.type}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{selectedBlock.source ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt>Tokens</dt>
                <dd>{selectedBlock.tokens}</dd>
              </div>
              <div>
                <dt>Negative evidence</dt>
                <dd>{selectedBlock.isNegativeEvidence ? "Yes" : "No"}</dd>
              </div>
            </dl>
            <p className="route-evidence-text">{selectedBlock.content}</p>
          </DetailDrawer>
        )}
      </div>
    </div>
  );
}

function contextTokenTotal(view: AccessReplayView): number {
  return view.contextBlocks.reduce((total, block) => total + block.tokens, 0);
}
