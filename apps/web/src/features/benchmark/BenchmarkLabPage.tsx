import { BarChart3, Gauge, ShieldCheck } from "lucide-react";
import type { ReactElement } from "react";
import type {
  BenchmarkCaseDrawerView,
  BenchmarkCaseRowView,
  BenchmarkLabResult,
  BenchmarkLabView,
  BenchmarkMetricLineView,
  BenchmarkMatrixCellView,
  BenchmarkNegativeEvidenceView,
  BenchmarkTokenBloatView,
  MetricNumber,
} from "../../api/viewModels";
import { ErrorState } from "../../components/ui/ErrorState";
import { MetricCard } from "../../components/ui/MetricCard";
import { ScoreBar } from "../../components/ui/ScoreBar";
import { StatusPill } from "../../components/ui/StatusPill";
import { StrategyToken } from "../../components/ui/StrategyToken";

export interface BenchmarkLabPageProps {
  benchmark: BenchmarkLabResult;
}

export function BenchmarkLabPage({ benchmark }: BenchmarkLabPageProps): ReactElement {
  if (benchmark.data === undefined) {
    return <ErrorState state={benchmark.requestState} />;
  }
  return <BenchmarkLabPageContent view={benchmark.data} />;
}

export interface BenchmarkLabPageContentProps {
  view: BenchmarkLabView;
}

