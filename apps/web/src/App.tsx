import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { ReactElement } from "react";
import { BrowserRouter, MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { createDashboardClient, resolveApiBaseUrl } from "./api/client";
import { useBenchmarkLab, useDashboardOverview, useMemoryAtlas, useOpsReadOnly } from "./api/queries";
import type { DashboardMode } from "./api/viewModels";
import { AccessReplayPage } from "./components/access/AccessReplayPage";
import { AppChrome } from "./components/chrome/AppChrome";
import { OverviewDashboard } from "./components/dashboard/OverviewDashboard";
import { RunExplorerPage } from "./components/runs/RunExplorerPage";
import { BenchmarkLabPage } from "./features/benchmark/BenchmarkLabPage";
import { MemoryAtlasPage } from "./features/memories/MemoryAtlasPage";
import { OpsReadOnlyPage } from "./features/ops/OpsReadOnlyPage";
import { ShowcasePage } from "./features/showcase/ShowcasePage";

export interface AppProps {
  initialMode?: DashboardMode;
  initialApiKey?: string;
  initialWorkspaceId?: string;
  initialPath?: string;
}

export function App({
  initialMode = "fixture",
  initialApiKey = "",
  initialPath,
  initialWorkspaceId,
}: AppProps): ReactElement {
  const [mode, setMode] = useState<DashboardMode>(initialMode);
  const [apiKey, setApiKey] = useState(initialApiKey);
  const [workspaceId, setWorkspaceId] = useState<string | undefined>(initialWorkspaceId);
  const queryClient = useMemo(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 15_000,
      },
    },
  }), []);

  const apiBaseUrl = resolveApiBaseUrl(import.meta.env.VITE_MEMTRACE_API_BASE_URL);
  const client = useMemo(() => createDashboardClient({
    apiKey,
    baseUrl: apiBaseUrl,
  }), [apiBaseUrl, apiKey]);

  const routedShell = (
    <DashboardShell
      apiBaseUrl={apiBaseUrl}
      client={client}
      initialMode={mode}
      initialWorkspaceId={workspaceId}
      onConnectLive={({ apiKey: nextApiKey, workspaceId: nextWorkspaceId }) => {
        setApiKey(nextApiKey);
        setWorkspaceId(nextWorkspaceId);
        setMode("live");
      }}
      onUseFixture={() => {
        setMode("fixture");
        setWorkspaceId(undefined);
      }}
    />
  );
  const router = typeof window === "undefined" || initialPath !== undefined
    ? <MemoryRouter initialEntries={[initialPath ?? "/"]}>{routedShell}</MemoryRouter>
    : <BrowserRouter>{routedShell}</BrowserRouter>;

  return (
    <QueryClientProvider client={queryClient}>
      {router}
    </QueryClientProvider>
  );
}

interface DashboardShellProps {
  apiBaseUrl: string;
  client: ReturnType<typeof createDashboardClient>;
  initialMode: DashboardMode;
  initialWorkspaceId?: string | undefined;
  onConnectLive: (values: { apiKey: string; workspaceId?: string | undefined }) => void;
  onUseFixture: () => void;
}

function DashboardShell({
  apiBaseUrl,
  client,
  initialMode,
  initialWorkspaceId,
  onConnectLive,
  onUseFixture,
}: DashboardShellProps): ReactElement {
  const location = useLocation();
  const overview = useDashboardOverview({
    client,
    mode: initialMode,
    workspaceId: initialWorkspaceId,
  });
  const defaultRunId = overview.data?.runGallery[0]?.runId;
  const defaultAccessId = overview.data?.recentAccesses[0]?.accessId;

  return (
    <AppChrome
      activePath={location.pathname}
      apiBaseUrl={apiBaseUrl}
      defaultAccessId={defaultAccessId}
      defaultRunId={defaultRunId}
      mode={initialMode}
      onConnectLive={onConnectLive}
      onUseFixture={onUseFixture}
      requestState={overview.requestState}
      workspaceIds={overview.data?.workspaceIds ?? []}
    >
      <Routes>
        <Route path="/" element={<OverviewDashboard overview={overview} />} />
        <Route path="/showcase" element={<ShowcasePage />} />
        <Route path="/benchmark" element={<BenchmarkLabRoute client={client} mode={initialMode} workspaceId={initialWorkspaceId} />} />
        <Route path="/memories" element={<MemoryAtlasRoute client={client} mode={initialMode} workspaceId={initialWorkspaceId} />} />
        <Route path="/ops" element={<OpsReadOnlyRoute client={client} mode={initialMode} workspaceId={initialWorkspaceId} />} />
        <Route path="/runs/:runId" element={<RunExplorerRoute client={client} mode={initialMode} />} />
        <Route path="/access/:accessId" element={<AccessReplayRoute client={client} mode={initialMode} />} />
        <Route path="*" element={<OverviewDashboard overview={overview} />} />
      </Routes>
    </AppChrome>
  );
}

interface RouteComponentProps {
  client: ReturnType<typeof createDashboardClient>;
  mode: DashboardMode;
}

function RunExplorerRoute({ client, mode }: RouteComponentProps): ReactElement {
  const { runId } = useParams();
  return <RunExplorerPage client={client} mode={mode} runId={runId} />;
}

function AccessReplayRoute({ client, mode }: RouteComponentProps): ReactElement {
  const { accessId } = useParams();
  return <AccessReplayPage accessId={accessId} client={client} mode={mode} />;
}

function BenchmarkLabRoute({
  client,
  mode,
  workspaceId,
}: RouteComponentProps & { workspaceId?: string | undefined }): ReactElement {
  const benchmark = useBenchmarkLab({ client, mode, workspaceId });
  return <BenchmarkLabPage benchmark={benchmark} />;
}

function MemoryAtlasRoute({
  client,
  mode,
  workspaceId,
}: RouteComponentProps & { workspaceId?: string | undefined }): ReactElement {
  const atlas = useMemoryAtlas({ client, mode, workspaceId });
  return <MemoryAtlasPage atlas={atlas} />;
}

function OpsReadOnlyRoute({
  client,
  mode,
  workspaceId,
}: RouteComponentProps & { workspaceId?: string | undefined }): ReactElement {
  const ops = useOpsReadOnly({ client, mode, workspaceId });
  return <OpsReadOnlyPage ops={ops} />;
}
