import type { ReactElement } from "react";

export interface EmptyStateProps {
  title: string;
  body: string;
}

export function EmptyState({ body, title }: EmptyStateProps): ReactElement {
  return (
    <section className="empty-state">
      <h1>{title}</h1>
      <p>{body}</p>
    </section>
  );
}