export function BenchmarkLabPageContent({ view }: BenchmarkLabPageContentProps): ReactElement {
  return (
    <div className="benchmark-layout">
      <section className="hero-band benchmark-hero">
        <div>
          <StatusPill label={view.source === "fixture" ? "Fixture mode" : "Live mode"} tone="info" />
          <h1>Benchmark Lab</h1>
          <div className="summary-meta" aria-label="Benchmark lab totals">
            <span>{view.caseCount} cases returned</span>
            <span>{view.strategyIds.length} strategies</span>
            <span>Missing rows stay unavailable</span>
          </div>
        </div>
        <div className="benchmark-hero-icon" aria-hidden="true">
          <BarChart3 size={34} />
        </div>
      </section>

      <section className="benchmark-story-grid" aria-label="Benchmark summary panels">
        <BenchmarkMetricPanel
          icon={<ShieldCheck aria-hidden="true" size={20} />}
          metrics={[
            view.contamination.baseline,
            view.contamination.variantTwo,
            {
              id: "contamination_delta",
              label: view.contamination.delta.label,
              metric: view.contamination.delta,
              tone: "good",
              note: "Requires baseline_1 and variant_2 comparator metrics.",
            },
          ].filter((line): line is BenchmarkMetricLineView => line !== null)}
          title="Positive contamination"
        />
        <TokenBloatPanel tokenBloat={view.tokenBloat} />
        <BenchmarkMetricPanel
          icon={<Gauge aria-hidden="true" size={20} />}
          metrics={[view.reflectionRetention]}
          title="Reflection retention"
        />
        <BenchmarkMetricPanel
          metrics={[
            view.compaction.triggerRate,
            view.compaction.constraintRetention,
            view.compaction.unsafeLeakage,
            view.compaction.retainedNegativeUnsafeLeakage,
          ]}
          title="Compaction retention"
        />
        <NegativeEvidencePanel negativeEvidence={view.negativeEvidence} />
      </section>

      <section className="panel benchmark-matrix-panel">
        <div className="panel-header">
          <div>
            <h2>Strategy x case matrix</h2>
          </div>
          <StatusPill label="Returned eval rows" tone="warning" />
        </div>
        <div className="benchmark-strategy-legend" aria-label="Benchmark strategy legend">
          {view.strategies.map((strategy) => (
            <StrategyToken key={strategy.strategy} label={strategy.label} strategy={strategy.strategy} />
          ))}
        </div>
        <div className="benchmark-matrix-scroll">
          <table className="benchmark-matrix">
            <thead>
              <tr>
                <th scope="col">Case</th>
                {view.strategies.map((strategy) => (
                  <th key={strategy.strategy} scope="col">
                    <StrategyToken label={strategy.label} strategy={strategy.strategy} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.cases.map((caseRow) => (
                <BenchmarkCaseTableRow caseRow={caseRow} key={caseRow.caseId} strategyIds={view.strategyIds} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <BenchmarkCaseDrawer drawer={view.caseDrawer} />
    </div>
  );
}

interface BenchmarkMetricPanelProps {
  icon?: ReactElement;
  metrics: BenchmarkMetricLineView[];
  title: string;
}

function BenchmarkMetricPanel({ icon, metrics, title }: BenchmarkMetricPanelProps): ReactElement {
  return (
    <section className="panel benchmark-panel">
      <div className="panel-header">
        <div>
          <h2>{title}</h2>
        </div>
        {icon}
      </div>
      <div className="benchmark-metric-list">
        {metrics.map((line) => <BenchmarkMetricLine key={line.id} line={line} />)}
      </div>
    </section>
  );
}

function TokenBloatPanel({ tokenBloat }: { tokenBloat: BenchmarkTokenBloatView }): ReactElement {
  return (
    <section className="panel benchmark-panel">
      <div className="panel-header">
        <div>
          <h2>Long-context token bloat</h2>
        </div>
        <StatusPill
          label={tokenBloat.state === "available" ? "Comparator available" : "Comparator unavailable"}
          tone={tokenBloat.state === "available" ? "good" : "warning"}
        />
      </div>
      <div className="metric-mini-grid">
        <MetricCard metric={tokenBloat.longContext} />
        <MetricCard metric={tokenBloat.comparator} />
        <MetricCard metric={tokenBloat.overhead} />
      </div>
    </section>
  );
}

function NegativeEvidencePanel({ negativeEvidence }: { negativeEvidence: BenchmarkNegativeEvidenceView }): ReactElement {
  return (
    <BenchmarkMetricPanel
      metrics={[
        negativeEvidence.promptBlocks,
        negativeEvidence.retainedMetadata,
        negativeEvidence.unsafeLeakage,
      ]}
      title="Negative evidence retention"
    />
  );
}

function BenchmarkMetricLine({ line }: { line: BenchmarkMetricLineView }): ReactElement {
  return (
    <div className="benchmark-metric-line">
      <div>
        <span>{line.label}</span>
        <small>{line.note}</small>
      </div>
      {line.metric.kind === "available"
        ? <ScoreBar label={line.label} tone={line.tone} value={normalizeScoreValue(line.metric.value)} valueLabel={formatMetric(line.metric)} />
        : <strong className="metric-unavailable">Unavailable</strong>}
    </div>
  );
}

interface BenchmarkCaseTableRowProps {
  caseRow: BenchmarkCaseRowView;
  strategyIds: string[];
}

function BenchmarkCaseTableRow({ caseRow, strategyIds }: BenchmarkCaseTableRowProps): ReactElement {
  return (
    <tr>
      <th scope="row">
        <span>{caseRow.name}</span>
        <code>{caseRow.caseId}</code>
      </th>
      {strategyIds.map((strategy) => (
        <td key={strategy}>
          <BenchmarkMatrixCell cell={caseRow.cells[strategy]} />
        </td>
      ))}
    </tr>
  );
}

function BenchmarkMatrixCell({ cell }: { cell: BenchmarkMatrixCellView | undefined }): ReactElement {
  if (cell === undefined) {
    return <StatusPill label="Not run" tone="neutral" />;
  }
  return (
    <div className={`benchmark-cell ${cell.state}`}>
      <StatusPill label={cell.label} tone={cell.tone} />
      <small>{cell.metric.kind === "available" ? formatMetric(cell.metric) : cell.metric.reason}</small>
      {cell.accessId === null ? null : (
        <a href={`/access/${encodeURIComponent(cell.accessId)}`}>Replay</a>
      )}
    </div>
  );
}

function BenchmarkCaseDrawer({ drawer }: { drawer: BenchmarkCaseDrawerView }): ReactElement {
  return (
    <section className="panel benchmark-drawer">
      <div className="panel-header">
        <div>
          <h2>Case detail</h2>
        </div>
        {drawer.strategy === null ? null : <StrategyToken strategy={drawer.strategy} />}
      </div>
      <div className="case-detail-heading">
        <strong>{drawer.name}</strong>
        <code>{drawer.caseId}</code>
      </div>
      <p>{drawer.description}</p>
      <div className="drawer-actions">
        {drawer.links.map((link) => (
          <a className="command-button secondary compact" href={link.href} key={link.href}>{link.label}</a>
        ))}
      </div>
      <div className="source-metric-grid">
        {drawer.metrics.slice(0, 12).map((line) => (
          <div className="source-metric" key={line.id}>
            <span>{line.label}</span>
            <strong>{formatMetric(line.metric)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatMetric(metric: MetricNumber): string {
  if (metric.kind === "unavailable") return "Unavailable";
  if (metric.value >= 0 && metric.value <= 1 && !Number.isInteger(metric.value)) {
    return `${Math.round(metric.value * 100)}%`;
  }
  if (Number.isInteger(metric.value)) return metric.value.toLocaleString("en-US");
  return metric.value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function normalizeScoreValue(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value >= 0 && value <= 1) return value;
  return Math.min(1, value / Math.max(1, Math.abs(value)));
}
