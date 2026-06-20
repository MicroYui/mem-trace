import type {
  AccessInspection,
  AdminActionAuditRecord,
  AgentEvent,
  AgentStep,
  ContextBlock,
  DashboardTables,
  GateDecisionType,
  GateDecisionView,
  MaintenanceRunRecord,
  MaintenanceTaskAttemptRecord,
  MemoryConflictRecord,
  MemoryItem,
  MemoryVersionRecord,
  MemoryAccessLog,
  QuotaLimitRecord,
  ObservabilitySummary,
  ProfileEvent,
  ReplayDiffItem,
  ReplayRetrievalResult,
  RetrievalStrategy,
  StateNode,
} from "@memtrace/sdk";
import type {
  AdminTableName,
  AccessReplayView,
  BenchmarkCaseDrawerView,
  BenchmarkCaseRowView,
  BenchmarkCompactionView,
  BenchmarkContaminationView,
  BenchmarkLabView,
  BenchmarkMatrixCellView,
  BenchmarkMetricLineView,
  BenchmarkNegativeEvidenceView,
  BenchmarkStrategyView,
  BenchmarkTokenBloatView,
  CandidateDecisionView,
  CapabilityState,
  ContextBlockView,
  DashboardOverviewView,
  DisplayKeyView,
  DisplayTextView,
  DecisionGroupView,
  MetricNumber,
  MemoryAtlasDetailView,
  MemoryAtlasItemView,
  MemoryAtlasView,
  MemoryConflictView,
  MemoryRiskBadgeView,
  MemoryVersionView,
  OpsReadOnlyView,
  RequestState,
  RunExplorerView,
  RunProfilePhaseView,
  RunGalleryItemView,
  RunSummaryView,
  RunTimelineEventView,
  SignalMetricView,
  StrategyIdentityView,
} from "./viewModels";

const ADMIN_TABLE_NAMES: AdminTableName[] = [
  "maintenance_runs",
  "maintenance_task_attempts",
  "admin_action_audits",
  "quota_limits",
];

const STRATEGY_LABELS: Record<string, string> = {
  baseline_0: "No memory baseline",
  long_context: "Long-context",
  baseline_1: "Vector only",
  variant_1: "State-aware rerank",
  variant_2: "State-aware + gate",
  variant_3: "Gate + reflection signal",
};

const STRATEGY_ORDER = ["baseline_0", "long_context", "baseline_1", "variant_1", "variant_2", "variant_3"];

export function normalizeMetricNumber(
  value: unknown,
  label: string,
  tone?: "neutral" | "good" | "warning" | "danger" | "info",
): MetricNumber {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return { kind: "unavailable", label, reason: "not provided" };
  }
  return tone === undefined ? { kind: "available", label, value } : { kind: "available", label, value, tone };
}

export function normalizeDashboardTables(dashboard: DashboardTables, source: "fixture" | "live" = "live"): DashboardOverviewView {
  const summary = dashboard.observability_summary ?? undefined;
  const workspaceIds = collectWorkspaceIds(dashboard, summary);
  const benchmarkStrategies = normalizeBenchmarkSummary(dashboard.benchmark_summary ?? {});
  const recentRuns = dashboard.runs.slice(0, 8).map((run): RunSummaryView => ({
    runId: run.run_id,
    workspaceId: run.workspace_id,
    task: run.task ?? "Untitled run",
    status: run.status,
    startedAt: run.started_at,
    finishedAt: run.finished_at ?? null,
    eventCount: { kind: "unavailable", label: "Events", reason: "requires timeline projection" },
    accessCount: {
      kind: "available",
      label: "Accesses",
      value: dashboard.accesses.filter((access) => access.run_id === run.run_id).length,
    },
  }));
  const recentAccesses = dashboard.accesses.slice(0, 8).map(normalizeAccess);

  return {
    workspaceIds,
    metrics: {
      runs: { kind: "available", label: "Runs", value: dashboard.runs.length },
      accesses: normalizeMetricNumber(summary?.access_count, "Accesses"),
      candidates: normalizeMetricNumber(summary?.candidate_count, "Candidates"),
      accepted: normalizeMetricNumber(summary?.accepted_count, "Accepted", "good"),
      rejected: normalizeMetricNumber(summary?.rejected_count, "Rejected", "danger"),
      degraded: normalizeMetricNumber(summary?.degraded_negative_evidence_count, "Degraded"),
      compactionEvents: normalizeMetricNumber(summary?.history_summary_count, "Compaction"),
      safetySignals: normalizeMetricNumber(totalSafetySignals(summary), "Safety signals"),
    },
    recentRuns,
    recentAccesses,
    runGallery: normalizeRunGallery(recentRuns, recentAccesses),
    safetySignals: normalizeSafetySignals(summary),
    compactionSignals: normalizeCompactionSignals(summary),
    negativeEvidenceSignals: normalizeNegativeEvidenceSignals(summary),
    benchmarkStrategies,
    opsCapability: normalizeOpsCapability(dashboard),
    source,
  };
}

export function normalizeBenchmarkLab(dashboard: DashboardTables, source: "fixture" | "live" = "live"): BenchmarkLabView {
  const cases = normalizeBenchmarkCases(dashboard);
  const results = normalizeBenchmarkResults(dashboard);
  const strategyIds = collectBenchmarkStrategies(dashboard, cases, results);
  const caseRows = cases.map((caseRecord) => normalizeBenchmarkCaseRow(caseRecord, strategyIds, results));
  const firstDrawerCase = caseRows[0];

  return {
    source,
    strategyIds,
    strategies: strategyIds.map(strategyIdentity),
    caseCount: caseRows.length,
    cases: caseRows,
    contamination: normalizeBenchmarkContamination(dashboard.benchmark_summary ?? {}),
    tokenBloat: normalizeBenchmarkTokenBloat(dashboard.benchmark_summary ?? {}, results),
    reflectionRetention: benchmarkLine(
      "reflection_retention_hit_rate",
      "Reflection retention",
      summaryMetric(dashboard.benchmark_summary, "variant_3", "reflection_retention_hit_rate", "Reflection retention"),
      "info",
      "Uses variant_3 reflection_retention_hit_rate only when returned.",
    ),
    compaction: normalizeBenchmarkCompaction(dashboard.benchmark_summary ?? {}),
    negativeEvidence: normalizeBenchmarkNegativeEvidence(dashboard.benchmark_summary ?? {}),
    caseDrawer: firstDrawerCase === undefined
      ? emptyBenchmarkDrawer()
      : normalizeBenchmarkCaseDrawer(firstDrawerCase, results),
  };
}

export interface NormalizeMemoryAtlasInput {
  dashboard: DashboardTables;
  memories: MemoryItem[];
  source?: "fixture" | "live";
}

