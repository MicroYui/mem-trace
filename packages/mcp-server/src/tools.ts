import type {
  AccessInspection,
  FinishStepRequest,
  FinishStepResult,
  JsonObject,
  MemoryContext,
  ObservabilityReportRequest,
  ObservabilityReportResult,
  RetrievalRequest,
  ReplayRetrievalResult,
  StartRunRequest,
  StartStepRequest,
  WriteEventRequest,
  WriteEventResult,
  AgentRun,
  AgentStep,
} from "@memtrace/sdk";

export const MAX_TOOL_TEXT_CHARS = 8000;

export interface McpTextContent {
  type: "text";
  text: string;
}

export interface McpToolResult {
  content: McpTextContent[];
  isError?: boolean;
}

export interface McpInputSchema {
  type: "object";
  properties: Record<string, unknown>;
  required?: string[];
  additionalProperties?: boolean;
}

export interface MemTraceMcpTool {
  name: string;
  description: string;
  inputSchema: McpInputSchema;
  handler: (input: Record<string, unknown>) => Promise<McpToolResult>;
}

export interface MemTraceToolClient {
  startRun(req: StartRunRequest): Promise<AgentRun>;
  startStep(req: StartStepRequest): Promise<AgentStep>;
  writeEvent(req: WriteEventRequest): Promise<WriteEventResult>;
  retrieveContext(req: RetrievalRequest): Promise<MemoryContext>;
  inspectAccess(accessId: string): Promise<AccessInspection>;
  finishStep(req: FinishStepRequest): Promise<FinishStepResult>;
  replayAccess(accessId: string): Promise<ReplayRetrievalResult>;
  writeObservabilityReport(req: ObservabilityReportRequest): Promise<ObservabilityReportResult>;
}

function stringProperty(description: string): Record<string, string> {
  return { type: "string", description };
}

function booleanProperty(description: string): Record<string, string> {
  return { type: "boolean", description };
}

function numberProperty(description: string): Record<string, string> {
  return { type: "number", description };
}

function objectSchema(properties: Record<string, unknown>, required: string[] = []): McpInputSchema {
  return { type: "object", properties, required, additionalProperties: true };
}

export function toolTextResult(text: string, isError = false): McpToolResult {
  const contentText = limitToolText(redactToolText(text));
  return { content: [{ type: "text", text: contentText }], ...(isError ? { isError: true } : {}) };
}

function secretKeyName(key: string): boolean {
  const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return (
    normalized === "password" ||
    normalized === "passwd" ||
    normalized === "token" ||
    normalized === "authorization" ||
    normalized === "auth_header" ||
    normalized === "api_key" ||
    normalized === "access_token" ||
    normalized === "refresh_token" ||
    normalized === "id_token" ||
    normalized === "secret" ||
    normalized === "secret_key" ||
    normalized === "client_secret" ||
    normalized === "credential" ||
    normalized === "private_key" ||
    normalized.endsWith("_secret") ||
    normalized.endsWith("_token") ||
    normalized.endsWith("_credential")
  );
}

function redactJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactJsonValue(item));
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        secretKeyName(key) ? "[REDACTED]" : redactJsonValue(item),
      ]),
    );
  }
  return value;
}

function redactWholeJson(input: string): string {
  const trimmed = input.trim();
  if (trimmed.length === 0 || (trimmed[0] !== "{" && trimmed[0] !== "[")) {
    return input;
  }
  try {
    return JSON.stringify(redactJsonValue(JSON.parse(input) as unknown));
  } catch {
    return input;
  }
}

