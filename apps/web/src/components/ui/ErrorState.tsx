import { CircleAlert, LockKeyhole, PlugZap } from "lucide-react";
import type { ReactElement } from "react";
import type { RequestState } from "../../api/viewModels";
import { StatusPill } from "./StatusPill";

export interface ErrorStateProps {
  state: RequestState;
}

export function ErrorState({ state }: ErrorStateProps): ReactElement {
  const Icon = state.kind === "forbidden" || state.kind === "unauthorized"
    ? LockKeyhole
    : state.kind === "connection_failed"
      ? PlugZap
      : CircleAlert;

  return (
    <section className="error-state" aria-live="polite">
      <Icon aria-hidden="true" size={28} />
      <div>
        <StatusPill label={state.kind.replaceAll("_", " ")} tone={stateTone(state)} />
        <h1>{stateTitle(state)}</h1>
        <p>{state.message ?? "Dashboard data is unavailable."}</p>
      </div>
    </section>
  );
}

function stateTitle(state: RequestState): string {
  if (state.kind === "loading") return "Loading dashboard";
  if (state.kind === "idle") return "Connect a workspace";
  if (state.kind === "forbidden") return "Owner credentials required";
  if (state.kind === "unauthorized") return "Authentication required";
  if (state.kind === "quota_limited") return "Quota limited";
  if (state.kind === "connection_failed") return "Connection failed";
  return "Dashboard unavailable";
}

function stateTone(state: RequestState): "neutral" | "good" | "warning" | "danger" | "info" {
  if (state.kind === "success") return "good";
  if (state.kind === "loading" || state.kind === "idle") return "info";
  if (state.kind === "stale") return "warning";
  if (state.kind === "forbidden" || state.kind === "unauthorized" || state.kind === "quota_limited") return "danger";
  return "neutral";
}