export function normalizeMemoryAtlas({
  dashboard,
  memories,
  source = "live",
}: NormalizeMemoryAtlasInput): MemoryAtlasView {
  const memoryRows = memories
    .slice()
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
    .map(normalizeMemoryAtlasItem);
  const versions = dashboard.memory_versions
    .slice()
    .sort((left, right) => left.version_no - right.version_no)
    .map(normalizeMemoryVersion);
  const conflicts = dashboard.memory_conflicts
    .slice()
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    .map(normalizeMemoryConflict);
  const memoryWithVersions = memoryRows.find((memory) => (
    versions.some((version) => version.memoryId === memory.memoryId)
  ));
  const selectedMemoryRow = memoryWithVersions ?? memoryRows[0] ?? null;

  return {
    source,
    workspaceIds: collectMemoryWorkspaceIds(dashboard, memories),
    summary: {
      totalMemories: { kind: "available", label: "Memories", value: memories.length },
      activeMemories: {
        kind: "available",
        label: "Active",
        value: memories.filter((memory) => memory.status === "active" || memory.status === "pinned").length,
        tone: "good",
      },
      conflictCount: {
        kind: "available",
        label: "Conflicts",
        value: dashboard.memory_conflicts.length,
        tone: dashboard.memory_conflicts.length === 0 ? "good" : "warning",
      },
      secretOrRisky: {
        kind: "available",
        label: "Secret/risky",
        value: memories.filter((memory) => isSensitiveMemory(memory)).length,
        tone: memories.some(isSensitiveMemory) ? "warning" : "good",
      },
    },
    memories: memoryRows,
    versions,
    conflicts,
    selectedMemory: selectedMemoryRow === null
      ? null
      : normalizeMemoryAtlasDetail(selectedMemoryRow, versions, conflicts),
    filters: {
      types: uniqueSorted(memoryRows.map((memory) => memory.type)),
      lifecycleStatuses: uniqueSorted(memoryRows.map((memory) => memory.lifecycleStatus)),
      sensitivities: uniqueSorted(memoryRows.map((memory) => memory.sensitivity)),
      branchStatuses: uniqueSorted(memoryRows.map((memory) => memory.branchStatus)),
    },
  };
}

export function normalizeOpsReadOnly(
  dashboard: DashboardTables,
  source: "fixture" | "live" = "live",
): OpsReadOnlyView {
  const capability = normalizeOpsCapability(dashboard);
  const maintenanceRuns = dashboard.maintenance_runs
    .slice()
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    .map(normalizeMaintenanceRun);
  const taskAttempts = dashboard.maintenance_task_attempts
    .slice()
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    .map(normalizeMaintenanceTaskAttempt);
  const adminAudits = dashboard.admin_action_audits
    .slice()
    .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
    .map(normalizeAdminAudit);
  const quotaLimits = dashboard.quota_limits
    .slice()
    .sort((left, right) => left.unit.localeCompare(right.unit))
    .map(normalizeQuotaLimit);

  return {
    source,
    capability,
    summary: {
      maintenanceRuns: { kind: "available", label: "Maintenance runs", value: maintenanceRuns.length },
      taskAttempts: { kind: "available", label: "Task attempts", value: taskAttempts.length },
      adminAudits: { kind: "available", label: "Admin audits", value: adminAudits.length },
      quotaLimits: { kind: "available", label: "Quota limits", value: quotaLimits.length },
    },
    maintenanceRuns,
    taskAttempts,
    adminAudits,
    quotaLimits,
  };
}

export function classifyRequestError(error: unknown): RequestState {
  if (!(error instanceof Error)) {
    return { kind: "error", message: "Unknown request failure" };
  }
  const name = error.name;
  if (name === "ForbiddenError") {
    return error.message.toLowerCase().includes("missing") || error.message.toLowerCase().includes("api key")
      ? { kind: "unauthorized", message: error.message }
      : { kind: "forbidden", message: error.message };
  }
  if (name === "NotFoundError") {
    return { kind: "not_found", message: error.message };
  }
  if (name === "RateLimitedError") {
    return { kind: "quota_limited", message: error.message };
  }
  if (name === "TypeError") {
    return { kind: "connection_failed", message: error.message };
  }
  return { kind: "error", message: error.message };
}

export interface NormalizeRunExplorerInput {
  runId: string;
  timeline: AgentEvent[];
  stateTree: StateNode[];
  steps: AgentStep[];
  profile: ProfileEvent[];
}

export function normalizeRunExplorer({
  profile,
  runId,
  stateTree,
  steps,
  timeline,
}: NormalizeRunExplorerInput): RunExplorerView {
  const profilePhases = profile
    .slice()
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
    .map(normalizeProfilePhase);

  return {
    runId,
    timeline: timeline
      .slice()
      .sort((left, right) => left.sequence_no - right.sequence_no)
      .map(normalizeTimelineEvent),
    steps: steps
      .slice()
      .sort((left, right) => Date.parse(left.started_at) - Date.parse(right.started_at))
      .map(normalizeRunStep),
    stateNodes: stateTree
      .slice()
      .sort((left, right) => left.path.localeCompare(right.path))
      .map((node) => ({
        nodeId: node.node_id,
        parentId: node.parent_id ?? null,
        stepId: node.step_id ?? null,
        nodeType: node.node_type,
        status: node.status,
        statusTone: statusTone(node.status),
        goal: node.goal ?? "No goal recorded",
        summary: node.summary ?? "No summary recorded",
        depth: node.depth,
        path: node.path,
        failureReason: node.failure_reason ?? null,
      })),
    profilePhases,
    profileTotals: {
      latencyMs: sum(profilePhases, (phase) => phase.latencyMs),
      actualTokens: sum(profilePhases, (phase) => phase.inputTokens + phase.outputTokens),
      candidateCount: sum(profilePhases, (phase) => phase.candidateCount),
      acceptedCount: sum(profilePhases, (phase) => phase.acceptedCount),
      rejectedCount: sum(profilePhases, (phase) => phase.rejectedCount),
    },
  };
}

export interface NormalizeAccessReplayInput {
  accessId: string;
  inspection: AccessInspection;
  replay: ReplayRetrievalResult;
}

