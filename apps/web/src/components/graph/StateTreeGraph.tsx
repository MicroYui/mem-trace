import type { CSSProperties, ReactElement } from "react";
import type { RunStateNodeView } from "../../api/viewModels";
import { StatusPill } from "../ui/StatusPill";

export interface StateTreeGraphProps {
  nodes: RunStateNodeView[];
}

export function StateTreeGraph({ nodes }: StateTreeGraphProps): ReactElement {
  return (
    <div className="state-tree-graph" aria-label="State tree graph">
      {nodes.map((node) => (
        <article
          className={`state-node-row ${node.nodeType}`}
          key={node.nodeId}
          style={{ "--node-depth": node.depth } as CSSProperties}
        >
          <div className="state-node-connector" aria-hidden="true" />
          <div className="state-node-content">
            <div>
              <span className="timeline-eyebrow">{node.nodeType}</span>
              <h3>{node.goal}</h3>
              <p>{node.summary}</p>
              {node.failureReason === null ? null : <p className="danger-inline">{node.failureReason}</p>}
            </div>
            <StatusPill label={node.status} tone={node.statusTone} />
          </div>
        </article>
      ))}
    </div>
  );
}
