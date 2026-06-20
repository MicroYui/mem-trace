import { Activity, BarChart3, Boxes, Database, GitBranch, KeyRound, Moon, Network, Presentation, SunMedium } from "lucide-react";
import { useEffect, useState } from "react";
import type { PropsWithChildren, ReactElement } from "react";
import { Link } from "react-router-dom";
import type { DashboardMode, RequestState } from "../../api/viewModels";
import { StatusPill } from "../ui/StatusPill";

export interface AppChromeProps extends PropsWithChildren {
  activePath: string;
  apiBaseUrl: string;
  defaultAccessId?: string | undefined;
  defaultRunId?: string | undefined;
  mode: DashboardMode;
  onConnectLive: (values: { apiKey: string; workspaceId?: string | undefined }) => void;
  onUseFixture: () => void;
  requestState: RequestState;
  workspaceIds: string[];
}

const NAV_ITEMS = [
  { label: "Overview", icon: Activity, key: "overview" },
  { label: "Runs", icon: GitBranch, key: "runs" },
  { label: "Replay", icon: Network, key: "replay" },
  { label: "Benchmark", icon: BarChart3, key: "benchmark" },
  { label: "Memories", icon: Database, key: "memories" },
  { label: "Ops", icon: Boxes, key: "ops" },
  { label: "Showcase", icon: Presentation, key: "showcase" },
];

export function AppChrome({
  activePath,
  apiBaseUrl,
  children,
  defaultAccessId,
  defaultRunId,
  mode,
  onConnectLive,
  onUseFixture,
  requestState,
  workspaceIds,
}: AppChromeProps): ReactElement {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [workspaceDraft, setWorkspaceDraft] = useState("");
  const [apiKeyDraft, setApiKeyDraft] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const apiLabel = apiBaseUrl.length === 0 ? "same-origin /v1" : apiBaseUrl;
  const workspaceLabel = workspaceIds.length === 0 ? "No workspace selected" : workspaceIds[0] ?? "No workspace selected";

  return (
    <div className="app-shell">
      <aside className="left-rail" aria-label="Dashboard navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">MT</div>
          <div>
            <div className="brand-name">MemTrace</div>
            <div className="brand-subtitle">Trace memory runtime</div>
          </div>
        </div>
        <nav className="nav-list">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const href = navHref(item.key, { defaultAccessId, defaultRunId });
            const active = navActive(item.key, activePath);
            return (
              <Link className={active ? "nav-item active" : "nav-item"} to={href} key={item.label}>
                <Icon aria-hidden="true" size={18} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="rail-footer">
          <StatusPill label={mode === "fixture" ? "Fixture mode" : "Live mode"} tone={mode === "fixture" ? "info" : "good"} />
        </div>
      </aside>

      <div className="main-stage">
        <header className="top-bar">
          <div className="selector-group" aria-label="Connection summary">
            <div className="selector">
              <span>Workspace</span>
              <strong>{workspaceLabel}</strong>
            </div>
            <div className="selector">
              <span>API</span>
              <strong>{apiLabel}</strong>
            </div>
            <StatusPill label={requestStateLabel(requestState)} tone={requestStateTone(requestState)} />
          </div>
          <div className="top-actions">
            <form
              className="connection-form"
              onSubmit={(event) => {
                event.preventDefault();
                onConnectLive({
                  apiKey: apiKeyDraft,
                  workspaceId: workspaceDraft.trim().length === 0 ? undefined : workspaceDraft.trim(),
                });
                setApiKeyDraft("");
              }}
            >
              <input
                aria-label="Workspace id"
                autoComplete="off"
                onChange={(event) => setWorkspaceDraft(event.currentTarget.value)}
                placeholder="workspace id"
                value={workspaceDraft}
              />
              <input
                aria-label="API key"
                autoComplete="off"
                onChange={(event) => setApiKeyDraft(event.currentTarget.value)}
                placeholder="API key"
                type="password"
                value={apiKeyDraft}
              />
              <button className="command-button secondary compact" type="submit">Connect live</button>
              <button className="command-button secondary compact" onClick={onUseFixture} type="button">Use fixture</button>
            </form>
            <button className="icon-button" type="button" title="API key stays in the Authorization header">
              <KeyRound aria-hidden="true" size={18} />
              <span className="visually-hidden">API key status</span>
            </button>
            <button
              className="icon-button"
              type="button"
              title="Toggle theme"
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <SunMedium aria-hidden="true" size={18} /> : <Moon aria-hidden="true" size={18} />}
              <span className="visually-hidden">Toggle theme</span>
            </button>
          </div>
        </header>
        <main className="content-stage">
          {children}
        </main>
      </div>
    </div>
  );
}

function navHref(
  key: string,
  defaults: { defaultAccessId?: string | undefined; defaultRunId?: string | undefined },
): string {
  if (key === "overview") return "/";
  if (key === "runs") return defaults.defaultRunId === undefined ? "/" : `/runs/${encodeURIComponent(defaults.defaultRunId)}`;
  if (key === "replay") return defaults.defaultAccessId === undefined ? "/" : `/access/${encodeURIComponent(defaults.defaultAccessId)}`;
  if (key === "benchmark") return "/benchmark";
  if (key === "memories") return "/memories";
  if (key === "ops") return "/ops";
  if (key === "showcase") return "/showcase";
  return "/";
}

function navActive(key: string, activePath: string): boolean {
  if (key === "overview") return activePath === "/";
  if (key === "runs") return activePath.startsWith("/runs");
  if (key === "replay") return activePath.startsWith("/access");
  if (key === "benchmark") return activePath.startsWith("/benchmark");
  if (key === "memories") return activePath.startsWith("/memories");
  if (key === "ops") return activePath.startsWith("/ops");
  if (key === "showcase") return activePath.startsWith("/showcase");
  return false;
}

function requestStateLabel(state: RequestState): string {
  if (state.message !== undefined && state.message.length > 0) {
    return state.message;
  }
  return state.kind.replaceAll("_", " ");
}

function requestStateTone(state: RequestState): "neutral" | "good" | "warning" | "danger" | "info" {
  if (state.kind === "success") return "good";
  if (state.kind === "loading" || state.kind === "idle") return "info";
  if (state.kind === "stale") return "warning";
  if (state.kind === "forbidden" || state.kind === "unauthorized" || state.kind === "quota_limited") return "danger";
  return "neutral";
}