export function normalizeAccessReplay({
  accessId,
  inspection,
  replay,
}: NormalizeAccessReplayInput): AccessReplayView {
  const gateDecisions = inspection.gate_decisions.map(normalizeGateDecision);
  const contextBlocks = inspection.context_blocks.map(normalizeContextBlock);
  const replayedContextBlocks = replay.replayed_context_blocks.map(normalizeContextBlock);
  const decisionGroups = normalizeDecisionGroups(gateDecisions);

  return {
    accessId,
    runId: replay.run_id ?? null,
    stepId: replay.step_id ?? null,
    workspaceId: replay.workspace_id,
    query: inspection.query ?? replay.query ?? "Unlabeled retrieval",
    strategy: inspection.retrieval_strategy,
    tokenBudget: replay.token_budget,
    topK: replay.top_k,
    policy: {
      policyVersion: inspection.policy_version ?? replay["policy_version"] as string | null | undefined ?? null,
      policyHash: inspection.policy_hash ?? replay["policy_hash"] as string | null | undefined ?? null,
    },
    candidates: inspection.candidates.map(normalizeGateDecision),
    gateDecisions,
    decisionGroups,
    contextBlocks,
    negativeEvidenceBlocks: contextBlocks.filter((block) => block.isNegativeEvidence),
    replayedContextBlocks,
    compactionLogCount: replay.compaction_logs.length,
    replayDrift: normalizeReplayDrift(replay.diffs, replay.warnings),
  };
}

function normalizeMemoryAtlasItem(memory: MemoryItem): MemoryAtlasItemView {
  const secretLike = isSensitiveMemory(memory);
  return {
    memoryId: memory.memory_id,
    workspaceId: memory.workspace_id,
    runId: memory.run_id ?? null,
    sessionId: memory.session_id ?? null,
    type: memory.memory_type,
    scope: memory.scope,
    lifecycleStatus: memory.status,
    branchStatus: memory.branch_status,
    sensitivity: memory.sensitivity,
    embeddingStatus: memory.embedding_status,
    displayKey: displayKey(memory.key),
    displayValue: displayMemoryText(memory.value ?? "", memory, "value"),
    displayContent: displayMemoryText(memory.content, memory, "content"),
    summary: safeInlineText(memory.summary ?? (secretLike ? "Sensitive memory hidden" : "No summary returned")),
    riskBadges: riskBadges(memory),
    statusTone: statusTone(memory.status),
    sensitivityTone: sensitivityTone(memory.sensitivity, memory),
    createdAt: memory.created_at,
    updatedAt: memory.updated_at,
  };
}

function normalizeMemoryVersion(version: MemoryVersionRecord): MemoryVersionView {
  return {
    versionId: version.version_id,
    memoryId: version.memory_id,
    versionNo: version.version_no,
    changeReason: safeInlineText(version.change_reason),
    snapshotPreview: previewJson(sanitizeSnapshot(version.snapshot)),
    createdAt: version.created_at,
  };
}

function normalizeMemoryConflict(conflict: MemoryConflictRecord): MemoryConflictView {
  return {
    conflictId: conflict.conflict_id,
    subjectKey: displayKey(conflict.subject_key),
    memoryIds: conflict.memory_ids,
    status: conflict.status,
    detectedBy: safeInlineText(conflict.detected_by),
    explanationPreview: safeInlineText(conflict.explanation),
    createdAt: conflict.created_at,
    resolvedAt: conflict.resolved_at ?? null,
  };
}

function normalizeMemoryAtlasDetail(
  memory: MemoryAtlasItemView,
  versions: MemoryVersionView[],
  conflicts: MemoryConflictView[],
): MemoryAtlasDetailView {
  return {
    memory,
    versions: versions.filter((version) => version.memoryId === memory.memoryId),
    conflicts: conflicts.filter((conflict) => conflict.memoryIds.includes(memory.memoryId)),
  };
}

function normalizeMaintenanceRun(run: MaintenanceRunRecord) {
  return {
    schedulerRunId: run.scheduler_run_id,
    workspaceId: run.workspace_id,
    requestedBy: safeInlineText(run.requested_by),
    reason: safeInlineText(run.reason ?? "No reason returned"),
    operations: run.operations,
    dryRun: run.dry_run,
    status: run.status,
    summaryPreview: previewJson(sanitizeSnapshot(run.summary)),
    warningCount: run.warnings.length,
    startedAt: run.started_at ?? null,
    finishedAt: run.finished_at ?? null,
    createdAt: run.created_at,
  };
}

function normalizeMaintenanceTaskAttempt(attempt: MaintenanceTaskAttemptRecord) {
  return {
    attemptId: attempt.attempt_id,
    schedulerRunId: attempt.scheduler_run_id,
    workspaceId: attempt.workspace_id,
    operation: attempt.operation,
    status: attempt.status,
    attemptNo: attempt.attempt_no,
    resultPreview: previewJson(sanitizeSnapshot(attempt.result)),
    errorSummary: attempt.error_summary === null || attempt.error_summary === undefined
      ? null
      : safeInlineText(attempt.error_summary),
    startedAt: attempt.started_at ?? null,
    finishedAt: attempt.finished_at ?? null,
  };
}

function normalizeAdminAudit(audit: AdminActionAuditRecord) {
  return {
    adminActionId: audit.admin_action_id,
    workspaceId: audit.workspace_id,
    principalId: safeInlineText(audit.principal_id),
    action: safeInlineText(audit.action),
    targetType: safeInlineText(audit.target_type),
    targetId: audit.target_id === null || audit.target_id === undefined ? null : safeInlineText(audit.target_id),
    metadataPreview: previewJson(sanitizeSnapshot(audit.metadata)),
    createdAt: audit.created_at,
  };
}

function normalizeQuotaLimit(limit: QuotaLimitRecord) {
  return {
    quotaLimitId: limit.quota_limit_id,
    workspaceId: limit.workspace_id,
    principalId: limit.principal_id ?? null,
    unit: limit.unit,
    limit: limit.limit,
    windowSeconds: limit.window_seconds,
    createdBy: safeInlineText(limit.created_by),
    updatedAt: limit.updated_at,
  };
}

function normalizeAccess(access: MemoryAccessLog) {
  const totalDecisions = access.accepted_count + access.rejected_count;
  const gateRatioLabel = totalDecisions === 0
    ? "No gate decisions"
    : `${access.accepted_count}/${totalDecisions} accepted`;

  return {
    accessId: access.access_id,
    runId: access.run_id ?? null,
    workspaceId: access.workspace_id,
    strategy: access.retrieval_strategy,
    query: access.query ?? "Unlabeled retrieval",
    accepted: access.accepted_count,
    rejected: access.rejected_count,
    tokenBudget: access.token_budget,
    actualTokens: access.actual_tokens,
    gateRatioLabel,
    createdAt: access.created_at,
  };
}

