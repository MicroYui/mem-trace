import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import type { DashboardTables, MemoryItem } from "@memtrace/sdk";
import { App } from "../src/App";
import { normalizeMemoryAtlas, normalizeOpsReadOnly } from "../src/api/normalizers";

describe("WEB-H memory atlas and ops read-only", () => {
  test("redacts secret-like memory display fields and nested version snapshots", () => {
    const view = normalizeMemoryAtlas({
      dashboard: atlasDashboard,
      memories: atlasMemories,
      source: "fixture",
    });
    const serialized = JSON.stringify(view);

    expect(view.summary.totalMemories).toEqual({ kind: "available", label: "Memories", value: 3 });
    expect(view.memories.map((memory) => memory.memoryId)).toEqual([
      "mem_bun",
      "mem_secret",
      "mem_destructive",
    ]);

    const secret = view.memories.find((memory) => memory.memoryId === "mem_secret");
    expect(secret?.displayKey.isMasked).toBe(true);
    expect(secret?.displayValue.state).toBe("secret");
    expect(secret?.displayValue.preview).toBe("Secret value hidden");
    expect(secret?.displayContent.preview).toBe("Secret content hidden");

    const destructive = view.memories.find((memory) => memory.memoryId === "mem_destructive");
    expect(destructive?.displayContent.state).toBe("sanitized");
    expect(destructive?.displayContent.preview).toBe("Risky command hidden");

    expect(view.selectedMemory?.versions[0]?.snapshotPreview).toContain("[redacted]");
    expect(serialized).not.toContain("sk-live-secret");
    expect(serialized).not.toContain("Authorization: Bearer");
    expect(serialized).not.toContain("rm -rf /prod");
    expect(serialized).not.toContain("/srv/prod");
    expect(serialized).not.toContain("raw_payload_ref");
  });

  test("normalizes owner-gated ops tables without inferring ownership from empty arrays", () => {
    const ownerView = normalizeOpsReadOnly(ownerDashboard, "fixture");
    expect(ownerView.capability).toEqual({ kind: "authorized", rowCount: 5 });
    expect(ownerView.maintenanceRuns[0]?.schedulerRunId).toBe("maint_run_1");
    expect(ownerView.taskAttempts[0]?.operation).toBe("conflict_scan");
    expect(ownerView.adminAudits.map((audit) => audit.action)).toContain("maintenance.enqueue");
    expect(ownerView.quotaLimits[0]?.unit).toBe("retrieve_context");

    const emptyUnknown = normalizeOpsReadOnly({
      ...ownerDashboard,
      maintenance_runs: [],
      maintenance_task_attempts: [],
      admin_action_audits: [],
      quota_limits: [],
    }, "live");
    expect(emptyUnknown.capability.kind).toBe("owner_only_unavailable");

    const authorizedEmpty = normalizeOpsReadOnly({
      ...ownerDashboard,
      admin_capability: "authorized_empty",
      maintenance_runs: [],
      maintenance_task_attempts: [],
      admin_action_audits: [],
      quota_limits: [],
    } as DashboardTables, "live");
    expect(authorizedEmpty.capability.kind).toBe("authorized_empty");
  });

  test("renders memory atlas and ops direct routes from fixture data", () => {
    const memoriesHtml = renderToStaticMarkup(<App initialMode="fixture" initialPath="/memories" />);
    expect(memoriesHtml).toContain("Memory Atlas");
    expect(memoriesHtml).toContain("project.package_manager");
    expect(memoriesHtml).toContain("Conflict detail");
    expect(memoriesHtml).toContain("Version timeline");
    expect(memoriesHtml).not.toContain("sk-live-secret");
    expect(memoriesHtml).not.toContain("rm -rf /prod");

    const opsHtml = renderToStaticMarkup(<App initialMode="fixture" initialPath="/ops" />);
    expect(opsHtml).toContain("Ops Read-Only");
    expect(opsHtml).toContain("Maintenance runs");
    expect(opsHtml).toContain("quota_override.upsert");
    expect(opsHtml).not.toContain("admin-secret");
  });
});

