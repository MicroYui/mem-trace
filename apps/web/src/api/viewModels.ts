import type {
  AgentRun,
  GateDecisionType,
  GateLayer,
  MaintenanceOperation,
  MemoryAccessLog,
  MemoryStatus,
  ProfilePhase,
  QuotaUnitName,
  RetrievalStrategy,
  SchedulerRunStatus,
  SchedulerTaskStatus,
  Sensitivity,
  StateNodeType,
} from "@memtrace/sdk";

export type DashboardMode = "fixture" | "live";

export type RequestStateKind =
  | "idle"
  | "loading"
  | "success"
  | "stale"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "quota_limited"
  | "connection_failed"
  | "error";

export interface RequestState {
  kind: RequestStateKind;
  message?: string;
}

export type MetricNumber =
  | {
      kind: "available";
      label: string;
      value: number;
      tone?: "neutral" | "good" | "warning" | "danger" | "info";
    }
  | {
      kind: "unavailable";
      label: string;
      reason: string;
    };

export type CapabilityState =
  | { kind: "authorized"; rowCount: number }
  | { kind: "authorized_empty"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "owner_only_unavailable"; message: string }
  | { kind: "unsupported"; message: string }
  | { kind: "unknown"; message: string };

export interface OverviewMetrics {
  runs: MetricNumber;
  accesses: MetricNumber;
  candidates: MetricNumber;
  accepted: MetricNumber;
  rejected: MetricNumber;
  degraded: MetricNumber;
  compactionEvents: MetricNumber;
  safetySignals: MetricNumber;
}

export interface RunSummaryView {
  runId: string;
  workspaceId: string;
  task: string;
  status: AgentRun["status"];
  startedAt: string;
  finishedAt: string | null;
  eventCount: MetricNumber;
  accessCount: MetricNumber;
}

export interface AccessSummaryView {
  accessId: string;
  runId: string | null;
  workspaceId: string;
  strategy: RetrievalStrategy;
  query: string;
  accepted: number;
  rejected: number;
  tokenBudget: number;
  actualTokens: number;
  gateRatioLabel: string;
  createdAt: string;
}

export interface StrategyIdentityView {
  strategy: string;
  label: string;
}

export interface SignalMetricView {
  id: string;
  label: string;
  metric: MetricNumber;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
  unit: "count" | "ratio";
}

export interface RunGalleryItemView extends RunSummaryView {
  durationLabel: string;
  latestAccess: AccessSummaryView | null;
  dominantStrategy: StrategyIdentityView | null;
}

export interface BenchmarkStrategyView {
  strategy: string;
  label: string;
  metrics: Record<string, MetricNumber>;
}

export type BenchmarkCellState = "passed" | "failed" | "not_run" | "unavailable";

export interface BenchmarkResultLinkView {
  href: string;
  label: string;
}

export interface BenchmarkMetricLineView {
  id: string;
  label: string;
  metric: MetricNumber;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
  note: string;
}

export interface BenchmarkMatrixCellView {
  strategy: string;
  state: BenchmarkCellState;
  label: string;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
  metric: MetricNumber;
  resultId: string | null;
  runId: string | null;
  accessId: string | null;
}

export interface BenchmarkCaseRowView {
  caseId: string;
  name: string;
  description: string;
  tags: string[];
  cells: Record<string, BenchmarkMatrixCellView>;
}

export interface BenchmarkCaseDrawerView {
  caseId: string;
  name: string;
  description: string;
  strategy: string | null;
  metrics: BenchmarkMetricLineView[];
  links: BenchmarkResultLinkView[];
}

export interface BenchmarkContaminationView {
  baseline: BenchmarkMetricLineView | null;
  variantTwo: BenchmarkMetricLineView | null;
  delta: MetricNumber;
}

export interface BenchmarkTokenBloatView {
  state: "available" | "comparator_unavailable";
  longContext: MetricNumber;
  comparator: MetricNumber;
  overhead: MetricNumber;
}

export interface BenchmarkCompactionView {
  triggerRate: BenchmarkMetricLineView;
  constraintRetention: BenchmarkMetricLineView;
  unsafeLeakage: BenchmarkMetricLineView;
  retainedNegativeUnsafeLeakage: BenchmarkMetricLineView;
}

export interface BenchmarkNegativeEvidenceView {
  promptBlocks: BenchmarkMetricLineView;
  retainedMetadata: BenchmarkMetricLineView;
  unsafeLeakage: BenchmarkMetricLineView;
}

