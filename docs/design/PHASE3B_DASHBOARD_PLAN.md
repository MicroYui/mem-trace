# Phase 3-B Showcase Dashboard Implementation Plan

> **For agentic workers:** implement this plan task-by-task. Keep the dashboard a real product surface over existing MemTrace evidence, not a marketing landing page. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, memorable React + TypeScript dashboard in `apps/web` that makes MemTrace's differentiator obvious in the first 10 seconds: trace-first agent memory, execution-state isolation, gate decisions, context packing, negative evidence, compaction, replay, and benchmark contrast. The UI should be attractive enough for demos, screenshots, and open-source discovery, while staying faithful to backend truth and not adding new runtime semantics.

**Architecture:** `apps/web` is a separate frontend app that consumes existing read-only `/v1` APIs through `@memtrace/sdk` and thin local query adapters. The existing `/v1/dashboard/ui` remains a small built-in static viewer; it must not grow into the full frontend. Any backend work in this slice is limited to bounded, read-only projection endpoints needed by the UI and must preserve existing authz, quota, workspace isolation, redaction, and deterministic benchmark behavior.

**Tech Stack:** Bun workspace, React, TypeScript, Vite, React Router, TanStack Query or equivalent query cache, local CSS/token system, lucide-react icons, Apache ECharts for charts/Sankey-style flows, and React Flow or a similarly focused graph library for the state tree. Avoid a heavy generic admin template unless it demonstrably speeds table/form work without erasing the MemTrace visual identity.

---

## 0. Selection Decision

Select **Phase 3-B Showcase Dashboard** as the next roadmap target.

Reasons:

- The runtime is broad and well verified, but the story is still mostly hidden in JSON, Markdown reports, and a minimal static HTML viewer.
- A high-quality dashboard turns existing correctness work into something users, reviewers, and potential contributors can understand quickly.
- This target has better project-discovery leverage than starting Phase 5 storage or distributed scheduler leasing before their trigger conditions are met.
- The slice is mostly read-only UI over mature APIs, so it can improve perceived quality without destabilizing retrieval, gate, compaction, governance, or benchmark semantics.

Do not interpret this plan as permission to start Elasticsearch/OpenSearch, Neo4j, graph retrieval, query planning, or admin mutation UI. Those remain separate roadmap items with their own triggers.

---

## 1. Product Experience

### 1.1 First Screen

The first screen should be the actual dashboard, not a landing page.

It should show:

- A top-level workspace/run selector with connection status and token entry.
- A "What happened?" overview: recent runs, status, events, accesses, gate outcomes, and safety signals.
- A "Why MemTrace?" visual: a compact strategy comparison showing baseline contamination versus state-aware + gate behavior.
- A "Where to inspect next?" area with direct entry points to run timeline, state tree, memory flow, replay, and benchmark lab.

The first viewport should signal the product identity through real data visualization, not decorative copy. It should be possible to take a screenshot of the first screen and understand that MemTrace is about agent trace, memory, state, gate, and replay.

The workspace selector is initially a manual/current-workspace filter plus workspace ids discovered from returned rows or fixtures. Do not add a workspace listing API in this slice unless an existing read-only route already supports it.

### 1.2 Showcase Promise

The dashboard should be demo-ready for:

- A Bun-vs-npm failed-branch demo run.
- A benchmark run showing all six strategies and the returned benchmark cases; current acceptance fixtures cover 13 known cases.
- A context-compaction case showing retained constraints and compaction notices.
- A failure-aware negative-evidence case showing safe "avoid repeating this" lessons without positive contamination.
- A governance/maintenance overview when owner credentials are provided, while keeping admin data hidden for report-reader and anonymous callers.

### 1.3 Audience

Primary audience:

- Open-source evaluators deciding whether the project is serious.
- Agent developers debugging memory behavior.
- Infra/platform engineers evaluating traceability, safety, and reproducibility.

Design tone:

- Technical, high-signal, and visually distinctive.
- More polished than a utilitarian admin table.
- Still dense enough for real repeated use.

---

## 2. Non-Goals and Guardrails

- No runtime retrieval, gate, context-packing, compaction, benchmark, or governance semantic changes in this UI slice.
- No Phase 5 advanced retrieval/storage work: no ES/OpenSearch, Neo4j, graph retrieval, Query Planner, multi-hop retrieval, or task-intent ranking profiles.
- No admin mutation UI in the first implementation pass. Owner-only admin data may be displayed read-only if existing APIs already expose it safely.
- No dedicated IDE package work.
- No package publication or deploy platform lock-in.
- No storing API keys in URLs, logs, telemetry, screenshots, or committed fixtures.
- No `dangerouslySetInnerHTML` or untrusted HTML rendering.
- No expanding `apps/api/app/api/dashboard_ui.py` beyond minor links/copy to point users at the full web app once it exists.

---

## 3. Visual Direction

### 3.1 Layout

Use an application layout:

- Left rail: product mark, workspace/run navigation, major views.
- Top bar: connection state, workspace filter, run selector, token status, theme toggle.
- Main canvas: data-dense panels and visualizations.
- Right detail drawer: selected run/event/memory/gate/context detail.