describe("WEB-I showcase mode and screenshots", () => {
  test("renders a guided fixture-backed showcase route without live API state", () => {
    const html = renderToStaticMarkup(<App initialMode="fixture" initialPath="/showcase" initialApiKey="secret-token" />);

    expect(html).toContain("Showcase Mode");
    expect(html).toContain("Bun vs npm failure recovery");
    expect(html).toContain("/runs/run_showcase_bun_recovery");
    expect(html).toContain("/access/acc_showcase_gate");
    expect(html).toContain("/benchmark");
    expect(html).toContain("/memories");
    expect(html).not.toContain("secret-token");
  });

  test("documents a repeatable screenshot capture workflow without committing bulky artifacts", () => {
    // Resolve from this test file's location (apps/web/test) so the assertions
    // hold regardless of the cwd the runner is launched from (root `bun test`
    // vs the package-local `bun run web:test`, which first `cd apps/web`).
    const webRoot = join(import.meta.dir, "..");
    const packageJson = JSON.parse(readFileSync(join(webRoot, "package.json"), "utf8")) as {
      scripts?: Record<string, string>;
    };

    expect(packageJson.scripts?.screenshots).toBe("node scripts/capture-showcase-screenshots.mjs");
    expect(existsSync(join(webRoot, "scripts/capture-showcase-screenshots.mjs"))).toBe(true);

    const script = readFileSync(join(webRoot, "scripts/capture-showcase-screenshots.mjs"), "utf8");
    expect(script).toContain("MEMTRACE_WEB_SCREENSHOT_URL");
    expect(script).toContain("/showcase");
    expect(script).toContain("/memories");
    expect(script).toContain("/ops");
    expect(script).toContain("/tmp/memtrace-web-showcase");
  });
});

const atlasMemories: MemoryItem[] = [
  {
    memory_id: "mem_bun",
    workspace_id: "ws_showcase",
    session_id: "session_showcase",
    run_id: "run_showcase_bun_recovery",
    memory_type: "project",
    key: "project.package_manager",
    value: "bun",
    scope: "workspace",
    content: "Project uses Bun for JavaScript commands.",
    summary: "Use Bun for package scripts.",
    branch_status: "completed",
    status: "active",
    sensitivity: "internal",
    embedding_status: "embedded",
    risk_flags: {
      tool_sensitive: false,
      contains_secret: false,
      destructive_command: false,
      production_env: false,
    },
    created_at: "2026-06-20T00:00:00Z",
    updated_at: "2026-06-20T00:01:00Z",
  },
  {
    memory_id: "mem_secret",
    workspace_id: "ws_showcase",
    session_id: "session_showcase",
    run_id: "run_showcase_bun_recovery",
    memory_type: "working_state",
    key: "api_token",
    value: "sk-live-secret",
    scope: "workspace",
    content: "Authorization: Bearer sk-live-secret",
    summary: "Secret-bearing value was redacted.",
    branch_status: "completed",
    status: "quarantined",
    sensitivity: "secret",
    embedding_status: "failed",
    risk_flags: {
      tool_sensitive: false,
      contains_secret: true,
      destructive_command: false,
      production_env: false,
    },
    created_at: "2026-06-20T00:02:00Z",
    updated_at: "2026-06-20T00:02:00Z",
  },
  {
    memory_id: "mem_destructive",
    workspace_id: "ws_showcase",
    session_id: "session_showcase",
    run_id: "run_showcase_bun_recovery",
    memory_type: "tool_evidence",
    key: "tool.failed_command",
    value: "rm -rf /prod",
    scope: "workspace",
    content: "Failed command rm -rf /prod from /srv/prod",
    summary: "Unsafe command was blocked.",
    branch_status: "rolled_back",
    status: "archived",
    sensitivity: "private",
    embedding_status: "stale",
    risk_flags: {
      tool_sensitive: true,
      contains_secret: false,
      destructive_command: true,
      production_env: true,
    },
    created_at: "2026-06-20T00:03:00Z",
    updated_at: "2026-06-20T00:03:00Z",
  },
];