function normalizeTimelineEvent(event: AgentEvent): RunTimelineEventView {
  const status = event.status ?? event.event_type;
  return {
    eventId: event.event_id,
    sequenceNo: event.sequence_no,
    role: event.role,
    eventType: event.event_type,
    title: event.content ?? event.content_digest ?? `${event.role} ${event.event_type}`,
    content: event.content ?? "Content unavailable",
    contentDigest: event.content_digest ?? null,
    stepId: event.step_id,
    stateNodeId: event.state_node_id ?? null,
    statusLabel: status,
    statusTone: statusTone(status),
    createdAt: event.created_at,
    meta: [
      `seq ${event.sequence_no}`,
      event.role,
      event.event_type,
      event.tool_name ?? "no tool",
    ],
  };
}

function normalizeRunStep(step: AgentStep) {
  return {
    stepId: step.step_id,
    stateNodeId: step.state_node_id ?? null,
    intent: step.intent ?? "No intent recorded",
    status: step.status,
    statusTone: statusTone(step.status),
    startedAt: step.started_at,
    finishedAt: step.finished_at ?? null,
    durationLabel: formatDuration(step.started_at, step.finished_at ?? null),
    recoveryFromStepId: step.recovery_from_step_id ?? null,
    errorMessage: step.error_message ?? null,
  };
}

function normalizeProfilePhase(event: ProfileEvent): RunProfilePhaseView {
  return {
    profileId: event.profile_id,
    phase: event.phase,
    operation: event.operation ?? event.phase,
    latencyMs: event.latency_ms,
    inputTokens: event.input_tokens,
    outputTokens: event.output_tokens,
    candidateCount: event.candidate_count,
    acceptedCount: event.accepted_count,
    rejectedCount: event.rejected_count,
    createdAt: event.created_at,
    tone: profileTone(event),
  };
}

function normalizeGateDecision(decision: GateDecisionView): CandidateDecisionView {
  return {
    memoryId: decision.memory_id,
    content: decision.content,
    layer: decision.layer,
    decision: decision.decision,
    rejectReason: decision.reject_reason ?? null,
    branchStatus: decision.branch_status ?? null,
    relevanceScore: decision.relevance_score,
    stateMatchScore: decision.state_match_score,
    freshnessScore: decision.freshness_score,
    trustScore: decision.trust_score,
    riskScore: decision.risk_score,
    finalScore: decision.final_score,
    tone: decisionTone(decision.decision),
  };
}

function normalizeDecisionGroups(decisions: CandidateDecisionView[]): Record<GateDecisionType, DecisionGroupView> {
  return {
    accept: decisionGroup("accept", decisions),
    warn: decisionGroup("warn", decisions),
    degrade: decisionGroup("degrade", decisions),
    reject: decisionGroup("reject", decisions),
  };
}

function decisionGroup(decision: GateDecisionType, decisions: CandidateDecisionView[]): DecisionGroupView {
  return {
    decision,
    label: decisionLabel(decision),
    count: decisions.filter((item) => item.decision === decision).length,
    tone: decisionTone(decision),
  };
}

function normalizeContextBlock(block: ContextBlock, index: number): ContextBlockView {
  return {
    index,
    type: block.type,
    source: block.source ?? null,
    memoryId: block.memory_id ?? null,
    reason: block.reason ?? null,
    content: block.content,
    tokens: block.tokens,
    isNegativeEvidence: block.type === "avoided_attempts" || block.source === "negative_evidence",
  };
}

function normalizeReplayDrift(diffs: ReplayDiffItem[], warnings: string[]) {
  if (diffs.length === 0) {
    return {
      diffCount: 0,
      worstSeverity: null,
      severityLabel: "No replay drift",
      warningCount: warnings.length,
    };
  }

  const worst = ["critical", "error", "warning", "info"].find((severity) => (
    diffs.some((diff) => diff.severity.toLowerCase() === severity)
  )) ?? diffs[0]?.severity ?? "unknown";

  return {
    diffCount: diffs.length,
    worstSeverity: worst,
    severityLabel: `${diffs.length} replay drift ${diffs.length === 1 ? "item" : "items"}`,
    warningCount: warnings.length,
  };
}

function normalizeBenchmarkSummary(summary: Record<string, Record<string, number>>): BenchmarkStrategyView[] {
  const metricKeys = [...new Set(Object.values(summary).flatMap((metrics) => Object.keys(metrics)))].sort();
  return Object.keys(summary).sort(compareStrategyIds).map((strategy) => ({
    strategy,
    label: strategyLabel(strategy),
    metrics: Object.fromEntries(metricKeys.map((metricKey) => [
      metricKey,
      normalizeMetricNumber(summary[strategy]?.[metricKey], metricLabel(metricKey)),
    ])),
  }));
}

interface BenchmarkCaseSource {
  caseId: string;
  name: string;
  description: string;
  tags: string[];
  strategies: string[];
}

interface BenchmarkResultSource {
  resultId: string;
  caseId: string;
  strategy: string;
  metrics: Record<string, unknown>;
  passed: boolean | null;
  runId: string | null;
  accessId: string | null;
  createdAt: string | null;
}

function normalizeBenchmarkCases(dashboard: DashboardTables): BenchmarkCaseSource[] {
  const cases = new Map<string, BenchmarkCaseSource>();
  for (const row of dashboard.benchmark_cases) {
    const record = asRecord(row);
    const caseId = stringField(record, "case_id");
    if (caseId === null) continue;
    const config = asRecord(record.config);
    cases.set(caseId, {
      caseId,
      name: stringField(record, "name") ?? caseId,
      description: stringField(record, "description") ?? "No case description returned.",
      tags: [],
      strategies: stringArray(config.strategies),
    });
  }
  for (const row of dashboard.eval_cases) {
    const record = asRecord(row);
    const caseId = stringField(record, "eval_case_id");
    if (caseId === null) continue;
    const config = asRecord(record.config);
    const existing = cases.get(caseId);
    cases.set(caseId, {
      caseId,
      name: stringField(record, "name") ?? existing?.name ?? caseId,
      description: stringField(record, "description") ?? existing?.description ?? "No case description returned.",
      tags: stringArray(record.tags),
      strategies: mergeStrings(existing?.strategies ?? [], stringArray(config.strategies)),
    });
  }
  for (const row of [...dashboard.benchmark_results, ...dashboard.eval_results]) {
    const result = normalizeBenchmarkResult(row);
    if (result === null || cases.has(result.caseId)) continue;
    cases.set(result.caseId, {
      caseId: result.caseId,
      name: result.caseId,
      description: "Case metadata was not returned with this result row.",
      tags: [],
      strategies: [result.strategy],
    });
  }
  return [...cases.values()].sort(compareBenchmarkCases);
}