Avoid nested cards. Use full-width bands, split panes, graph canvases, tables, drawers, and repeated item cards only where each item is a distinct entity.

### 3.2 Palette

Avoid one-note purple/blue gradients or generic dark dashboards.

Suggested palette:

- Base: near-black graphite / warm white.
- Data accents: cyan for retrieval, green for accepted, amber for warn/degrade, red for reject/risk, violet only as a minor policy/compaction accent.
- Structure accents: slate borders, muted grid lines, high-contrast text.

The UI can use subtle gradients inside charts or heatmaps, but page backgrounds should not depend on decorative gradient blobs.

### 3.3 Typography and Density

- Use compact headings in panels.
- Reserve large display type for the overview title only.
- Use tabular numerals for metrics.
- Keep line lengths short in drawers and log rows.
- All labels must fit at mobile and desktop widths.

### 3.4 Motion

Use restrained motion to explain data flow:

- Animated run timeline cursor on selected access.
- Gate flow highlighting from candidate to decision to context block.
- Smooth pan/zoom in state tree and Sankey canvases.

Motion must be optional/respect reduced-motion settings and must not block data inspection.

---

## 4. Information Architecture

### 4.1 Routes

- `/` - Overview and run gallery.
- `/runs/:runId` - Run timeline, state tree, events, steps, profile phases.
- `/access/:accessId` - Retrieval replay, candidates, gate decisions, context blocks, compaction, negative evidence.
- `/benchmark` - Six-strategy benchmark lab.
- `/memories` - Memory atlas: lifecycle, conflicts, versions, sensitivity, branch status.
- `/ops` - Read-only maintenance/admin observability when owner data is available; otherwise a safe empty/locked state.
- `/showcase` - Fixture-backed demo mode for screenshots and offline exploration, clearly labeled as sample data.

### 4.2 Primary Views

#### Overview

Purpose: quickly answer "what is happening in this workspace?"

Content:

- Summary metric strip: runs, accesses, candidates, accepted, rejected, degraded, compaction events, and explicit safety counters.
- Strategy comparison sparkline/cards from `observability_summary.by_strategy` and `benchmark_summary`.
- Recent runs table with status, task, timestamps, event count, access count, safety status.
- Recent accesses table with strategy, gate ratio, token budget, and context-block/compaction indicators when explicit projections provide them.
- Small state-aware memory explainer using real counts, not marketing text.

#### Run Explorer

Purpose: inspect one run end-to-end.

Content:

- Timeline rail ordered by `sequence_no`.
- Step list grouped by state node and status.
- State tree graph showing active, completed, failed, rolled_back, and recovery nodes.
- Profile phase strip: ingestion, construction, retrieval, rerank, gate, context packing, compaction, generation, maintenance, quality, safety.
- Event detail drawer with redacted content/digests and memory ids.

#### Access Replay

Purpose: show exactly why a retrieval result was injected or blocked.

Content:

- Candidate list with final score and component scores.
- Gate decision matrix by layer: hard policy, risk policy, soft ranking.
- Flow/Sankey view: candidates -> accept/warn/degrade/reject -> context blocks.
- Context pack preview with block type, source, tokens, compaction notice, retained facts, negative evidence.
- Replay drift summary with severity, original vs replayed counts, policy hash/version.

#### Benchmark Lab

Purpose: make the six-strategy story visible.

Content:

- Strategy x case heatmap for pass/fail/task success.
- Contamination chart: baseline versus state-aware + gate.
- Token overhead and context bloat chart for long-context.
- Reflection retention chart for `variant_3`.
- Compaction and negative-evidence retention panels.
- Case drawer showing seeded facts, expected behavior, observed metrics, and relevant access id links.

#### Memory Atlas

Purpose: inspect durable memory health.

Content:

- Filterable memory table: key, type, scope, lifecycle status, branch status, sensitivity, trust/freshness/retention.
- Conflict list and version timeline.
- Memory lineage drawer: source run/step/event, superseded_by, lifecycle audits if exposed through existing read APIs.
- Safe highlighting for secrets/risky entries without showing raw sensitive text.

#### Ops Read-Only

Purpose: show maintenance/admin governance depth without enabling mutation UI.

Content:

- Maintenance run table and attempt details when owner auth is present.
- Admin action audit summary when owner auth is present.
- Quota limit overview when owner auth is present.
- Locked/empty state for report-reader/anonymous callers.

---

## 5. Data Contracts

### 5.1 Existing APIs to Use First

Use existing endpoints before adding backend code:

- `GET /v1/dashboard/tables`
- `GET /v1/observability/summary`
- `GET /v1/runs/{run_id}/timeline`
- `GET /v1/runs/{run_id}/state-tree`
- `GET /v1/runs/{run_id}/steps`
- `GET /v1/runs/{run_id}/profile`
- `GET /v1/access/{access_id}`
- `GET /v1/replay/access/{access_id}`
- `GET /v1/replay/runs/{run_id}`
- `GET /v1/memories`
- `GET /v1/memories/{memory_id}/versions`
- `GET /v1/memory-conflicts`
- `POST /v1/observability/reports` only for explicit export actions, not page load.
- `POST /v1/telemetry/export/runs/{run_id}` only for explicit owner/report-reader export actions, not page load.