const atlasDashboard: DashboardTables = {
  runs: [],
  accesses: [],
  profile_events: [],
  benchmark_cases: [],
  benchmark_results: [],
  eval_cases: [],
  eval_runs: [],
  eval_results: [],
  memory_versions: [
    {
      version_id: "version_secret_1",
      memory_id: "mem_secret",
      workspace_id: "ws_showcase",
      version_no: 1,
      snapshot: {
        key: "api_token",
        value: "sk-live-secret",
        content: "Authorization: Bearer sk-live-secret",
        lifecycle_metadata: {
          raw_payload_ref: "raw_payload_ref=secret",
          command: "rm -rf /prod",
          cwd: "/srv/prod",
        },
      },
      change_reason: "redaction_state_changed",
      created_at: "2026-06-20T00:04:00Z",
    },
  ],
  memory_conflicts: [
    {
      conflict_id: "conflict_1",
      workspace_id: "ws_showcase",
      subject_key: "project.package_manager",
      memory_ids: ["mem_bun", "mem_secret"],
      status: "open",
      detected_by: "maintenance_conflict_scan_v1",
      explanation: "Conflicting package manager facts were detected without exposing raw secret values.",
      created_at: "2026-06-20T00:05:00Z",
      resolved_at: null,
    },
  ],
  maintenance_runs: [],
  maintenance_task_attempts: [],
  admin_action_audits: [],
  quota_limits: [],
  benchmark_summary: {},
};

const ownerDashboard: DashboardTables = {
  ...atlasDashboard,
  maintenance_runs: [
    {
      scheduler_run_id: "maint_run_1",
      workspace_id: "ws_showcase",
      requested_by: "owner_user",
      reason: "weekly maintenance",
      operations: ["conflict_scan", "summary_refresh"],
      dry_run: false,
      status: "completed",
      summary: { conflicts_opened: 1 },
      warnings: [],
      started_at: "2026-06-20T00:10:00Z",
      finished_at: "2026-06-20T00:11:00Z",
      created_at: "2026-06-20T00:10:00Z",
      updated_at: "2026-06-20T00:11:00Z",
    },
  ],
  maintenance_task_attempts: [
    {
      attempt_id: "attempt_1",
      scheduler_run_id: "maint_run_1",
      workspace_id: "ws_showcase",
      operation: "conflict_scan",
      status: "completed",
      idempotency_key: "safe-idempotency",
      attempt_no: 1,
      result: { conflicts_opened: 1 },
      error_summary: null,
      started_at: "2026-06-20T00:10:00Z",
      finished_at: "2026-06-20T00:10:20Z",
      created_at: "2026-06-20T00:10:00Z",
      updated_at: "2026-06-20T00:10:20Z",
    },
  ],
  admin_action_audits: [
    {
      admin_action_id: "adm_1",
      workspace_id: "ws_showcase",
      principal_id: "owner_user",
      action: "maintenance.enqueue",
      target_type: "maintenance_run",
      target_id: "maint_run_1",
      metadata: { result: "accepted" },
      created_at: "2026-06-20T00:10:00Z",
    },
    {
      admin_action_id: "adm_2",
      workspace_id: "ws_showcase",
      principal_id: "owner_user",
      action: "quota_override.upsert",
      target_type: "quota_limit",
      target_id: "quota_1",
      metadata: { token: "admin-secret" },
      created_at: "2026-06-20T00:12:00Z",
    },
  ],
  quota_limits: [
    {
      quota_limit_id: "quota_1",
      workspace_id: "ws_showcase",
      principal_id: null,
      unit: "retrieve_context",
      limit: 120,
      window_seconds: 60,
      created_by: "owner_user",
      created_at: "2026-06-20T00:12:00Z",
      updated_at: "2026-06-20T00:12:00Z",
    },
  ],
};