function normalizeBenchmarkResults(dashboard: DashboardTables): BenchmarkResultSource[] {
  return [...dashboard.benchmark_results, ...dashboard.eval_results]
    .map(normalizeBenchmarkResult)
    .filter((row): row is BenchmarkResultSource => row !== null)
    .sort((left, right) => {
      if (left.caseId !== right.caseId) return compareCaseIds(left.caseId, right.caseId);
      const strategyOrder = compareStrategyIds(left.strategy, right.strategy);
      if (strategyOrder !== 0) return strategyOrder;
      return (left.createdAt ?? "").localeCompare(right.createdAt ?? "");
    });
}

function normalizeBenchmarkResult(row: unknown): BenchmarkResultSource | null {
  const record = asRecord(row);
  const caseId = stringField(record, "case_id") ?? stringField(record, "eval_case_id");
  const strategy = stringField(record, "strategy");
  if (caseId === null || strategy === null) return null;
  const resultId = stringField(record, "eval_result_id") ?? stringField(record, "result_id") ?? `${caseId}:${strategy}`;
  return {
    resultId,
    caseId,
    strategy,
    metrics: asRecord(record.metrics),
    passed: typeof record.passed === "boolean" ? record.passed : null,
    runId: stringField(record, "run_id"),
    accessId: stringField(record, "access_id"),
    createdAt: stringField(record, "created_at"),
  };
}

function collectBenchmarkStrategies(
  dashboard: DashboardTables,
  cases: BenchmarkCaseSource[],
  results: BenchmarkResultSource[],
): string[] {
  const ids = new Set<string>(STRATEGY_ORDER);
  for (const strategy of Object.keys(dashboard.benchmark_summary ?? {})) ids.add(strategy);
  for (const caseRecord of cases) {
    for (const strategy of caseRecord.strategies) ids.add(strategy);
  }
  for (const result of results) ids.add(result.strategy);
  return [...ids].sort(compareStrategyIds);
}

function normalizeBenchmarkCaseRow(
  caseRecord: BenchmarkCaseSource,
  strategyIds: string[],
  results: BenchmarkResultSource[],
): BenchmarkCaseRowView {
  return {
    caseId: caseRecord.caseId,
    name: caseRecord.name,
    description: caseRecord.description,
    tags: caseRecord.tags,
    cells: Object.fromEntries(strategyIds.map((strategy) => {
      const result = latestBenchmarkResult(results, caseRecord.caseId, strategy);
      return [strategy, normalizeBenchmarkCell(strategy, result)];
    })),
  };
}

function normalizeBenchmarkCell(strategy: string, result: BenchmarkResultSource | null): BenchmarkMatrixCellView {
  if (result === null) {
    return {
      strategy,
      state: "not_run",
      label: "Not run",
      tone: "neutral",
      metric: { kind: "unavailable", label: "Task success", reason: "not run" },
      resultId: null,
      runId: null,
      accessId: null,
    };
  }

  const taskSuccess = metricFromRecord(result.metrics, "task_success", "Task success");
  if (result.passed === true) {
    return {
      strategy,
      state: "passed",
      label: "Passed",
      tone: "good",
      metric: taskSuccess,
      resultId: result.resultId,
      runId: result.runId,
      accessId: result.accessId,
    };
  }
  if (result.passed === false) {
    return {
      strategy,
      state: "failed",
      label: "Failed",
      tone: "danger",
      metric: taskSuccess,
      resultId: result.resultId,
      runId: result.runId,
      accessId: result.accessId,
    };
  }
  return {
    strategy,
    state: "unavailable",
    label: "Unavailable",
    tone: "warning",
    metric: { kind: "unavailable", label: "Task success", reason: "explicit pass flag not returned" },
    resultId: result.resultId,
    runId: result.runId,
    accessId: result.accessId,
  };
}

function normalizeBenchmarkCaseDrawer(
  caseRow: BenchmarkCaseRowView,
  results: BenchmarkResultSource[],
): BenchmarkCaseDrawerView {
  const result = preferredResultForCase(caseRow.caseId, results);
  return {
    caseId: caseRow.caseId,
    name: caseRow.name,
    description: caseRow.description,
    strategy: result?.strategy ?? null,
    metrics: result === undefined ? [] : Object.keys(result.metrics).sort().map((metricKey) => benchmarkLine(
      metricKey,
      metricLabel(metricKey),
      metricFromRecord(result.metrics, metricKey, metricLabel(metricKey)),
      metricTone(metricKey),
      "Source metric returned by the benchmark/eval row.",
    )),
    links: result === undefined ? [] : benchmarkLinks(result),
  };
}

function emptyBenchmarkDrawer(): BenchmarkCaseDrawerView {
  return {
    caseId: "none",
    name: "No benchmark cases",
    description: "No benchmark or eval cases were returned.",
    strategy: null,
    metrics: [],
    links: [],
  };
}

function normalizeBenchmarkContamination(summary: Record<string, Record<string, number>>): BenchmarkContaminationView {
  const baselineMetric = firstSummaryMetric(summary, "baseline_1", [
    "positive_contamination_rate",
    "failed_branch_contamination_rate",
  ], "Positive contamination");
  const variantMetric = firstSummaryMetric(summary, "variant_2", [
    "positive_contamination_rate",
    "failed_branch_contamination_rate",
  ], "Positive contamination");
  const delta = baselineMetric.kind === "available" && variantMetric.kind === "available"
    ? {
      kind: "available" as const,
      label: "Baseline minus variant_2",
      value: baselineMetric.value - variantMetric.value,
      tone: baselineMetric.value - variantMetric.value >= 0 ? "good" as const : "warning" as const,
    }
    : { kind: "unavailable" as const, label: "Baseline minus variant_2", reason: "requires both comparator rows" };

  return {
    baseline: benchmarkLine(
      "baseline_1_contamination",
      "baseline_1 contamination",
      baselineMetric,
      "danger",
      "Uses explicit positive_contamination_rate or failed_branch_contamination_rate.",
    ),
    variantTwo: benchmarkLine(
      "variant_2_contamination",
      "variant_2 contamination",
      variantMetric,
      "good",
      "Uses explicit positive_contamination_rate or failed_branch_contamination_rate.",
    ),
    delta,
  };
}

function normalizeBenchmarkTokenBloat(
  summary: Record<string, Record<string, number>>,
  results: BenchmarkResultSource[],
): BenchmarkTokenBloatView {
  const hasLongContextRows = results.some((result) => result.strategy === "long_context");
  const hasComparatorRows = results.some((result) => result.strategy === "variant_2");
  const longContext = hasLongContextRows ? firstSummaryMetric(summary, "long_context", [
    "avg_memory_token_overhead",
    "avg_actual_tokens",
  ], "Long-context tokens") : { kind: "unavailable" as const, label: "Long-context tokens", reason: "long_context row not returned" };
  const comparator = hasComparatorRows ? firstSummaryMetric(summary, "variant_2", [
    "avg_memory_token_overhead",
    "avg_actual_tokens",
  ], "variant_2 tokens") : { kind: "unavailable" as const, label: "variant_2 tokens", reason: "variant_2 comparator row not returned" };
  const available = longContext.kind === "available" && comparator.kind === "available";
  return {
    state: available ? "available" : "comparator_unavailable",
    longContext,
    comparator,
    overhead: available
      ? { kind: "available", label: "Token overhead", value: longContext.value - comparator.value, tone: "warning" }
      : { kind: "unavailable", label: "Token overhead", reason: "requires long_context and variant_2 token metrics" },
  };
}

