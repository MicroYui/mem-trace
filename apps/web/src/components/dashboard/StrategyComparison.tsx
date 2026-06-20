import { ArrowRight } from "lucide-react";
import type { ReactElement } from "react";
import type { BenchmarkStrategyView, MetricNumber } from "../../api/viewModels";
import { ScoreBar } from "../ui/ScoreBar";
import { StatusPill } from "../ui/StatusPill";
import { StrategyToken } from "../ui/StrategyToken";

export interface StrategyComparisonProps {
  strategies: BenchmarkStrategyView[];
}

export function StrategyComparison({ strategies }: StrategyComparisonProps): ReactElement {
  const baseline = strategies.find((strategy) => strategy.strategy === "baseline_1");
  const variantTwo = strategies.find((strategy) => strategy.strategy === "variant_2");
  const visibleStrategies = [baseline, variantTwo, ...strategies.filter((strategy) => (
    strategy.strategy !== "baseline_1" && strategy.strategy !== "variant_2"
  ))].filter((strategy): strategy is BenchmarkStrategyView => strategy !== undefined);

  return (
    <section className="panel strategy-panel">
      <div className="panel-header">
        <div>
          <h2>Strategy comparison</h2>
        </div>
        <StatusPill label="Returned benchmark metrics" tone="warning" />
      </div>
      <div className="strategy-ladder">
        {visibleStrategies.map((strategy, index) => (
          <div className="strategy-ladder-item" key={strategy.strategy}>
            {index === 1 ? <ArrowRight aria-hidden="true" className="strategy-transition" size={20} /> : null}
            <StrategyCard strategy={strategy} featured={strategy.strategy === "variant_2"} />
          </div>
        ))}
      </div>
    </section>
  );
}

interface StrategyCardProps {
  strategy: BenchmarkStrategyView;
  featured?: boolean;
}

function StrategyCard({ featured = false, strategy }: StrategyCardProps): ReactElement {
  const success = strategy.metrics.task_success_rate;
  const contamination = strategy.metrics.positive_contamination_rate;
  const retention = strategy.metrics.negative_lesson_retained_rate ?? strategy.metrics.reflection_retention_hit_rate;
  const avgTokens = strategy.metrics.avg_actual_tokens;

  return (
    <article className={featured ? "strategy-card featured" : "strategy-card"}>
      <div className="strategy-card-title">
        <StrategyToken label={strategy.label} strategy={strategy.strategy} />
        <code>{strategy.strategy}</code>
      </div>
      <div className="strategy-bars">
        <MetricScore label="Task success" metric={success} tone="good" />
        <MetricScore label="Positive contamination" metric={contamination} tone="danger" />
        <MetricScore label="Retention signal" metric={retention} tone="info" />
      </div>
      <span className="strategy-token-note">Avg tokens: {formatMetric(avgTokens)}</span>
    </article>
  );
}

interface MetricScoreProps {
  label: string;
  metric: MetricNumber | undefined;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
}

function MetricScore({ label, metric, tone }: MetricScoreProps): ReactElement {
  if (metric?.kind !== "available") {
    return (
      <div className="metric-score unavailable">
        <span>{label}</span>
        <strong>Unavailable</strong>
      </div>
    );
  }
  return <ScoreBar label={label} tone={tone} value={metric.value} />;
}

function formatMetric(metric: MetricNumber | undefined): string {
  if (metric?.kind !== "available") return "Unavailable";
  return Number.isInteger(metric.value)
    ? metric.value.toLocaleString("en-US")
    : metric.value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