export interface BenchmarkLabView {
  source: "fixture" | "live";
  strategyIds: string[];
  strategies: StrategyIdentityView[];
  caseCount: number;
  cases: BenchmarkCaseRowView[];
  contamination: BenchmarkContaminationView;
  tokenBloat: BenchmarkTokenBloatView;
  reflectionRetention: BenchmarkMetricLineView;
  compaction: BenchmarkCompactionView;
  negativeEvidence: BenchmarkNegativeEvidenceView;
  caseDrawer: BenchmarkCaseDrawerView;
}

export interface BenchmarkLabResult {
  data?: BenchmarkLabView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}

export interface DashboardOverviewView {
  workspaceIds: string[];
  metrics: OverviewMetrics;
  recentRuns: RunSummaryView[];
  recentAccesses: AccessSummaryView[];
  runGallery: RunGalleryItemView[];
  safetySignals: SignalMetricView[];
  compactionSignals: SignalMetricView[];
  negativeEvidenceSignals: SignalMetricView[];
  benchmarkStrategies: BenchmarkStrategyView[];
  opsCapability: CapabilityState;
  source: "fixture" | "live";
}

export interface DashboardOverviewResult {
  data?: DashboardOverviewView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}

export interface RunTimelineEventView {
  eventId: string;
  sequenceNo: number;
  role: string;
  eventType: string;
  title: string;
  content: string;
  contentDigest: string | null;
  stepId: string;
  stateNodeId: string | null;
  statusLabel: string;
  statusTone: "neutral" | "good" | "warning" | "danger" | "info";
  createdAt: string;
  meta: string[];
}

export interface RunStepView {
  stepId: string;
  stateNodeId: string | null;
  intent: string;
  status: string;
  statusTone: "neutral" | "good" | "warning" | "danger" | "info";
  startedAt: string;
  finishedAt: string | null;
  durationLabel: string;
  recoveryFromStepId: string | null;
  errorMessage: string | null;
}

export interface RunStateNodeView {
  nodeId: string;
  parentId: string | null;
  stepId: string | null;
  nodeType: StateNodeType;
  status: string;
  statusTone: "neutral" | "good" | "warning" | "danger" | "info";
  goal: string;
  summary: string;
  depth: number;
  path: string;
  failureReason: string | null;
}

export interface RunProfilePhaseView {
  profileId: string;
  phase: ProfilePhase;
  operation: string;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  candidateCount: number;
  acceptedCount: number;
  rejectedCount: number;
  createdAt: string;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
}

export interface RunProfileTotalsView {
  latencyMs: number;
  actualTokens: number;
  candidateCount: number;
  acceptedCount: number;
  rejectedCount: number;
}

export interface RunExplorerView {
  runId: string;
  timeline: RunTimelineEventView[];
  steps: RunStepView[];
  stateNodes: RunStateNodeView[];
  profilePhases: RunProfilePhaseView[];
  profileTotals: RunProfileTotalsView;
}

export interface RunExplorerResult {
  data?: RunExplorerView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}

export interface CandidateDecisionView {
  memoryId: string;
  content: string;
  layer: GateLayer;
  decision: GateDecisionType;
  rejectReason: string | null;
  branchStatus: string | null;
  relevanceScore: number;
  stateMatchScore: number;
  freshnessScore: number;
  trustScore: number;
  riskScore: number;
  finalScore: number;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
}

export interface DecisionGroupView {
  decision: GateDecisionType;
  label: string;
  count: number;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
}

export interface ContextBlockView {
  index: number;
  type: string;
  source: string | null;
  memoryId: string | null;
  reason: string | null;
  content: string;
  tokens: number;
  isNegativeEvidence: boolean;
}

export interface ReplayDriftView {
  diffCount: number;
  worstSeverity: string | null;
  severityLabel: string;
  warningCount: number;
}

export interface AccessReplayView {
  accessId: string;
  runId: string | null;
  stepId: string | null;
  workspaceId: string;
  query: string;
  strategy: RetrievalStrategy;
  tokenBudget: number;
  topK: number;
  policy: {
    policyVersion: string | null;
    policyHash: string | null;
  };
  candidates: CandidateDecisionView[];
  gateDecisions: CandidateDecisionView[];
  decisionGroups: Record<GateDecisionType, DecisionGroupView>;
  contextBlocks: ContextBlockView[];
  negativeEvidenceBlocks: ContextBlockView[];
  replayedContextBlocks: ContextBlockView[];
  compactionLogCount: number;
  replayDrift: ReplayDriftView;
}

export interface AccessReplayResult {
  data?: AccessReplayView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}

