import type { ReactElement } from "react";
import type { SignalMetricView } from "../../api/viewModels";
import { ScoreBar } from "../ui/ScoreBar";

export interface SignalPanelProps {
  title: string;
  signals: SignalMetricView[];
}

export function SignalPanel({ signals, title }: SignalPanelProps): ReactElement {
  return (
    <section className="panel signal-panel">
      <div className="panel-header">
        <div>
          <h2>{title}</h2>
        </div>
      </div>
      <div className="signal-list">
        {signals.map((signal) => (
          <div className="signal-row" key={signal.id}>
            {signal.unit === "ratio" && signal.metric.kind === "available" ? (
              <ScoreBar
                label={signal.label}
                tone={signal.tone}
                value={signal.metric.value}
                valueLabel={formatSignalValue(signal)}
              />
            ) : (
              <>
                <span>{signal.label}</span>
                <strong className={`signal-value ${signal.tone}`}>{formatSignalValue(signal)}</strong>
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function formatSignalValue(signal: SignalMetricView): string {
  if (signal.metric.kind === "unavailable") return "Unavailable";
  if (signal.unit === "ratio") return `${Math.round(signal.metric.value * 100)}%`;
  return signal.metric.value.toLocaleString("en-US");
}