`@memtrace/sdk` already wraps the core read/replay/dashboard/memory-conflict APIs. Prefer it for request behavior and error mapping. Add SDK methods only when the dashboard needs an existing public route that is not yet represented.

### 5.2 UI ViewModels and Normalization

Do not let route/page components consume raw backend DTOs directly.

`apps/web` must include a typed normalization layer:

- `api/normalizers.ts` converts API DTOs into UI view models.
- `api/viewModels.ts` defines stable UI-facing shapes.
- Fixture data and live API data must pass through the same normalizers.
- Components may depend on view models, not ad hoc `metrics["some_key"]` or `metadata["some_key"]` lookups scattered through JSX.

Rules:

- Benchmark metrics, profile metadata, compaction metadata, and gate score components must be normalized in one place.
- Missing fields must become explicit `unavailable` / `not_run` / `not_applicable` states, never silent `0`.
- Normalizers must be unit-tested with live-shaped DTO fixtures and showcase fixtures.
- If a backend DTO changes, normalizer tests should fail before visual components drift.

This layer is required before WEB-D/WEB-E/WEB-F feature work grows. It keeps live mode and showcase mode from becoming two separate products.

### 5.3 Capability and Permission Semantics

The dashboard must not infer authorization from empty arrays alone.

For owner-gated data such as maintenance runs, admin action audits, and quota limits, the UI must distinguish:

- **Forbidden/unauthorized:** request failed with `401` / `403`.
- **Owner-only data unavailable:** backend returned no owner-only table data and did not explicitly say the caller can view it.
- **Authorized but empty:** backend or normalized metadata explicitly indicates the caller can view the table and the row count is zero.
- **Unsupported by backend:** the field/capability metadata is absent because the API version predates the table.

Preferred future backend projection, if needed:

```json
{
  "capabilities": {
    "can_view_admin_tables": true
  },
  "hidden_tables": []
}
```

Do not expose sensitive role internals unless there is a clear product need. A boolean capability and hidden-table list is enough for the first pass.

Normalize this into one UI enum instead of per-component row-length checks:

```ts
type CapabilityState =
  | "authorized"
  | "forbidden"
  | "owner_only_unavailable"
  | "authorized_empty"
  | "unsupported"
  | "unknown";
```

Ops, top-bar capability indicators, and admin table empty states should all consume this state.

### 5.4 Deep-Link Bootstrapping

Every detail route must be independently loadable from URL.

- `/runs/:runId` must load its primary content from run-specific timeline/state-tree/steps/profile APIs, not from prior Overview state.
- `/access/:accessId` must load inspect/replay content from access-specific APIs, not from a selected row held in memory.
- `/memories` and conflict/version detail drawers must be able to recover from URL/search params where feasible.
- `dashboard/tables` may populate navigation chrome and recent lists, but it must not be required for route primary content.

If a route lacks enough data for breadcrumb/workspace selector after direct load, show an explicit partial-state skeleton and fetch the smallest read-only supporting data available.

### 5.5 Benchmark Metric Semantics

Benchmark charts must not infer missing or ambiguous metrics.

Rules:

- Strategy/case pass/fail comes from explicit benchmark/eval result fields when present. If no explicit pass flag exists, render the cell as `not_run` or `unavailable`, not failure and not success.
- Missing strategy/case cells render as `not_run`.
- Contamination charts may only use explicit contamination/leakage metrics, such as failed-branch contamination or unsafe leakage fields exposed by benchmark/eval rows. If the metric is unavailable, hide the chart segment or mark it unavailable.
- Token bloat uses explicit token metrics such as `actual_tokens`, `pre_compaction_tokens`, or benchmark summary token-overhead fields only when present. Do not estimate token bloat from context string length in the UI.
- Reflection retention uses `reflection_retention_hit_rate` when present. Do not infer it from generic memory counts.
- Compaction panels use explicit compaction trigger/retention/compression fields when present.
- Negative-evidence retention uses explicit negative-evidence metrics and must distinguish prompt blocks from retained metadata.
- Comparator-dependent claims must require both sides. For example, long-context bloat must require a long-context row and a comparator row; otherwise render `comparator unavailable`.

These rules should live in benchmark normalizers and be covered by tests.

### 5.6 Overview Metric Semantics

Overview cards and recent tables must distinguish explicit fields from derived display metrics.

Rules:

- `access_count` may be derived from `dashboard/tables.accesses` grouped by `run_id`.
- `event_count` is shown only if a read-only projection supplies it. Do not fetch every run timeline from the Overview just to compute event counts.
- `context_block_count` and `compaction_status` are shown only if present in access/profile/compaction projections or a bounded read-only projection. Otherwise render `unavailable`.
- "Unsafe leakage" must not be an undefined aggregate. Prefer explicit safety labels from `ObservabilitySummary`, such as failed-branch injection, workspace leakage, stale injection, risky blocked, sanitized notices, and negative-evidence blocks.
- If a visual uses an umbrella label such as "unsafe leakage", the normalizer must name it as either an explicit field, a documented derived display group, or `unavailable`.
- Overview normalizers own derived display groups; components must not independently recompute safety totals from unrelated fields.

These rules reflect the current DTO shape: `AgentRun` does not carry event/access summary counts, `MemoryAccessLog` does not carry context-block count or compaction status, and `ObservabilitySummary` exposes specific safety counters rather than a generic unsafe-leakage field.

### 5.7 Possible Read-Only Backend Enhancements

Only add these if existing data proves insufficient:

- Bounded pagination/filtering for dashboard tables, preserving workspace authorization and existing hidden-admin-table behavior.
- A run summary row endpoint if `dashboard/tables` becomes too heavy for initial load.
- A read-only access list endpoint if access rows need independent pagination.
- A small graph projection endpoint for state tree layout hints only if frontend layout cannot derive from `state-tree` data.
- Optional dashboard capability metadata, if needed to distinguish authorized-empty owner tables from hidden owner-only tables.

Every backend enhancement must:

- Be read-only.
- Use existing `report_reader` authorization where appropriate.
- Enforce bounded `limit/offset`.
- Preserve owner-only admin table visibility.
- Return redacted data only.
- Avoid new migrations unless there is a clear projection storage need, which is not expected for this slice.

### 5.8 Fixture Mode

The app may include a fixture-backed `/showcase` mode for screenshots and offline exploration.

Rules:

- Fixtures must be synthetic or generated from existing deterministic demo/benchmark outputs after redaction.
- Fixture files must include `fixture_schema_version` and `generated_from` metadata.
- Fixture validation must run through the same view-model normalizers used by live API data.
- The UI must visibly label fixture mode as sample data.
- Fixture mode must not become the source of truth for product behavior.
- Fixture files must be small enough for repository hygiene and must not include API keys, raw secrets, raw destructive production commands, or generated report directories.

### 5.9 Access Replay Decision Semantics

The UI must preserve MemTrace's three-way gate semantics:

- `accept` and `warn` may appear as positive injected context.
- `degrade` may contribute to warning-only negative evidence / `avoided_attempts`.
- `degrade` must never be displayed, counted, colored, or summarized as accepted positive memory.
- `reject` remains rejected context and may have a sanitized explanation.

Visualizations should make this distinction obvious. A degraded failed lesson is useful because it can warn the model away from a failed path without reintroducing that path as positive context.

---

## 6. App Structure

Proposed files:

```text
apps/web/
  package.json
  index.html
  tsconfig.json
  vite.config.ts
  src/
    main.tsx
    app/App.tsx
    app/routes.tsx
    app/queryClient.ts
    app/env.ts
    api/memtraceClient.ts
    api/queries.ts
    api/normalizers.ts
    api/viewModels.ts
    api/capabilities.ts
    api/fixtures.ts
    components/
      chrome/
      data/
      forms/
      graph/
      layout/
      navigation/
      status/
    features/
      overview/
      runs/
      access/
      benchmark/
      memories/
      ops/
      showcase/
    styles/
      tokens.css
      base.css
      layout.css
    test/
      *.test.tsx
      fixtures/
```

Root changes:

- Add `apps/web` to `package.json` workspaces.
- Include `apps/web/src/**/*.ts(x)` in root `tsconfig.json`.
- Add root scripts such as `web:dev`, `web:build`, and `web:test` if they fit the existing Bun workflow.
- Keep `bun.lock`; do not add npm/pnpm/yarn lockfiles.

---

### 6.1 Runtime Config, CORS, and Deployment Origin

The web app needs an explicit API origin model.

Runtime config:

- `VITE_MEMTRACE_API_BASE_URL` defaults to same-origin.
- API keys are sent only in the `Authorization` header by the SDK/client layer, never in URLs.
- The UI must show which API origin it is connected to without exposing token values.

Local development:

- Prefer a Vite dev proxy for `/v1` to the local FastAPI service, defaulting to `http://localhost:8000`.
- If `VITE_MEMTRACE_API_BASE_URL` is set, the client may call that origin directly.
- Connection errors should clearly explain whether the API service is unreachable, unauthorized, forbidden, or quota-limited.

Static/production deployment:

- Recommended deployment is same-origin reverse proxy: serve the web assets and proxy `/v1` to the API from the same host.
- Cross-origin deployment is allowed only when the API is explicitly configured for CORS by the operator. Do not assume cross-origin credentials work by default.
- Deployment docs must explain same-origin reverse proxy versus explicit CORS tradeoffs.

### 6.2 Legacy Static Dashboard Link Strategy

`GET /v1/dashboard/ui` remains the minimal built-in viewer.

After `apps/web` exists:

