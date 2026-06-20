import type { ReactElement } from "react";

export interface StrategyTokenProps {
  strategy: string;
  label?: string | undefined;
}

export function StrategyToken({ label, strategy }: StrategyTokenProps): ReactElement {
  return (
    <span className={`strategy-token ${strategyTone(strategy)}`} data-strategy={strategy}>
      <span aria-hidden="true" className="strategy-token-mark" />
      <span>{label ?? strategy}</span>
    </span>
  );
}

function strategyTone(strategy: string): string {
  if (strategy === "variant_2" || strategy === "variant_3") return "good";
  if (strategy === "variant_1") return "info";
  if (strategy === "long_context") return "warning";
  if (strategy.startsWith("baseline")) return "neutral";
  return "info";
}
