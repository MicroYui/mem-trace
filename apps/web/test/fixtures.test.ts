import { describe, expect, test } from "bun:test";
import { showcaseFixture } from "../src/fixtures/showcase";
import { validateShowcaseFixture } from "../src/fixtures/validation";

describe("showcase fixtures", () => {
  test("carry schema metadata and validate before normalization", () => {
    const result = validateShowcaseFixture(showcaseFixture);

    expect(result.fixtureSchemaVersion).toBe(1);
    expect(result.generatedFrom).toContain("deterministic");
    expect(result.dashboard.runs.length).toBeGreaterThan(0);
    expect(JSON.stringify(showcaseFixture)).not.toContain("raw_payload_ref");
  });

  test("rejects fixture objects without schema metadata", () => {
    expect(() => validateShowcaseFixture({ dashboard: { runs: [] } })).toThrow("fixture_schema_version");
  });
});
