import type { DashboardTables } from "@memtrace/sdk";
import type { ShowcaseFixture } from "./types";

const REQUIRED_DASHBOARD_ARRAYS = [
  "runs",
  "accesses",
  "profile_events",
  "benchmark_cases",
  "benchmark_results",
  "eval_cases",
  "eval_runs",
  "eval_results",
  "memory_versions",
  "memory_conflicts",
  "maintenance_runs",
  "maintenance_task_attempts",
  "admin_action_audits",
  "quota_limits",
] as const;

export function validateShowcaseFixture(input: unknown): {
  fixtureSchemaVersion: 1;
  generatedFrom: string;
  generatedAt: string;
  dashboard: DashboardTables;
} {
  if (!isRecord(input)) {
    throw new Error("fixture must be an object");
  }
  if (input.fixture_schema_version !== 1) {
    throw new Error("fixture_schema_version must be 1");
  }
  if (typeof input.generated_from !== "string" || input.generated_from.length === 0) {
    throw new Error("generated_from must be a non-empty string");
  }
  if (typeof input.generated_at !== "string" || input.generated_at.length === 0) {
    throw new Error("generated_at must be a non-empty string");
  }
  if (!isRecord(input.dashboard)) {
    throw new Error("dashboard fixture payload must be an object");
  }

  for (const field of REQUIRED_DASHBOARD_ARRAYS) {
    if (!Array.isArray(input.dashboard[field])) {
      throw new Error(`dashboard.${field} must be an array`);
    }
  }
  if (!isRecord(input.dashboard.benchmark_summary)) {
    throw new Error("dashboard.benchmark_summary must be an object");
  }
  if (!isRecord(input.routes)) {
    throw new Error("routes fixture payload must be an object");
  }
  if (!isRecord(input.routes.runs)) {
    throw new Error("routes.runs must be an object");
  }
  if (!isRecord(input.routes.accesses)) {
    throw new Error("routes.accesses must be an object");
  }
  if (!Array.isArray(input.routes.memories)) {
    throw new Error("routes.memories must be an array");
  }

  const fixture = input as unknown as ShowcaseFixture;
  return {
    fixtureSchemaVersion: fixture.fixture_schema_version,
    generatedFrom: fixture.generated_from,
    generatedAt: fixture.generated_at,
    dashboard: fixture.dashboard,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
