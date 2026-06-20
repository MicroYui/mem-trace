import type { ReactElement } from "react";

export interface StatusPillProps {
  label: string;
  tone?: "neutral" | "good" | "warning" | "danger" | "info";
}

export function StatusPill({ label, tone = "neutral" }: StatusPillProps): ReactElement {
  return <span className={`status-pill ${tone}`}>{label}</span>;
}