- The static viewer may include a small "Open full dashboard" link only if a configured public dashboard URL is available.
- If no full dashboard URL is configured, the static viewer should stay self-contained and avoid a broken link.
- README/docs must distinguish "built-in static viewer" from "full React dashboard".
- Do not duplicate full dashboard routes, charts, or graph logic inside `apps/api/app/api/dashboard_ui.py`.

The exact setting name for the full dashboard URL should be chosen during implementation if the link is added.

---

## 7. Implementation Streams

### WEB-A: Scaffold and Build Boundary

**Files:**

- Create: `apps/web/*`
- Modify: `package.json`
- Modify: `tsconfig.json`
- Modify: `tsconfig.base.json` only if path aliases are needed

- [x] Add `apps/web` as a Bun workspace package.
- [x] Add Vite + React + TypeScript scaffold.
- [x] Add `@memtrace/sdk` workspace dependency.
- [x] Add selected UI/data-viz dependencies.
- [x] Define `VITE_MEMTRACE_API_BASE_URL` behavior and Vite dev proxy defaults.
- [x] Add development/build/test scripts.
- [x] Verify root typecheck still covers TS packages and the web app.
- [x] Add a simple app shell that can render without a live API by showing a connection form and fixture-mode link.

Acceptance:

- `bun run typecheck` passes.
- `bun test` still covers existing packages, with web tests included or explicitly added to the root test script.
- `bun run web:build` emits a production bundle without requiring a live API.

Status (2026-06-17): complete. Implemented `apps/web` with Vite/React/TypeScript, workspace dependency on `@memtrace/sdk`, root `web:*` scripts, root TS coverage, same-origin API default plus Vite `/v1` dev proxy, and a fixture-first app shell with a live connection form. Verification used temporary Bun via `npm exec --yes --package bun -- ...`: root typecheck passed, root JS tests passed, and `bun run web:build` produced a production bundle without a live API.

### WEB-B: API Client, Query Layer, and Fixtures

**Files:**

- Create: `apps/web/src/api/*`
- Modify: `packages/ts-sdk/src/client.ts` only if dashboard needs an existing public API not yet wrapped
- Modify: `packages/ts-sdk/src/types.ts` only for existing route DTO coverage gaps

- [x] Build `createMemTraceClient({ baseUrl, apiKey })` around `@memtrace/sdk`. Implemented as `createDashboardClient(...)`.
- [x] Add React Query hooks for dashboard tables, observability summary, run timeline, state tree, steps, profile, access inspection, replay, memories, versions, and conflicts.
- [x] Add `api/viewModels.ts` and `api/normalizers.ts`; all feature components consume normalized view models instead of raw DTOs.
- [x] Add `CapabilityState` / hidden-table normalization for owner-gated data.
- [x] Normalize query keys by workspace/run/access id.
- [x] Add request states: loading, stale, unauthorized, forbidden, not found, quota-limited, connection failed.
- [x] Add fixture data for `/showcase` with `fixture_schema_version` and `generated_from` metadata.
- [x] Add tests for auth header behavior, error state mapping, fixture validation, and normalizer missing-field semantics.

Acceptance:

- API key is never placed in URL query params.
- `401`, `403`, `404`, `422`, and `429` map to user-facing states without crashing the app.
- Fixture mode and live mode share the same view components.
- Direct route loads do not require preloaded Overview/dashboard state.

Status (2026-06-17): complete and review-hardened for the shared data boundary. Added SDK-backed client factory, query keys/hooks for all existing read-only surfaces listed above, fixture validation, typed view models, normalizers shared by fixture/live mode, explicit missing-metric states, owner-gated `CapabilityState`, and tests for auth-header handling, fixture schema, query keys, error classification, and missing-field semantics. Review hardening rejects protocol-relative API base URLs before API keys can be sent cross-origin, accepts `/` as same-origin root, rejects embedded credentials, and aligns TS SDK `DashboardTables` with backend maintenance/admin/quota rows. Feature route pages that consume these hooks remain WEB-D through WEB-H.

### WEB-C: Visual System

**Files:**

- Create: `apps/web/src/styles/*`
- Create: `apps/web/src/components/*`

- [x] Define CSS variables for color, spacing, typography, border, shadow, focus, and chart palette.
- [x] Build app chrome: left rail, top bar, command/selector area, content panes.
- [x] Build drawers.
- [x] Build reusable data components: metric tile, status badge, empty state.
- [x] Build reusable data components: score bar, timeline row, error state, token pill, strategy badge.
- [x] Build icon buttons with lucide-react and accessible labels/tooltips.
- [x] Build theme toggle with light/dark support.
- [x] Add responsive rules for laptop, desktop, and mobile inspection.

Acceptance:

- No text overlaps at common widths: 390px, 768px, 1280px, 1440px.
- Buttons and badges have stable dimensions.
- Color alone is not the only indicator for accept/warn/degrade/reject.
- The palette does not read as a generic purple/dark-blue SaaS dashboard.