function normalizeBenchmarkCompaction(summary: Record<string, Record<string, number>>): BenchmarkCompactionView {
  return {
    triggerRate: benchmarkLine(
      "compaction_trigger_rate",
      "Compaction trigger rate",
      summaryMetric(summary, "variant_2", "compaction_trigger_rate", "Compaction trigger rate"),
      "info",
      "Explicit rate from benchmark_summary.variant_2.",
    ),
    constraintRetention: benchmarkLine(
      "constraint_retention_hit_rate",
      "Constraint retention",
      summaryMetric(summary, "variant_2", "constraint_retention_hit_rate", "Constraint retention"),
      "good",
      "Explicit constraint_retention_hit_rate only.",
    ),
    unsafeLeakage: benchmarkLine(
      "unsafe_compaction_leakage_rate",
      "Unsafe compaction leakage",
      summaryMetric(summary, "variant_2", "unsafe_compaction_leakage_rate", "Unsafe compaction leakage"),
      "danger",
      "Explicit unsafe_compaction_leakage_rate only.",
    ),
    retainedNegativeUnsafeLeakage: benchmarkLine(
      "compaction_retained_negative_unsafe_leakage_rate",
      "Retained negative unsafe leakage",
      summaryMetric(
        summary,
        "variant_2",
        "compaction_retained_negative_unsafe_leakage_rate",
        "Retained negative unsafe leakage",
      ),
      "danger",
      "Explicit compaction_retained_negative_unsafe_leakage_rate only.",
    ),
  };
}

function normalizeBenchmarkNegativeEvidence(summary: Record<string, Record<string, number>>): BenchmarkNegativeEvidenceView {
  return {
    promptBlocks: benchmarkLine(
      "negative_lesson_retained_rate",
      "Prompt negative lesson retained",
      summaryMetric(summary, "variant_2", "negative_lesson_retained_rate", "Prompt negative lesson retained"),
      "warning",
      "Prompt avoided_attempts / negative_evidence retention, not positive context.",
    ),
    retainedMetadata: benchmarkLine(
      "compaction_negative_lesson_retained_rate",
      "Retained metadata lesson",
      summaryMetric(summary, "variant_2", "compaction_negative_lesson_retained_rate", "Retained metadata lesson"),
      "info",
      "Dropped negative evidence retained as compaction metadata.",
    ),
    unsafeLeakage: benchmarkLine(
      "unsafe_negative_leakage_rate",
      "Unsafe negative leakage",
      summaryMetric(summary, "variant_2", "unsafe_negative_leakage_rate", "Unsafe negative leakage"),
      "danger",
      "Explicit unsafe_negative_leakage_rate only.",
    ),
  };
}

function benchmarkLine(
  id: string,
  label: string,
  metric: MetricNumber,
  tone: BenchmarkMetricLineView["tone"],
  note: string,
): BenchmarkMetricLineView {
  return { id, label, metric, tone, note };
}

function latestBenchmarkResult(
  results: BenchmarkResultSource[],
  caseId: string,
  strategy: string,
): BenchmarkResultSource | null {
  const matches = results.filter((result) => result.caseId === caseId && result.strategy === strategy);
  return matches[matches.length - 1] ?? null;
}

function preferredResultForCase(caseId: string, results: BenchmarkResultSource[]): BenchmarkResultSource | undefined {
  const caseResults = results.filter((result) => result.caseId === caseId);
  return caseResults.find((result) => result.strategy === "variant_2" && (result.runId !== null || result.accessId !== null))
    ?? caseResults.find((result) => result.runId !== null || result.accessId !== null)
    ?? caseResults[0];
}

function benchmarkLinks(result: BenchmarkResultSource): { href: string; label: string }[] {
  const links: { href: string; label: string }[] = [];
  if (result.runId !== null) links.push({ href: `/runs/${encodeURIComponent(result.runId)}`, label: "Open run" });
  if (result.accessId !== null) links.push({ href: `/access/${encodeURIComponent(result.accessId)}`, label: "Replay access" });
  return links;
}

function summaryMetric(
  summary: Record<string, Record<string, number>> | undefined,
  strategy: string,
  metricKey: string,
  label: string,
): MetricNumber {
  return normalizeMetricNumber(summary?.[strategy]?.[metricKey], label);
}

function firstSummaryMetric(
  summary: Record<string, Record<string, number>> | undefined,
  strategy: string,
  metricKeys: string[],
  label: string,
): MetricNumber {
  for (const metricKey of metricKeys) {
    const metric = summaryMetric(summary, strategy, metricKey, label);
    if (metric.kind === "available") return metric;
  }
  return { kind: "unavailable", label, reason: "not provided" };
}

function metricFromRecord(record: Record<string, unknown>, metricKey: string, label: string): MetricNumber {
  return normalizeMetricNumber(record[metricKey], label);
}

function metricTone(metricKey: string): BenchmarkMetricLineView["tone"] {
  if (metricKey.includes("leakage") || metricKey.includes("contamination")) return "danger";
  if (metricKey.includes("retention") || metricKey.includes("success") || metricKey.includes("blocked")) return "good";
  if (metricKey.includes("token") || metricKey.includes("compaction")) return "warning";
  return "neutral";
}

function normalizeRunGallery(runs: RunSummaryView[], accesses: ReturnType<typeof normalizeAccess>[]): RunGalleryItemView[] {
  return runs.map((run) => {
    const runAccesses = accesses
      .filter((access) => access.runId === run.runId)
      .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt));
    const latestAccess = runAccesses[0] ?? null;
    return {
      ...run,
      durationLabel: formatDuration(run.startedAt, run.finishedAt),
      latestAccess,
      dominantStrategy: latestAccess === null ? null : strategyIdentity(latestAccess.strategy),
    };
  });
}