export type AdminTableName =
  | "maintenance_runs"
  | "maintenance_task_attempts"
  | "admin_action_audits"
  | "quota_limits";

export type DashboardAccess = MemoryAccessLog;

export type DisplayTextState = "collapsed" | "visible" | "secret" | "sanitized" | "empty";

export interface DisplayTextView {
  state: DisplayTextState;
  preview: string;
  expandable: boolean;
}

export interface DisplayKeyView {
  label: string;
  isMasked: boolean;
  reason: string | null;
}

export interface MemoryRiskBadgeView {
  id: string;
  label: string;
  tone: "neutral" | "good" | "warning" | "danger" | "info";
}

export interface MemoryAtlasSummaryView {
  totalMemories: MetricNumber;
  activeMemories: MetricNumber;
  conflictCount: MetricNumber;
  secretOrRisky: MetricNumber;
}

export interface MemoryAtlasItemView {
  memoryId: string;
  workspaceId: string;
  runId: string | null;
  sessionId: string | null;
  type: string;
  scope: string;
  lifecycleStatus: MemoryStatus;
  branchStatus: string;
  sensitivity: Sensitivity;
  embeddingStatus: string;
  displayKey: DisplayKeyView;
  displayValue: DisplayTextView;
  displayContent: DisplayTextView;
  summary: string;
  riskBadges: MemoryRiskBadgeView[];
  statusTone: "neutral" | "good" | "warning" | "danger" | "info";
  sensitivityTone: "neutral" | "good" | "warning" | "danger" | "info";
  createdAt: string;
  updatedAt: string;
}

export interface MemoryVersionView {
  versionId: string;
  memoryId: string;
  versionNo: number;
  changeReason: string;
  snapshotPreview: string;
  createdAt: string;
}

export interface MemoryConflictView {
  conflictId: string;
  subjectKey: DisplayKeyView;
  memoryIds: string[];
  status: string;
  detectedBy: string;
  explanationPreview: string;
  createdAt: string;
  resolvedAt: string | null;
}

export interface MemoryAtlasDetailView {
  memory: MemoryAtlasItemView;
  versions: MemoryVersionView[];
  conflicts: MemoryConflictView[];
}

export interface MemoryAtlasView {
  source: "fixture" | "live";
  workspaceIds: string[];
  summary: MemoryAtlasSummaryView;
  memories: MemoryAtlasItemView[];
  versions: MemoryVersionView[];
  conflicts: MemoryConflictView[];
  selectedMemory: MemoryAtlasDetailView | null;
  filters: {
    types: string[];
    lifecycleStatuses: string[];
    sensitivities: string[];
    branchStatuses: string[];
  };
}

export interface MemoryAtlasResult {
  data?: MemoryAtlasView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}

export interface OpsMetricSummaryView {
  maintenanceRuns: MetricNumber;
  taskAttempts: MetricNumber;
  adminAudits: MetricNumber;
  quotaLimits: MetricNumber;
}

export interface MaintenanceRunRowView {
  schedulerRunId: string;
  workspaceId: string;
  requestedBy: string;
  reason: string;
  operations: MaintenanceOperation[];
  dryRun: boolean;
  status: SchedulerRunStatus;
  summaryPreview: string;
  warningCount: number;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
}

export interface MaintenanceTaskAttemptRowView {
  attemptId: string;
  schedulerRunId: string;
  workspaceId: string;
  operation: MaintenanceOperation;
  status: SchedulerTaskStatus;
  attemptNo: number;
  resultPreview: string;
  errorSummary: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface AdminAuditRowView {
  adminActionId: string;
  workspaceId: string;
  principalId: string;
  action: string;
  targetType: string;
  targetId: string | null;
  metadataPreview: string;
  createdAt: string;
}

export interface QuotaLimitRowView {
  quotaLimitId: string;
  workspaceId: string;
  principalId: string | null;
  unit: QuotaUnitName;
  limit: number;
  windowSeconds: number;
  createdBy: string;
  updatedAt: string;
}

export interface OpsReadOnlyView {
  source: "fixture" | "live";
  capability: CapabilityState;
  summary: OpsMetricSummaryView;
  maintenanceRuns: MaintenanceRunRowView[];
  taskAttempts: MaintenanceTaskAttemptRowView[];
  adminAudits: AdminAuditRowView[];
  quotaLimits: QuotaLimitRowView[];
}

export interface OpsReadOnlyResult {
  data?: OpsReadOnlyView;
  requestState: RequestState;
  source: "fixture" | "live";
  error?: Error;
}
