import type { ReactElement, ReactNode } from "react";
import { StatusPill } from "./StatusPill";

export interface TimelineRowProps {
  eyebrow: string;
  title: string;
  meta: string[];
  statusLabel: string;
  statusTone?: "neutral" | "good" | "warning" | "danger" | "info";
  actions?: ReactNode;
  children?: ReactNode;
}

export function TimelineRow({
  actions,
  children,
  eyebrow,
  meta,
  statusLabel,
  statusTone = "neutral",
  title,
}: TimelineRowProps): ReactElement {
  return (
    <article className="timeline-row">
      <div className="timeline-marker" aria-hidden="true" />
      <div className="timeline-row-body">
        <div className="timeline-row-main">
          <div>
            <span className="timeline-eyebrow">{eyebrow}</span>
            <h3>{title}</h3>
            <div className="timeline-meta">
              {meta.map((item) => <span key={item}>{item}</span>)}
            </div>
          </div>
          <div className="timeline-row-actions">
            <StatusPill label={statusLabel} tone={statusTone} />
            {actions}
          </div>
        </div>
        {children === undefined ? null : <div className="timeline-row-extra">{children}</div>}
      </div>
    </article>
  );
}
