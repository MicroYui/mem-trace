import type { ReactElement } from "react";
import type { MetricNumber } from "../../api/viewModels";

export interface MetricCardProps {
  metric: MetricNumber;
}

export function MetricCard({ metric }: MetricCardProps): ReactElement {
  return (
    <div className={metric.kind === "available" ? "metric-card" : "metric-card unavailable"}>
      <span>{metric.label}</span>
      <strong>{metric.kind === "available" ? formatMetric(metric.value) : "Unavailable"}</strong>
      {metric.kind === "unavailable" ? <small>{metric.reason}</small> : null}
    </div>
  );
}

function formatMetric(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}
