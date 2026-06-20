export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type ISODateTime = string;

export type RunStatus = "running" | "completed" | "failed" | "cancelled";
export type StepStatus = "active" | "completed" | "failed" | "cancelled" | "rolled_back";
export type StateNodeType = "root" | "step" | "recovery";
export type StateNodeStatus = "active" | "completed" | "failed" | "rolled_back";
export type EventRole = "user" | "assistant" | "tool" | "system" | "runtime";
export type EventType = "message" | "tool_call" | "tool_result" | "error" | "checkpoint";
export type MemoryType = "working_state" | "profile" | "project" | "episodic" | "tool_evidence" | "procedural";
export type MemoryScope = "workspace" | "user" | "session";
export type BranchStatus = "active" | "failed" | "rolled_back" | "completed";
export type MemoryStatus = "active" | "dormant" | "archived" | "superseded" | "conflicted" | "quarantined" | "pinned" | "deleted";
export type Sensitivity = "public" | "internal" | "private" | "secret";
export type EmbeddingStatus = "pending" | "embedded" | "failed" | "stale";
export type RetrievalStrategy = "baseline_0" | "long_context" | "baseline_1" | "variant_1" | "variant_2" | "variant_3";
export type GateLayer = "hard_policy" | "risk_policy" | "soft_ranking";
export type GateDecisionType = "accept" | "reject" | "degrade" | "warn";
export type ProfilePhase = "retrieval" | "gate" | "context_packing" | "context_compaction" | "ingestion" | "construction" | "rerank" | "generation" | "maintenance" | "quality" | "safety";
export type ExtractionMode = "sync" | "buffered" | "async" | "sync_flush" | "lazy" | "no_extract";
export type MaintenanceOperation =
  | "score_memory"
  | "decay_memory"
  | "archive_memory"
  | "quarantine_memory"
  | "conflict_scan"
  | "dedup_memory"
  | "reindex_memory"
  | "summary_refresh"
  | "procedural_refresh"
  | "profile_refresh";
export type SchedulerRunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type SchedulerTaskStatus = "pending" | "running" | "completed" | "failed" | "skipped";
export type QuotaUnitName = "write_event" | "retrieve_context" | "report_export" | "replay" | "async_task_enqueue";

export interface StartRunRequest {
  session_id: string;
  task?: string | null;
  workspace_id?: string | null;
  metadata?: JsonObject;
}