function normalizeSafetySignals(summary: ObservabilitySummary | undefined): SignalMetricView[] {
  return [
    signal(summary, "failed_branch_rejected", "Failed branch rejected", "danger"),
    signal(summary, "failed_branch_injected", "Failed branch injected", "danger"),
    signal(summary, "stale_rejected", "Stale rejected", "warning"),
    signal(summary, "stale_injected", "Stale injected", "warning"),
    signal(summary, "risk_blocked", "Risk blocked", "danger"),
    signal(summary, "tool_sensitive_blocked", "Tool-sensitive blocked", "danger"),
    signal(summary, "destructive_command_blocked", "Destructive blocked", "danger"),
    signal(summary, "workspace_mismatch_rejected", "Workspace mismatch rejected", "danger"),
    signal(summary, "workspace_leakage", "Workspace leakage", "danger"),
    signal(summary, "superseded_injected", "Superseded injected", "warning"),
  ];
}

function normalizeCompactionSignals(summary: ObservabilitySummary | undefined): SignalMetricView[] {
  return [
    signal(summary, "history_summary_count", "History summaries", "info"),
    signal(summary, "total_dropped_blocks", "Dropped blocks", "warning"),
    signal(summary, "compaction_trigger_rate", "Trigger rate", "info", "ratio"),
    signal(summary, "avg_compression_ratio", "Compression ratio", "info", "ratio"),
  ];
}

function normalizeNegativeEvidenceSignals(summary: ObservabilitySummary | undefined): SignalMetricView[] {
  return [
    signal(summary, "degraded_negative_evidence_count", "Degraded decisions", "warning"),
    signal(summary, "negative_evidence_block_count", "Prompt blocks", "warning"),
    signal(summary, "retained_negative_evidence_count", "Retained lessons", "info"),
    signal(summary, "sanitized_failure_notice_count", "Sanitized notices", "warning"),
    signal(summary, "sanitized_retained_negative_evidence_count", "Sanitized retained lessons", "warning"),
  ];
}

function signal(
  summary: ObservabilitySummary | undefined,
  id: string,
  label: string,
  tone: SignalMetricView["tone"],
  unit: SignalMetricView["unit"] = "count",
): SignalMetricView {
  return {
    id,
    label,
    metric: normalizeMetricNumber(summary?.[id], label, tone),
    tone,
    unit,
  };
}

function strategyIdentity(strategy: RetrievalStrategy | string): StrategyIdentityView {
  return {
    strategy,
    label: strategyLabel(strategy),
  };
}

function normalizeOpsCapability(dashboard: DashboardTables): CapabilityState {
  const explicit = dashboard["admin_capability"];
  if (explicit === "forbidden") {
    return { kind: "forbidden", message: "Owner credentials are required for operations tables." };
  }
  if (explicit === "authorized_empty") {
    return { kind: "authorized_empty", message: "Owner access is active, but no operations rows were returned." };
  }
  if (explicit === "unknown") {
    return { kind: "unknown", message: "The API did not report operations-table capability." };
  }

  const presentTables = ADMIN_TABLE_NAMES.filter((name) => Array.isArray(dashboard[name]));
  if (presentTables.length === 0) {
    return { kind: "unsupported", message: "This API does not expose read-only operations tables." };
  }

  const rowCount = presentTables.reduce((total, name) => total + ((dashboard[name] as unknown[])?.length ?? 0), 0);
  if (rowCount > 0) {
    return { kind: "authorized", rowCount };
  }

  return {
    kind: "owner_only_unavailable",
    message: "No owner-gated rows are visible. Provide owner credentials to distinguish empty data from unavailable data.",
  };
}

function collectWorkspaceIds(dashboard: DashboardTables, summary?: ObservabilitySummary): string[] {
  const ids = new Set<string>();
  if (typeof summary?.workspace_id === "string" && summary.workspace_id.length > 0) {
    ids.add(summary.workspace_id);
  }
  for (const run of dashboard.runs) ids.add(run.workspace_id);
  for (const access of dashboard.accesses) ids.add(access.workspace_id);
  for (const version of dashboard.memory_versions) ids.add(version.workspace_id);
  for (const conflict of dashboard.memory_conflicts) ids.add(conflict.workspace_id);
  return [...ids].sort();
}

function collectMemoryWorkspaceIds(dashboard: DashboardTables, memories: MemoryItem[]): string[] {
  const ids = new Set<string>();
  for (const memory of memories) ids.add(memory.workspace_id);
  for (const version of dashboard.memory_versions) ids.add(version.workspace_id);
  for (const conflict of dashboard.memory_conflicts) ids.add(conflict.workspace_id);
  return [...ids].sort();
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort();
}

function totalSafetySignals(summary: ObservabilitySummary | undefined): number | undefined {
  if (summary === undefined) return undefined;
  return summary.failed_branch_rejected
    + summary.failed_branch_injected
    + summary.degraded_negative_evidence_count
    + summary.sanitized_failure_notice_count
    + summary.risk_blocked
    + summary.tool_sensitive_blocked
    + summary.destructive_command_blocked
    + summary.workspace_mismatch_rejected
    + summary.workspace_leakage
    + summary.superseded_injected;
}

function strategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy;
}

function compareStrategyIds(left: string, right: string): number {
  const leftIndex = STRATEGY_ORDER.indexOf(left);
  const rightIndex = STRATEGY_ORDER.indexOf(right);
  if (leftIndex !== -1 && rightIndex !== -1) return leftIndex - rightIndex;
  if (leftIndex !== -1) return -1;
  if (rightIndex !== -1) return 1;
  return left.localeCompare(right);
}

function compareBenchmarkCases(left: BenchmarkCaseSource, right: BenchmarkCaseSource): number {
  return compareCaseIds(left.caseId, right.caseId);
}

function compareCaseIds(left: string, right: string): number {
  const leftNumber = caseNumber(left);
  const rightNumber = caseNumber(right);
  if (leftNumber !== null && rightNumber !== null && leftNumber !== rightNumber) {
    return leftNumber - rightNumber;
  }
  return left.localeCompare(right);
}

function caseNumber(caseId: string): number | null {
  const match = /^case_(\d+)/.exec(caseId);
  if (match === null) return null;
  const value = Number.parseInt(match[1] ?? "", 10);
  return Number.isFinite(value) ? value : null;
}

