import type { ReactElement } from "react";
import type { AccessReplayView } from "../../api/viewModels";

export interface MemoryFlowGraphProps {
  view: AccessReplayView;
}

export function MemoryFlowGraph({ view }: MemoryFlowGraphProps): ReactElement {
  return (
    <div className="memory-flow-graph" aria-label="Memory flow graph">
      <FlowStage label="Candidates" value={view.candidates.length} />
      <FlowArrow />
      <div className="flow-stage-stack" aria-label="Gate decisions">
        <FlowStage label={view.decisionGroups.accept.label} tone="good" value={view.decisionGroups.accept.count} />
        <FlowStage label={view.decisionGroups.degrade.label} tone="warning" value={view.decisionGroups.degrade.count} />
        <FlowStage label={view.decisionGroups.reject.label} tone="danger" value={view.decisionGroups.reject.count} />
      </div>
      <FlowArrow />
      <FlowStage label="Context blocks" tone="info" value={view.contextBlocks.length} />
    </div>
  );
}

interface FlowStageProps {
  label: string;
  value: number;
  tone?: "neutral" | "good" | "warning" | "danger" | "info";
}

function FlowStage({ label, tone = "neutral", value }: FlowStageProps): ReactElement {
  return (
    <article className={`flow-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function FlowArrow(): ReactElement {
  return <span className="flow-arrow" aria-hidden="true">-&gt;</span>;
}
