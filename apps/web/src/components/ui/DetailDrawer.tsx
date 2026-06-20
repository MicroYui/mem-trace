import type { ReactElement, ReactNode } from "react";

export interface DetailDrawerProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function DetailDrawer({ actions, children, subtitle, title }: DetailDrawerProps): ReactElement {
  return (
    <aside className="detail-drawer" aria-label={title}>
      <div className="detail-drawer-header">
        <div>
          {subtitle === undefined ? null : <span>{subtitle}</span>}
          <h2>{title}</h2>
        </div>
        {actions === undefined ? null : <div className="detail-drawer-actions">{actions}</div>}
      </div>
      <div className="detail-drawer-body">
        {children}
      </div>
    </aside>
  );
}