function metricLabel(metricKey: string): string {
  return metricKey
    .split("_")
    .map((part) => part.length === 0 ? part : part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDuration(startedAt: string, finishedAt: string | null): string {
  if (finishedAt === null) return "Running";
  const started = Date.parse(startedAt);
  const finished = Date.parse(finishedAt);
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return "Duration unavailable";
  const seconds = Math.round((finished - started) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return remainingSeconds === 0 ? `${minutes}m` : `${minutes}m ${remainingSeconds}s`;
}

function decisionLabel(decision: GateDecisionType): string {
  if (decision === "accept") return "Accepted positive context";
  if (decision === "warn") return "Accepted with warning";
  if (decision === "degrade") return "Negative evidence";
  return "Rejected";
}

function decisionTone(decision: GateDecisionType): "neutral" | "good" | "warning" | "danger" | "info" {
  if (decision === "accept") return "good";
  if (decision === "warn" || decision === "degrade") return "warning";
  if (decision === "reject") return "danger";
  return "neutral";
}

function statusTone(status: string): "neutral" | "good" | "warning" | "danger" | "info" {
  if (status === "completed" || status === "success") return "good";
  if (status === "active" || status === "running") return "info";
  if (status === "rolled_back" || status === "degrade" || status === "warn") return "warning";
  if (status === "failed" || status === "cancelled" || status === "error" || status === "reject") return "danger";
  return "neutral";
}

function profileTone(event: ProfileEvent): "neutral" | "good" | "warning" | "danger" | "info" {
  if (event.error_code !== null && event.error_code !== undefined) return "danger";
  if (event.phase === "context_compaction") return "warning";
  if (event.phase === "gate" || event.phase === "safety") return "info";
  return "neutral";
}

function sensitivityTone(sensitivity: string, memory: MemoryItem): "neutral" | "good" | "warning" | "danger" | "info" {
  if (sensitivity === "secret" || memory.risk_flags.contains_secret) return "danger";
  if (memory.risk_flags.destructive_command || memory.risk_flags.production_env || memory.risk_flags.tool_sensitive) return "warning";
  if (sensitivity === "private") return "warning";
  if (sensitivity === "internal") return "info";
  return "good";
}

function sum<T>(items: T[], selector: (item: T) => number): number {
  return items.reduce((total, item) => {
    const value = selector(item);
    return Number.isFinite(value) ? total + value : total;
  }, 0);
}

function isSensitiveMemory(memory: MemoryItem): boolean {
  return memory.sensitivity === "secret"
    || memory.risk_flags.contains_secret
    || memory.risk_flags.destructive_command
    || memory.risk_flags.production_env
    || secretLikeKey(memory.key ?? "");
}

function displayKey(key: string | null | undefined): DisplayKeyView {
  if (key === null || key === undefined || key.length === 0) {
    return { label: "unkeyed", isMasked: false, reason: null };
  }
  if (secretLikeKey(key)) {
    return { label: maskKey(key), isMasked: true, reason: "secret-like key" };
  }
  return { label: safeInlineText(key), isMasked: false, reason: null };
}

function displayMemoryText(
  value: string | null | undefined,
  memory: MemoryItem,
  field: "value" | "content",
): DisplayTextView {
  if (memory.sensitivity === "secret" || memory.risk_flags.contains_secret || secretLikeKey(memory.key ?? "")) {
    return {
      state: "secret",
      preview: field === "value" ? "Secret value hidden" : "Secret content hidden",
      expandable: false,
    };
  }
  if (memory.risk_flags.destructive_command || memory.risk_flags.production_env || unsafeString(value ?? "")) {
    return { state: "sanitized", preview: "Risky command hidden", expandable: false };
  }
  if (value === null || value === undefined || value.length === 0) {
    return { state: "empty", preview: "Unavailable", expandable: false };
  }
  const safe = safeInlineText(value);
  return {
    state: "collapsed",
    preview: safe.length > 160 ? `${safe.slice(0, 157)}...` : safe,
    expandable: safe.length > 160,
  };
}

function riskBadges(memory: MemoryItem): MemoryRiskBadgeView[] {
  const badges: MemoryRiskBadgeView[] = [];
  if (memory.sensitivity === "secret" || memory.risk_flags.contains_secret) {
    badges.push({ id: "secret", label: "Secret", tone: "danger" });
  }
  if (memory.risk_flags.destructive_command) {
    badges.push({ id: "destructive_command", label: "Destructive", tone: "danger" });
  }
  if (memory.risk_flags.production_env) {
    badges.push({ id: "production_env", label: "Production", tone: "warning" });
  }
  if (memory.risk_flags.tool_sensitive) {
    badges.push({ id: "tool_sensitive", label: "Tool-sensitive", tone: "warning" });
  }
  if (badges.length === 0) badges.push({ id: "safe_display", label: "Display safe", tone: "good" });
  return badges;
}

function safeInlineText(value: string): string {
  return unsafeString(value) ? "[redacted]" : value;
}

function previewJson(value: unknown): string {
  const serialized = JSON.stringify(value);
  if (serialized === undefined) return "{}";
  return serialized.length > 260 ? `${serialized.slice(0, 257)}...` : serialized;
}

function sanitizeSnapshot(value: unknown, keyHint = ""): unknown {
  if (secretLikeKey(keyHint) || contentLikeKey(keyHint)) {
    return "[redacted]";
  }
  if (typeof value === "string") {
    return unsafeString(value) || secretLikeKey(value) ? "[redacted]" : value;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 12).map((item) => sanitizeSnapshot(item));
  }
  if (typeof value === "object" && value !== null) {
    const output: Record<string, unknown> = {};
    let redactedIndex = 0;
    for (const [key, nestedValue] of Object.entries(value)) {
      const sanitizedKey = secretLikeKey(key) ? `redacted_key_${redactedIndex++}` : key;
      output[sanitizedKey] = sanitizeSnapshot(nestedValue, key);
    }
    return output;
  }
  return "[redacted]";
}

function secretLikeKey(value: string): boolean {
  const lower = value.toLowerCase();
  return [
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "id_token",
    "password",
    "private_key",
    "raw_payload_ref",
    "secret",
    "secret_key",
    "token",
  ].some((needle) => lower.includes(needle));
}

function contentLikeKey(value: string): boolean {
  const lower = value.toLowerCase();
  return lower === "content" || lower === "value" || lower.endsWith("_content") || lower.endsWith("_value");
}

function unsafeString(value: string): boolean {
  const lower = value.toLowerCase();
  return lower.includes("authorization:")
    || lower.includes("bearer ")
    || lower.includes("raw_payload_ref")
    || /\brm\s+-rf\b/iu.test(value)
    || /(^|\s)\/(?:srv\/)?prod(?:\b|\/)/iu.test(value)
    || /\bsk-[a-z0-9_-]{6,}\b/iu.test(value)
    || lower.includes("password=");
}

function maskKey(key: string): string {
  const [prefix] = key.split(/[._:-]/);
  if (prefix !== undefined && prefix.length > 0 && !secretLikeKey(prefix)) {
    return `${prefix}_[redacted]`;
  }
  return "[redacted]";
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringField(record: Record<string, unknown>, field: string): string | null {
  const value = record[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function mergeStrings(left: string[], right: string[]): string[] {
  return [...new Set([...left, ...right])];
}