Status (2026-06-17): complete for the Overview milestone. The app has tokens, chrome, responsive layout, icon buttons, theme toggle, metric/status/empty primitives, `DetailDrawer`, `ScoreBar`, `TimelineRow`, `TokenMeter`, `StrategyToken`, explicit `ErrorState`, and component coverage. After local Playwright browser dependencies were installed, desktop/mobile screenshot smoke passed; review caught and fixed 390px mobile nav crowding. Formal fixture-backed screenshot capture remains WEB-I/WEB-J.

### WEB-D: Overview and Run Gallery

**Files:**

- Create: `apps/web/src/features/overview/*`

- [x] Render workspace/run controls.
- [x] Render observability summary metrics.
- [x] Render recent run and access tables from dashboard rows.
- [x] Render compact strategy comparison from `benchmark_summary`.
- [x] Render top safety signals from explicit observability fields: failed-branch injection/rejection, degraded negative evidence, sanitized notices, compaction, workspace leakage, stale injection, risky blocked, and negative-evidence blocks.
- [x] Apply Overview metric semantics: no per-run timeline fan-out for event counts, no inferred context-block count or compaction status, and no undefined unsafe-leakage aggregate.
- [x] Link table rows into run/access/detail routes.
- [x] Add skeletons and empty state for a fresh workspace.

Acceptance:

- A first-time viewer can see the MemTrace value proposition without reading docs.
- Existing `dashboard/tables` data is enough for the first version.
- The overview does not require admin owner credentials.
- Workspace selection does not require a workspace listing API; it starts from manual/current workspace and discovered workspace ids in rows/fixtures.

Status (2026-06-17): complete. Overview now renders the real dashboard first screen over normalized view models: metric strip, strategy comparison, run gallery, access stream, safety signals, compaction evidence, negative-evidence signals, selected-run drawer, and owner-gated ops state. It uses explicit returned metrics only; event count stays unavailable without a projection, missing benchmark metrics stay unavailable, and no workspace-listing API was added.

### WEB-E: Run Explorer

**Files:**

- Create: `apps/web/src/components/runs/*`
- Modify: `apps/web/src/api/normalizers.ts`
- Modify: `apps/web/src/api/viewModels.ts`
- Modify: `apps/web/src/api/queries.ts`
- Modify: `apps/web/src/fixtures/*`

- [x] Render event timeline ordered by `sequence_no`.
- [x] Render step list with status and recovery relationships.
- [x] Render state tree view with active/completed/failed/rolled_back/recovery states.
- [x] Render profile phase strip with latency and counts.
- [x] Add detail drawer for selected event evidence.
- [x] Highlight failed branch isolation and recovery path.

Acceptance:

- Recovery nodes visually attach to the failed step's parent, matching runtime semantics.
- Failed/rolled_back branches are visible for audit but visually distinct from active context.
- State tree graph remains readable with at least 30 nodes.

Status (2026-06-18): complete for this slice. `/runs/:runId` now deep-links independently from Overview and loads timeline/state-tree/steps/profile through route-specific hooks. Fixture and live data share `normalizeRunExplorer(...)`; the page renders sequence timeline, a responsive state-tree graph, step list, profile phase strip, event detail drawer, and explicit failed-branch/recovery evidence. A full pan/zoom graph canvas remains a future polish option, but the current state-tree view satisfies the run-explorer evidence requirement without backend changes.

### WEB-F: Access Replay and Memory Flow

**Files:**

- Create: `apps/web/src/components/access/*`
- Modify: `apps/web/src/api/normalizers.ts`
- Modify: `apps/web/src/api/viewModels.ts`
- Modify: `apps/web/src/api/queries.ts`
- Modify: `apps/web/src/fixtures/*`

- [x] Render candidate table with component scores.
- [x] Render gate decisions grouped by layer and decision.
- [x] Render candidate -> decision -> context flow.
- [x] Render context block preview with tokens, source, memory id, and negative evidence.
- [x] Render replay drift summary and replay context evidence.
- [x] Add visual warning semantics for degraded negative evidence staying out of positive context.

Acceptance:

- `degrade` is never visually counted as accepted positive context.
- `degrade` may appear as warning-only negative evidence / `avoided_attempts`, not injected positive memory.
- Secret/destructive/production-risk data remains redacted in all panels.
- Replay drift severity is visible without exposing raw unsafe text.

Status (2026-06-20): complete and review-hardened for this slice. `/access/:accessId` now deep-links independently from Overview and loads inspect/replay payloads through route-specific hooks. Fixture and live data share `normalizeAccessReplay(...)`; the page renders a responsive candidate-to-gate-to-context memory-flow graph, candidate/gate decision matrix with final and component score bars, context block preview, replay drift summary, and selected context-block details. `degrade` is labeled as negative evidence rather than accepted positive context.

### WEB-G: Benchmark Lab

**Files:**

- Create: `apps/web/src/features/benchmark/*`

- [x] Render six-strategy case matrix.
- [x] Render contamination comparison.
- [x] Render token overhead / long-context bloat.
- [x] Render reflection retention for `variant_3`.
- [x] Render compaction and negative-evidence retention metrics.
- [x] Implement benchmark metric semantics in normalizers: missing rows as `not_run`, missing comparator as unavailable, and no inferred contamination/token/reflection metrics.
- [x] Add case detail drawer with source metrics and links to related accesses when available.
- [x] Add screenshot-friendly summary mode for README/social images.

