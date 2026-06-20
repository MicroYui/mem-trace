import type { ReactElement } from "react";
import { ScoreBar } from "./ScoreBar";

export interface TokenMeterProps {
  actual: number;
  budget: number;
  label?: string;
}

export function TokenMeter({ actual, budget, label = "Token pressure" }: TokenMeterProps): ReactElement {
  const safeBudget = Number.isFinite(budget) && budget > 0 ? budget : 0;
  const safeActual = Number.isFinite(actual) && actual >= 0 ? actual : 0;
  const ratio = safeBudget === 0 ? 0 : safeActual / safeBudget;
  const tone = ratio >= 0.95 ? "danger" : ratio >= 0.8 ? "warning" : "info";

  return (
    <div className="token-meter" aria-label={`${label} ${safeActual} of ${safeBudget} tokens`}>
      <ScoreBar
        label={label}
        tone={tone}
        value={ratio}
        valueLabel={`${safeActual.toLocaleString("en-US")}/${safeBudget.toLocaleString("en-US")}`}
      />
    </div>
  );
}