export function redactToolText(input: string): string {
  return redactWholeJson(input)
    .replace(/Authorization\s*:\s*Bearer\s+[^\s"']+/gi, "[REDACTED_AUTH_HEADER]")
    .replace(/Authorization\s+Bearer\s+[^\s"']+/gi, "[REDACTED_AUTH]")
    .replace(/(["']?(?:password|passwd|token|authorization|auth[_-]?header|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|secret|secret[_-]?key|client[_-]?secret|credential|private[_-]?key|[A-Za-z0-9_-]+[_-](?:secret|token|credential))["']?\s*:\s*)["'][^"']*["']/gi, "$1\"[REDACTED]\"")
    .replace(/(["']?(?:password|passwd|token|authorization|auth[_-]?header|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|secret|secret[_-]?key|client[_-]?secret|credential|private[_-]?key|[A-Za-z0-9_-]+[_-](?:secret|token|credential))["']?\s*=\s*)[^\s"']+/gi, "$1[REDACTED]")
    .replace(/Bearer\s+[^\s"']+/gi, "Bearer [REDACTED]")
    .replace(/MEMTRACE_API_KEY\s*[=:]\s*[^\s"']+/gi, "MEMTRACE_API_KEY=[REDACTED]")
    .replace(/sk-[A-Za-z0-9_-]+/g, "[REDACTED_TOKEN]")
    .replace(/password\s*[=:]\s*[^\s"']+/gi, "secret=[REDACTED]")
    .replace(/password/gi, "secret")
    .replace(/raw_payload_ref/gi, "redacted_payload_ref")
    .replace(/rm\s+-rf/gi, "[REDACTED_DESTRUCTIVE_COMMAND]")
    .replace(/\/prod\b/g, "[REDACTED_PRODUCTION_PATH]")
    .replace(/Authorization/gi, "AuthHeader");
}

function limitToolText(input: string): string {
  if (input.length <= MAX_TOOL_TEXT_CHARS) return input;
  const suffix = "\n...[truncated to keep MCP tool output concise]";
  return `${input.slice(0, MAX_TOOL_TEXT_CHARS - suffix.length)}${suffix}`;
}

function compactJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function errorText(error: unknown): string {
  if (error instanceof Error && "status" in error && "code" in error) {
    const status = String((error as { status: unknown }).status);
    const code = String((error as { code: unknown }).code);
    return `MemTrace tool error: ${error.name} status=${status} code=${code} message=${error.message}`;
  }
  if (error instanceof Error) {
    return `MemTrace tool error: ${error.name}: ${error.message}`;
  }
  return `MemTrace tool error: ${String(error)}`;
}

async function safeHandler(fn: () => Promise<string>): Promise<McpToolResult> {
  try {
    return toolTextResult(await fn());
  } catch (error) {
    return toolTextResult(errorText(error), true);
  }
}

function asRecord(input: Record<string, unknown>): JsonObject {
  return input as JsonObject;
}

function requireString(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${key} is required`);
  }
  return value;
}

function optionalString(input: Record<string, unknown>, key: string): string | null | undefined {
  const value = input[key];
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== "string") throw new Error(`${key} must be a string`);
  return value;
}

function optionalBoolean(input: Record<string, unknown>, key: string): boolean | undefined {
  const value = input[key];
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") throw new Error(`${key} must be a boolean`);
  return value;
}

function optionalNumber(input: Record<string, unknown>, key: string): number | undefined {
  const value = input[key];
  if (value === undefined) return undefined;
  if (typeof value !== "number") throw new Error(`${key} must be a number`);
  return value;
}

function maybeMetadata(input: Record<string, unknown>): JsonObject | undefined {
  const value = input.metadata;
  if (value === undefined) return undefined;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("metadata must be an object");
  }
  return value as JsonObject;
}

function omitUndefined<T extends Record<string, unknown>>(input: T): T {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined)) as T;
}

function summarizeRun(run: AgentRun): string {
  return `run_id=${run.run_id}\nworkspace_id=${run.workspace_id}\nsession_id=${run.session_id}\nstatus=${run.status}`;
}

function summarizeStep(step: AgentStep): string {
  return `step_id=${step.step_id}\nrun_id=${step.run_id}\nstatus=${step.status}\nstate_node_id=${step.state_node_id ?? ""}`;
}

function summarizeWrite(result: WriteEventResult): string {
  return [
    `event_id=${result.event.event_id}`,
    `sequence_no=${result.event.sequence_no}`,
    `created_memories=${result.created_memory_ids.length}`,
    `buffered=${result.buffered}`,
    `queued=${result.queued}`,
    result.task_id ? `task_id=${result.task_id}` : undefined,
    result.warnings.length > 0 ? `warnings=${result.warnings.join("; ")}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function summarizeContext(context: MemoryContext): string {
  return [
    `access_id=${context.access_id}`,
    `blocks=${context.context_blocks.length}`,
    `warnings=${context.warnings.length}`,
    context.context_blocks.length > 0
      ? `block_types=${context.context_blocks.map((block) => block.type).join(",")}`
      : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function summarizeInspection(inspection: AccessInspection): string {
  return [
    `access_id=${inspection.access_id}`,
    `strategy=${inspection.retrieval_strategy}`,
    `candidates=${inspection.candidates.length}`,
    `gate_decisions=${inspection.gate_decisions.length}`,
    `context_blocks=${inspection.context_blocks.length}`,
    inspection.policy_version ? `policy_version=${inspection.policy_version}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function summarizeFinish(result: FinishStepResult): string {
  return [
    `step_id=${result.step.step_id}`,
    `run_id=${result.step.run_id}`,
    `status=${result.step.status}`,
    `state_node_id=${result.state_node.node_id}`,
    `created_memories=${result.created_memory_ids.length}`,
  ].join("\n");
}

function summarizeReplay(result: ReplayRetrievalResult): string {
  return [
    `access_id=${result.access_id}`,
    `run_id=${result.run_id ?? ""}`,
    `strategy=${result.strategy}`,
    `diffs=${result.diffs.length}`,
    `warnings=${result.warnings.length}`,
    "details=",
    compactJson({ diffs: result.diffs, metrics: result.metrics, warnings: result.warnings }),
  ].join("\n");
}

function summarizeReport(result: ObservabilityReportResult): string {
  return [
    `json_path=${result.json_path}`,
    `markdown_path=${result.markdown_path}`,
    `html_path=${result.html_path}`,
    `access_count=${result.summary.access_count}`,
    `candidate_count=${result.summary.candidate_count}`,
    `accepted_count=${result.summary.accepted_count}`,
    `rejected_count=${result.summary.rejected_count}`,
    "summary=",
    compactJson(result.summary),
  ].join("\n");
}

export function createMemTraceTools(client: MemTraceToolClient): MemTraceMcpTool[] {
  return [
    {
      name: "memtrace_start_run",
      description: "Start a MemTrace run.",
      inputSchema: objectSchema(
        {
          session_id: stringProperty("Session id."),
          task: stringProperty("Optional task description."),
          workspace_id: stringProperty("Optional workspace id."),
          metadata: { type: "object", description: "Optional metadata." },
        },
        ["session_id"],
      ),
      handler: (input) =>
        safeHandler(async () =>
          summarizeRun(
            await client.startRun(omitUndefined({
              session_id: requireString(input, "session_id"),
              task: optionalString(input, "task"),
              workspace_id: optionalString(input, "workspace_id"),
              metadata: maybeMetadata(input),
            }) as StartRunRequest),
          ),
        ),
    },
    {
      name: "memtrace_start_step",
      description: "Start a MemTrace step.",
      inputSchema: objectSchema(
        {
          run_id: stringProperty("Run id."),
          intent: stringProperty("Optional step intent."),
          parent_step_id: stringProperty("Optional parent step id."),
          recovery_from_step_id: stringProperty("Optional recovery source step id."),
          goal: stringProperty("Optional goal."),
          metadata: { type: "object", description: "Optional metadata." },
        },
        ["run_id"],
      ),
      handler: (input) =>
        safeHandler(async () =>
          summarizeStep(
            await client.startStep(omitUndefined({
              run_id: requireString(input, "run_id"),
              intent: optionalString(input, "intent"),
              parent_step_id: optionalString(input, "parent_step_id"),
              recovery_from_step_id: optionalString(input, "recovery_from_step_id"),
              goal: optionalString(input, "goal"),
              metadata: maybeMetadata(input),
            }) as StartStepRequest),
          ),
        ),
    },
    {
      name: "memtrace_write_event",
      description: "Write an event to MemTrace.",
      inputSchema: objectSchema(
        {
          run_id: stringProperty("Run id."),
          step_id: stringProperty("Step id."),
          role: stringProperty("Event role."),
          event_type: stringProperty("Event type."),
          content: stringProperty("Event content."),
          tool_name: stringProperty("Optional tool name."),
          status: stringProperty("Optional status."),
          token_input: numberProperty("Input tokens."),
          token_output: numberProperty("Output tokens."),
          latency_ms: numberProperty("Latency in milliseconds."),
          extraction_mode: stringProperty("Extraction mode."),
          event_source: stringProperty("Optional event source."),
          metadata: { type: "object", description: "Optional metadata." },
        },
        ["run_id", "step_id"],
      ),
      handler: (input) =>
        safeHandler(async () =>
          summarizeWrite(
            await client.writeEvent(omitUndefined({
              run_id: requireString(input, "run_id"),
              step_id: requireString(input, "step_id"),
              role: optionalString(input, "role") as WriteEventRequest["role"],
              event_type: optionalString(input, "event_type") as WriteEventRequest["event_type"],
              content: optionalString(input, "content"),
              tool_name: optionalString(input, "tool_name"),
              status: optionalString(input, "status"),
              token_input: optionalNumber(input, "token_input"),
              token_output: optionalNumber(input, "token_output"),
              latency_ms: optionalNumber(input, "latency_ms"),
              extraction_mode: optionalString(input, "extraction_mode") as WriteEventRequest["extraction_mode"],
              event_source: optionalString(input, "event_source") ?? "mcp",
              metadata: maybeMetadata(input),
            }) as WriteEventRequest),
          ),
        ),
    },
    {
      name: "memtrace_retrieve_context",
      description: "Retrieve a MemTrace context.",
      inputSchema: objectSchema(
        {
          run_id: stringProperty("Run id."),
          step_id: stringProperty("Optional step id."),
          query: stringProperty("Retrieval query."),
          task_intent: stringProperty("Optional task intent."),
          workspace_id: stringProperty("Optional workspace id."),
          strategy: stringProperty("Optional retrieval strategy."),
          token_budget: numberProperty("Optional token budget."),
          top_k: numberProperty("Optional top-k."),
        },
        ["run_id", "query"],
      ),
      handler: (input) =>
        safeHandler(async () =>
          summarizeContext(
            await client.retrieveContext(omitUndefined({
              run_id: requireString(input, "run_id"),
              step_id: optionalString(input, "step_id"),
              query: requireString(input, "query"),
              task_intent: optionalString(input, "task_intent"),
              workspace_id: optionalString(input, "workspace_id"),
              strategy: optionalString(input, "strategy"),
              token_budget: optionalNumber(input, "token_budget"),
              top_k: optionalNumber(input, "top_k"),
            }) as RetrievalRequest),
          ),
        ),
    },
    {
      name: "memtrace_inspect_access",
      description: "Inspect a MemTrace access log.",
      inputSchema: objectSchema({ access_id: stringProperty("Access id.") }, ["access_id"]),
      handler: (input) => safeHandler(async () => summarizeInspection(await client.inspectAccess(requireString(input, "access_id")))),
    },
    {
      name: "memtrace_finish_step",
      description: "Finish a MemTrace step.",
      inputSchema: objectSchema(
        {
          run_id: stringProperty("Run id."),
          step_id: stringProperty("Step id."),
          status: stringProperty("Step status."),
          error_message: stringProperty("Optional error message."),
          summary: stringProperty("Optional summary."),
        },
        ["run_id", "step_id"],
      ),
      handler: (input) =>
        safeHandler(async () =>
          summarizeFinish(
            await client.finishStep(omitUndefined({
              run_id: requireString(input, "run_id"),
              step_id: requireString(input, "step_id"),
              status: optionalString(input, "status") as FinishStepRequest["status"],
              error_message: optionalString(input, "error_message"),
              summary: optionalString(input, "summary"),
            }) as FinishStepRequest),
          ),
        ),
    },
    {
      name: "memtrace_replay_access",
      description: "Replay a MemTrace access decision and summarize drift.",
      inputSchema: objectSchema({ access_id: stringProperty("Access id.") }, ["access_id"]),
      handler: (input) => safeHandler(async () => summarizeReplay(await client.replayAccess(requireString(input, "access_id")))),
    },
    {
      name: "memtrace_report",
      description: "Write a MemTrace observability report.",
      inputSchema: objectSchema({
        workspace_id: stringProperty("Optional workspace id."),
        run_id: stringProperty("Optional run id."),
        output_dir: stringProperty("Optional report output directory."),
        include_replay: booleanProperty("Whether to include replay details."),
      }),
      handler: (input) =>
        safeHandler(async () => {
          const req = omitUndefined({
            workspace_id: optionalString(input, "workspace_id"),
            run_id: optionalString(input, "run_id"),
            output_dir: optionalString(input, "output_dir") ?? undefined,
            include_replay: optionalBoolean(input, "include_replay"),
          }) as ObservabilityReportRequest;
          return summarizeReport(await client.writeObservabilityReport(req));
        }),
    },
  ];
}

export function toolsByName(tools: MemTraceMcpTool[]): Map<string, MemTraceMcpTool> {
  return new Map(tools.map((tool) => [tool.name, tool]));
}
