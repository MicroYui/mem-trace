import type { ReactElement } from "react";

export interface ScoreBarProps {
  label: string;
  value: number;
  tone?: "neutral" | "good" | "warning" | "danger" | "info";
  valueLabel?: string;
}

export function ScoreBar({
  label,
  tone = "neutral",
  value,
  valueLabel,
}: ScoreBarProps): ReactElement {
  const ratio = clampRatio(value);
  const percent = Math.round(ratio * 100);
  const displayValue = valueLabel ?? `${percent}%`;

  return (
    <div className={`score-bar ${tone}`} aria-label={`${label} ${displayValue}`}>
      <div className="score-bar-label">
        <span>{label}</span>
        <strong>{displayValue}</strong>
      </div>
      <div className="score-track" aria-hidden="true">
        <span style={{ inlineSize: `${percent}%` }} />
      </div>
    </div>
  );
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}