export interface AgentRun {
  run_id: string;
  workspace_id: string;
  session_id: string;
  task?: string | null;
  status: RunStatus;
  started_at: ISODateTime;
  finished_at?: ISODateTime | null;
  metadata: JsonObject;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface StartStepRequest {
  run_id: string;
  intent?: string | null;
  parent_step_id?: string | null;
  recovery_from_step_id?: string | null;
  goal?: string | null;
  metadata?: JsonObject;
}

export interface AgentStep {
  step_id: string;
  workspace_id: string;
  run_id: string;
  parent_step_id?: string | null;
  recovery_from_step_id?: string | null;
  state_node_id?: string | null;
  intent?: string | null;
  status: StepStatus;
  started_at: ISODateTime;
  finished_at?: ISODateTime | null;
  error_message?: string | null;
  metadata: JsonObject;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface AgentEvent {
  event_id: string;
  workspace_id: string;
  session_id?: string | null;
  run_id: string;
  step_id: string;
  state_node_id?: string | null;
  sequence_no: number;
  event_source?: string | null;
  visibility: string;
  role: EventRole;
  event_type: EventType;
  content?: string | null;
  content_digest?: string | null;
  raw_payload_ref?: string | null;
  redaction_status: string;
  causality_id?: string | null;
  tool_name?: string | null;
  tool_args_digest?: string | null;
  status?: string | null;
  token_input: number;
  token_output: number;
  latency_ms: number;
  metadata: JsonObject;
  created_at: ISODateTime;
  [key: string]: unknown;
}

export interface WriteEventRequest {
  run_id: string;
  step_id: string;
  role?: EventRole;
  event_type?: EventType;
  content?: string | null;
  tool_name?: string | null;
  status?: string | null;
  token_input?: number;
  token_output?: number;
  latency_ms?: number;
  extraction_mode?: ExtractionMode | null;
  event_source?: string | null;
  metadata?: JsonObject;
}

export interface WriteEventResult {
  event: AgentEvent;
  created_memory_ids: string[];
  buffered: boolean;
  queued: boolean;
  task_id?: string | null;
  warnings: string[];
  [key: string]: unknown;
}

export interface FinishStepRequest {
  run_id: string;
  step_id: string;
  status?: StepStatus;
  error_message?: string | null;
  summary?: string | null;
}

export interface StateNode {
  node_id: string;
  workspace_id: string;
  run_id: string;
  parent_id?: string | null;
  step_id?: string | null;
  node_type: StateNodeType;
  status: StateNodeStatus;
  goal?: string | null;
  summary?: string | null;
  raw_event_ids: string[];
  memory_refs: string[];
  branch_reason: JsonObject;
  failure_reason?: string | null;
  depth: number;
  path: string;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface FinishStepResult {
  step: AgentStep;
  state_node: StateNode;
  created_memory_ids: string[];
  [key: string]: unknown;
}

export interface RollbackRequest {
  run_id: string;
  step_id: string;
  reason?: string | null;
}

export interface RollbackResult {
  rolled_back_step_ids: string[];
  rolled_back_node_ids: string[];
  affected_memory_ids: string[];
  [key: string]: unknown;
}

export interface CompleteRunRequest {
  run_id?: string | null;
  status?: RunStatus;
  summary?: string | null;
}

export interface CompleteRunResult {
  run: AgentRun;
  summary_memory_id?: string | null;
  procedural_memory_id?: string | null;
  created_memory_ids: string[];
  [key: string]: unknown;
}

export interface RetrievalRequest {
  run_id: string;
  step_id?: string | null;
  query: string;
  task_intent?: string | null;
  workspace_id?: string | null;
  strategy?: RetrievalStrategy;
  token_budget?: number | null;
  top_k?: number;
}

export interface Provenance {
  run_id?: string | null;
  step_id?: string | null;
  event_id?: string | null;
  state_node_id?: string | null;
  [key: string]: unknown;
}

export interface ContextBlock {
  type: string;
  content: string;
  source?: string | null;
  memory_id?: string | null;
  reason?: string | null;
  provenance?: Provenance | null;
  tokens: number;
  [key: string]: unknown;
}

export interface MemoryContext {
  access_id: string;
  query?: string | null;
  context_blocks: ContextBlock[];
  warnings: string[];
  profile: JsonObject;
  [key: string]: unknown;
}

export interface RiskFlags {
  tool_sensitive: boolean;
  contains_secret: boolean;
  destructive_command: boolean;
  production_env: boolean;
  [key: string]: unknown;
}

export interface GateDecisionView {
  memory_id: string;
  content: string;
  layer: GateLayer;
  decision: GateDecisionType;
  reject_reason?: string | null;
  relevance_score: number;
  state_match_score: number;
  freshness_score: number;
  trust_score: number;
  risk_score: number;
  final_score: number;
  branch_status?: BranchStatus | null;
  [key: string]: unknown;
}

export interface AccessInspection {
  access_id: string;
  query?: string | null;
  task_intent?: string | null;
  retrieval_strategy: RetrievalStrategy;
  candidates: GateDecisionView[];
  gate_decisions: GateDecisionView[];
  context_blocks: ContextBlock[];
  profile: JsonObject;
  warnings: string[];
  policy_version?: string | null;
  policy_hash?: string | null;
  policy_snapshot: JsonObject;
  [key: string]: unknown;
}

export interface MemoryItem {
  memory_id: string;
  workspace_id: string;
  session_id?: string | null;
  run_id?: string | null;
  memory_type: MemoryType;
  key?: string | null;
  value?: string | null;
  scope: MemoryScope;
  content: string;
  summary?: string | null;
  branch_status: BranchStatus;
  status: MemoryStatus;
  sensitivity: Sensitivity;
  embedding_status: EmbeddingStatus;
  risk_flags: RiskFlags;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface MemoryVersionRecord {
  version_id: string;
  memory_id: string;
  workspace_id: string;
  version_no: number;
  snapshot: JsonObject;
  change_reason: string;
  created_at: ISODateTime;
  [key: string]: unknown;
}

export interface MemoryConflictRecord {
  conflict_id: string;
  workspace_id: string;
  subject_key: string;
  memory_ids: string[];
  status: string;
  detected_by: string;
  explanation: string;
  created_at: ISODateTime;
  resolved_at?: ISODateTime | null;
  [key: string]: unknown;
}

export interface MaintenanceRunRecord {
  scheduler_run_id: string;
  workspace_id: string;
  requested_by: string;
  reason?: string | null;
  operations: MaintenanceOperation[];
  dry_run: boolean;
  status: SchedulerRunStatus;
  summary: JsonObject;
  warnings: string[];
  started_at?: ISODateTime | null;
  finished_at?: ISODateTime | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface MaintenanceTaskAttemptRecord {
  attempt_id: string;
  scheduler_run_id: string;
  workspace_id: string;
  operation: MaintenanceOperation;
  status: SchedulerTaskStatus;
  idempotency_key?: string | null;
  attempt_no: number;
  result: JsonObject;
  error_summary?: string | null;
  started_at?: ISODateTime | null;
  finished_at?: ISODateTime | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface AdminActionAuditRecord {
  admin_action_id: string;
  workspace_id: string;
  principal_id: string;
  action: string;
  target_type: string;
  target_id?: string | null;
  metadata: JsonObject;
  created_at: ISODateTime;
  [key: string]: unknown;
}

export interface QuotaLimitRecord {
  quota_limit_id: string;
  workspace_id: string;
  principal_id?: string | null;
  unit: QuotaUnitName;
  limit: number;
  window_seconds: number;
  created_by: string;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  [key: string]: unknown;
}

export interface ProfileEvent {
  profile_id: string;
  run_id?: string | null;
  step_id?: string | null;
  access_id?: string | null;
  phase: ProfilePhase;
  operation?: string | null;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  db_calls: number;
  candidate_count: number;
  accepted_count: number;
  rejected_count: number;
  error_code?: string | null;
  metadata: JsonObject;
  created_at: ISODateTime;
  [key: string]: unknown;
}

export interface MemoryAccessLog {
  access_id: string;
  workspace_id: string;
  run_id?: string | null;
  step_id?: string | null;
  query?: string | null;
  task_intent?: string | null;
  retrieval_strategy: RetrievalStrategy;
  candidate_count: number;
  accepted_count: number;
  rejected_count: number;
  token_budget: number;
  top_k: number;
  actual_tokens: number;
  latency_ms: number;
  policy_version?: string | null;
  policy_hash?: string | null;
  policy_snapshot: JsonObject;
  created_at: ISODateTime;
  [key: string]: unknown;
}

export interface ReplayDiffItem {
  kind: string;
  memory_id?: string | null;
  field?: string | null;
  original?: unknown;
  replayed?: unknown;
  severity: string;
  [key: string]: unknown;
}

export interface ReplayRetrievalResult {
  access_id: string;
  run_id?: string | null;
  step_id?: string | null;
  workspace_id: string;
  query?: string | null;
  strategy: RetrievalStrategy;
  token_budget: number;
  top_k: number;
  original_candidates: unknown[];
  original_gate_decisions: unknown[];
  original_context_blocks_reconstructed: ContextBlock[];
  replayed_candidates: unknown[];
  replayed_gate_decisions: unknown[];
  replayed_context_blocks: ContextBlock[];
  compaction_logs: unknown[];
  diffs: ReplayDiffItem[];
  metrics: JsonObject;
  warnings: string[];
  [key: string]: unknown;
}

export interface RunReplayResult {
  run_id: string;
  access_count: number;
  replayed: ReplayRetrievalResult[];
  summary: JsonObject;
  [key: string]: unknown;
}

export interface ObservabilitySummary {
  workspace_id?: string | null;
  run_id?: string | null;
  access_count: number;
  candidate_count: number;
  accepted_count: number;
  rejected_count: number;
  failed_branch_rejected: number;
  failed_branch_injected: number;
  degraded_negative_evidence_count: number;
  sanitized_failure_notice_count: number;
  negative_evidence_block_count: number;
  retained_negative_evidence_count: number;
  sanitized_retained_negative_evidence_count: number;
  stale_rejected: number;
  stale_injected: number;
  tool_sensitive_blocked: number;
  destructive_command_blocked: number;
  risk_blocked: number;
  workspace_mismatch_rejected: number;
  workspace_leakage: number;
  superseded_injected: number;
  avg_latency_ms: number;
  avg_actual_tokens: number;
  compaction_trigger_rate: number;
  avg_compression_ratio: number;
  total_dropped_blocks: number;
  history_summary_count: number;
  by_strategy: Record<string, Record<string, number>>;
  [key: string]: unknown;
}

export interface ObservabilityReportRequest {
  workspace_id?: string | null;
  run_id?: string | null;
  output_dir?: string;
  include_replay?: boolean;
}

export interface ObservabilityReportResult {
  json_path: string;
  markdown_path: string;
  html_path: string;
  summary: ObservabilitySummary;
  [key: string]: unknown;
}

export interface DashboardTables {
  runs: AgentRun[];
  accesses: MemoryAccessLog[];
  profile_events: ProfileEvent[];
  benchmark_cases: unknown[];
  benchmark_results: unknown[];
  eval_cases: unknown[];
  eval_runs: unknown[];
  eval_results: unknown[];
  memory_versions: MemoryVersionRecord[];
  memory_conflicts: MemoryConflictRecord[];
  maintenance_runs: MaintenanceRunRecord[];
  maintenance_task_attempts: MaintenanceTaskAttemptRecord[];
  admin_action_audits: AdminActionAuditRecord[];
  quota_limits: QuotaLimitRecord[];
  observability_summary?: ObservabilitySummary | null;
  benchmark_summary: Record<string, Record<string, number>>;
  [key: string]: unknown;
}

export interface FlushResult {
  session_id: string;
  processed_event_count: number;
  created_memory_ids: string[];
  [key: string]: unknown;
}

export interface ListMemoriesParams {
  runId?: string;
  workspaceId?: string;
}

export interface ListMemoryConflictsParams {
  workspaceId: string;
  memoryId?: string;
  status?: string;
}

export interface ObservabilitySummaryParams {
  workspaceId?: string;
  runId?: string;
}