Acceptance:

- The benchmark view makes `baseline_1` vs `variant_2` contrast obvious.
- The UI represents all benchmark cases returned by current benchmark/eval data; fixture/live acceptance covers the current 13 known cases without hardcoding `13` into UI logic.
- Missing comparator rows do not silently show misleading zeroes.

Status (2026-06-20): complete for this slice. `/benchmark` now deep-links independently from Overview and loads fixture/live dashboard tables through `useBenchmarkLab(...)`. Fixture and live rows share `normalizeBenchmarkLab(...)`, which defensively parses `benchmark_*` and `eval_*` rows, renders all returned cases across the six strategies, marks missing cells as `not_run`, marks result rows without explicit pass flags as unavailable, and requires both returned result rows plus explicit summary metrics before displaying comparator-dependent token-bloat claims. The page renders contamination, long-context token bloat, reflection retention, compaction retention, negative-evidence retention, a six-strategy case matrix, and a case-detail panel with source metrics plus run/access links when returned. The fixture now carries the current 13 benchmark cases and synthetic redacted 13 x 6 eval/benchmark rows.

### WEB-H: Memory Atlas and Ops Read-Only

**Files:**

- Create: `apps/web/src/features/memories/*`
- Create: `apps/web/src/features/ops/*`

- [x] Render memory table with filtering by key/type/status/sensitivity/branch.
- [x] Render memory version timeline.
- [x] Render conflict list and conflict detail.
- [x] Render owner-only maintenance/admin/quota tables when returned by `dashboard/tables`.
- [x] Render locked empty states for admin tables when the caller lacks owner access.
- [x] Apply Memory Atlas content-display grading rules for keys, values, versions, conflicts, and risk flags.

Acceptance:

- Report-reader and anonymous users never see owner-only admin data.
- The UI does not offer admin mutations in this slice.
- Secret-like memory keys/values are not echoed unsafely.

Memory Atlas display rules:

- `key` is normally visible, but secret-like keys are partially masked and badged.
- `value` / `content` is collapsed by default.
- `sensitivity=secret` values never expand.
- `risk_flags.destructive_command=true` shows only sanitized summary, not the raw command.
- Version timelines must not bypass current redaction rules just because content is historical.
- Memory Atlas normalizers must recursively redact nested `MemoryVersionRecord.snapshot` fields before display; historical `content`, `value`, secret-like keys, destructive commands, raw payload refs, and production markers must not leak from nested JSON.
- Conflict detail compares safe summaries; it must not reveal raw secret/destructive content to explain a conflict.

Status (2026-06-20): complete for this slice. `/memories` now loads fixture/live current memories through `GET /v1/memories` plus dashboard-table versions/conflicts and normalizes everything through `normalizeMemoryAtlas(...)`; the page renders filterable memory rows, lifecycle/branch/sensitivity/risk badges, conflict detail, and a version timeline. Recursive snapshot redaction masks historical `content`/`value`, secret-like keys, raw-payload refs, destructive commands, and production markers before components receive data. `/ops` loads owner-gated maintenance/admin/quota dashboard rows through `normalizeOpsReadOnly(...)`, distinguishes authorized, authorized-empty, owner-only-unavailable, forbidden, unsupported, and unknown capability states, and remains read-only with no admin mutation UI.

### WEB-I: Showcase Mode, Screenshots, and Public Demo Polish

**Files:**

- Create: `apps/web/src/features/showcase/*`
- Optional create: `apps/web/scripts/*`
- Modify: `README.md` after implementation, not during planning

- [x] Add fixture-backed showcase route with a clearly visible sample-data label.
- [x] Add "Bun vs npm failure recovery" guided walkthrough.
- [x] Add screenshot capture script or documented Playwright screenshot command.
- [x] Add README-ready screenshot assets only if they are generated, small, and accepted by release hygiene.
- [x] Ensure fixture mode works without a running API.
- [x] Validate fixture schema/version and pass fixture payloads through the same normalizers as live data.

Acceptance:

- The app can be demonstrated from fixture data and from a live API.
- Screenshots do not contain API keys or real user data.
- Generated image artifacts are either ignored or intentionally documented if committed.

Status (2026-06-20): complete. `/showcase` renders a guided fixture-backed walkthrough linking to Run Explorer, Access Replay, Benchmark Lab, Memory Atlas, and Ops. The showcase fixture now includes synthetic redacted memory/ops evidence with updated schema validation and metadata. `apps/web/scripts/capture-showcase-screenshots.mjs` captures desktop/mobile screenshots for `/showcase`, `/`, `/runs/...`, `/access/...`, `/benchmark`, `/memories`, and `/ops` into `/tmp/memtrace-web-showcase-*.png` when run with Playwright; no image artifacts are committed by default.

### WEB-J: Testing, Accessibility, and Closeout

**Files:**

- Create/modify: web tests
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/deployment.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/*`

- [x] Unit-test API/query adapters and data transforms.
- [x] Unit-test view-model normalizers, capability states, benchmark metric semantics, and fixture schema validation.
- [x] Component-test critical table/graph states.
- [x] Run TypeScript typecheck.
- [x] Run production build.
- [x] Add Playwright or equivalent smoke for overview, run explorer, access replay, benchmark lab, and fixture mode.
- [x] Capture desktop and mobile screenshots during implementation review.
- [x] Check keyboard navigation, focus states, reduced motion, and contrast.
- [x] Update README/user docs with the web dashboard path and runtime requirements.
- [x] Update ROADMAP and `.ai` memory after each meaningful completed stream.

Acceptance:

- `bun run typecheck` passes.
- `bun test` passes.
- `bun run web:build` passes.
- UI smoke passes against fixture mode and, when a local API is running, live mode.
- `uv run --extra dev pytest -q` remains unaffected by UI-only changes except where backend read-only endpoints were intentionally added.
- `bash scripts/check-release-hygiene.sh` passes or documents any environment-specific blocker.

Status (2026-06-20): complete. Added `apps/web/test/memory-atlas-ops-showcase.test.tsx` for WEB-H/WEB-I normalizers, direct routes, redaction, capability states, and screenshot workflow. README, getting-started, deployment notes, ROADMAP, and `.ai` project memory were updated. Verification covered web tests, root JS tests, typecheck, production build, screenshot smoke, compileall fallback, release hygiene, and diff checks. Playwright screenshot workflow writes to `/tmp` and is not committed; screenshot command may require the optional Playwright package/browser environment.

---

## 8. Backend Boundary Review

Before implementing new backend routes, check whether the dashboard can derive the view from existing data.

If a new read-only endpoint is necessary, require:

- A focused API test.
- TS SDK DTO/client coverage if the web app uses it.
- Workspace scoping test.
- Authz/quota behavior matching similar observability/report routes.
- Redaction test for any egress fields.
- Bounded pagination if returning lists.

Do not add write endpoints, migrations, or admin mutation semantics for dashboard convenience.

---

## 9. Security and Privacy

- Treat the browser as an egress surface.
- Keep API keys in memory by default. If local persistence is added, it must be opt-in and clearly removable.
- Never include token values in error messages.
- Use React escaping and avoid raw HTML.
- Do not send telemetry from the dashboard by default.
- Do not display raw `raw_payload_ref`, raw secrets, raw failed destructive commands, or production path markers.
- Keep owner-only admin tables dependent on backend authorization; the frontend must not infer ownership from local state.

---

## 10. Performance

Targets for first implementation:

- Initial overview route should be useful with a single `dashboard/tables` request plus optional summary request.
- Heavy run/access details should load on navigation or selection, not on initial page load.
- Graphs should virtualize or cap visible rows/nodes where needed.
- Tables should support client-side sorting/filtering for small current result sets and move to server pagination only when data size requires it.
- Bundle size should be reviewed after dependency selection; avoid importing entire chart libraries into every route if route-level splitting is straightforward.

---

## 11. Documentation Updates After Implementation

When implementation lands, update:

- `README.md` with screenshot, live API path, fixture/showcase path, and local dev command.
- `docs/getting-started.md` with how to run API + web app.
- `docs/deployment.md` with static build/deployment notes and API base URL config.
- `docs/design/ROADMAP.md` with completed WEB streams.
- `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, and `.ai/IMPLEMENTATION_PLAN.md`.
- `.ai/PITFALLS.md` if implementation discovers reusable frontend/data-viz traps.

---

## 12. Verification Commands

Expected commands after implementation:

```bash
npm exec --yes --package bun -- bun install --frozen-lockfile
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test
npm exec --yes --package bun -- bun run web:build
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
uv run --extra dev pytest -q
bash scripts/check-release-hygiene.sh
git diff --check
```

If Playwright is added:

```bash
npm exec --yes --package bun -- bun run web:test:e2e
```

Run live-mode smoke only when a local API is running. Fixture-mode smoke must not require PostgreSQL, Redis, Celery, external providers, or network telemetry.

---

## 13. Slice Order Recommendation

Implement in this order:

1. WEB-A scaffold and build boundary.
2. WEB-B query layer, view-model normalizers, and fixture mode.
3. WEB-C visual system.
4. WEB-D overview.
5. WEB-E run explorer.
6. WEB-F access replay and memory flow.
7. WEB-G benchmark lab.
8. WEB-H memory atlas and ops read-only.
9. WEB-I showcase screenshots.
10. WEB-J closeout.

The first shippable milestone is WEB-A through WEB-D: a beautiful overview that builds, loads fixture/live data, and makes the project visually credible. **Status (2026-06-17): achieved.** WEB-E/WEB-F are complete and review-hardened as of 2026-06-20. The full Phase 3-B dashboard slice WEB-A through WEB-J is complete as of 2026-06-20: overview, run explorer, access replay, benchmark lab, memory atlas, ops read-only, showcase route, screenshot workflow, docs, and closeout verification.
