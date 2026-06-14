"""Self-contained static Dashboard UI for MemTrace (Phase 3-B).

This module renders a single, dependency-free HTML page served by the API at
``GET /v1/dashboard/ui``. The page uses only inline CSS and vanilla JavaScript
(no external JS, CDN, fonts, or build step), matching the self-contained style
of ``observability/reports.py``. In the browser it calls the existing read-only
APIs (``/v1/dashboard/tables`` and ``/v1/observability/summary``) via ``fetch``
and renders the runtime/observability/benchmark tables.

All dynamic values are inserted with ``textContent`` / DOM APIs in the client
script, never with ``innerHTML`` of untrusted data, so memory/run content cannot
inject markup. The page is a thin read-only view over existing semantics; it
adds no new runtime, retrieval, gate, or persistence behavior.
"""
from __future__ import annotations

# The page is intentionally a single static string. Auth defaults to off; when
# the API has auth enabled the user supplies a token in the UI which is sent as
# both Authorization: Bearer and X-API-Key (the backend accepts either).
_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MemTrace Dashboard</title>
<style>
  :root { color-scheme: light; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; color: #1f2937; background: #f9fafb;
  }
  header {
    background: #111827; color: #f9fafb; padding: 16px 32px;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }
  header h1 { font-size: 18px; margin: 0; font-weight: 700; }
  header .sub { color: #9ca3af; font-size: 13px; }
  main { padding: 24px 32px 64px; }
  .controls {
    display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap;
    background: white; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 16px; margin-bottom: 20px;
  }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-size: 12px; color: #6b7280; }
  .field input {
    padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px;
    font-size: 14px; min-width: 220px;
  }
  button {
    background: #2563eb; color: white; border: none; border-radius: 8px;
    padding: 9px 18px; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  button:hover { background: #1d4ed8; }
  button:disabled { background: #9ca3af; cursor: not-allowed; }
  .status { font-size: 13px; color: #6b7280; margin-left: auto; }
  .status.error { color: #b91c1c; }
  section { margin-bottom: 28px; }
  section h2 { font-size: 15px; color: #111827; margin: 0 0 12px; }
  .cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
  }
  .card {
    background: white; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px;
  }
  .card .label { font-size: 12px; color: #6b7280; }
  .card .value { font-size: 22px; font-weight: 700; color: #111827; }
  .card.warn .value { color: #b45309; }
  .card.danger .value { color: #b91c1c; }
  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; background: white; font-size: 13px; }
  th, td { border: 1px solid #e5e7eb; padding: 8px; text-align: left; white-space: nowrap; }
  th { background: #f3f4f6; position: sticky; top: 0; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: #6b7280; }
  .empty { color: #6b7280; font-style: italic; padding: 8px 0; }
  code { background: #eef2ff; padding: 2px 4px; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <h1>MemTrace Dashboard</h1>
  <span class="sub">trace-first, state-aware memory runtime &middot; read-only view</span>
</header>
<main>
  <div class="controls">
    <div class="field">
      <label for="ws">Workspace ID (optional)</label>
      <input id="ws" type="text" placeholder="leave blank for all (if permitted)" />
    </div>
    <div class="field">
      <label for="token">API token (optional)</label>
      <input id="token" type="password" placeholder="only if auth enabled" />
    </div>
    <button id="load">Load</button>
    <span id="status" class="status"></span>
  </div>

  <section id="summary-section">
    <h2>Observability Summary</h2>
    <div id="summary-cards" class="cards"></div>
  </section>

  <section>
    <h2>Benchmark Summary (by strategy)</h2>
    <div id="benchmark" class="table-wrap"></div>
  </section>

  <section>
    <h2>Per-strategy Observability</h2>
    <div id="by-strategy" class="table-wrap"></div>
  </section>

  <section>
    <h2>Runs</h2>
    <div id="runs" class="table-wrap"></div>
  </section>

  <section>
    <h2>Access Logs</h2>
    <div id="accesses" class="table-wrap"></div>
  </section>

  <section>
    <h2>Profile Events</h2>
    <div id="profile" class="table-wrap"></div>
  </section>
</main>

<script>
"use strict";

function el(tag, opts) {
  const node = document.createElement(tag);
  if (opts && opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);
  if (opts && opts.cls) node.className = opts.cls;
  return node;
}

function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, "").replace(/\\.$/, "");
  }
  if (typeof v === "object") {
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  }
  return String(v);
}

function isNumericKey(k, v) {
  return typeof v === "number";
}

// Build a table from an array of row objects using the given column keys.
function buildTable(container, rows, columns) {
  container.replaceChildren();
  if (!rows || rows.length === 0) {
    container.appendChild(el("div", { cls: "empty", text: "no rows" }));
    return;
  }
  const table = el("table");
  const thead = el("thead");
  const htr = el("tr");
  for (const col of columns) htr.appendChild(el("th", { text: col.label }));
  thead.appendChild(htr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const col of columns) {
      const raw = col.get ? col.get(row) : row[col.key];
      const td = el("td", { text: fmt(raw) });
      if (isNumericKey(col.key, raw)) td.className = "num";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}

function card(label, value, cls) {
  const c = el("div", { cls: cls ? "card " + cls : "card" });
  c.appendChild(el("div", { cls: "label", text: label }));
  c.appendChild(el("div", { cls: "value", text: fmt(value) }));
  return c;
}

function renderSummary(summary) {
  const cards = document.getElementById("summary-cards");
  cards.replaceChildren();
  if (!summary) {
    cards.appendChild(el("div", { cls: "empty", text: "no summary" }));
    return;
  }
  cards.appendChild(card("Accesses", summary.access_count));
  cards.appendChild(card("Candidates", summary.candidate_count));
  cards.appendChild(card("Accepted", summary.accepted_count));
  cards.appendChild(card("Rejected", summary.rejected_count));
  cards.appendChild(card("Failed-branch rejected", summary.failed_branch_rejected));
  const leak = summary.workspace_leakage || 0;
  cards.appendChild(card("Workspace leakage", leak, leak > 0 ? "danger" : null));
  cards.appendChild(card("Tool-sensitive blocked", summary.tool_sensitive_blocked));
  cards.appendChild(card("Destructive blocked", summary.destructive_command_blocked));
  cards.appendChild(card("Stale rejected", summary.stale_rejected));
  cards.appendChild(card("Negative-evidence blocks", summary.negative_evidence_block_count));
  cards.appendChild(card("Compaction trigger rate", summary.compaction_trigger_rate));
  cards.appendChild(card("Avg latency (ms)", summary.avg_latency_ms));
  cards.appendChild(card("Avg actual tokens", summary.avg_actual_tokens));
}

function renderByStrategy(byStrategy) {
  const container = document.getElementById("by-strategy");
  container.replaceChildren();
  const strategies = byStrategy ? Object.keys(byStrategy) : [];
  if (strategies.length === 0) {
    container.appendChild(el("div", { cls: "empty", text: "no per-strategy data" }));
    return;
  }
  // Union of metric keys across strategies for stable columns.
  const metricKeys = [];
  const seen = {};
  for (const s of strategies) {
    for (const k of Object.keys(byStrategy[s] || {})) {
      if (!seen[k]) { seen[k] = true; metricKeys.push(k); }
    }
  }
  const rows = strategies.map((s) => {
    const row = { strategy: s };
    for (const k of metricKeys) row[k] = (byStrategy[s] || {})[k];
    return row;
  });
  const columns = [{ key: "strategy", label: "strategy" }].concat(
    metricKeys.map((k) => ({ key: k, label: k }))
  );
  buildTable(container, rows, columns);
}

function renderBenchmark(benchmarkSummary) {
  const container = document.getElementById("benchmark");
  // benchmark_summary has the same {strategy: {metric: value}} shape.
  container.replaceChildren();
  const strategies = benchmarkSummary ? Object.keys(benchmarkSummary) : [];
  if (strategies.length === 0) {
    container.appendChild(el("div", { cls: "empty", text: "no benchmark summary" }));
    return;
  }
  const metricKeys = [];
  const seen = {};
  for (const s of strategies) {
    for (const k of Object.keys(benchmarkSummary[s] || {})) {
      if (!seen[k]) { seen[k] = true; metricKeys.push(k); }
    }
  }
  const rows = strategies.map((s) => {
    const row = { strategy: s };
    for (const k of metricKeys) row[k] = (benchmarkSummary[s] || {})[k];
    return row;
  });
  const columns = [{ key: "strategy", label: "strategy" }].concat(
    metricKeys.map((k) => ({ key: k, label: k }))
  );
  buildTable(container, rows, columns);
}

function authHeaders() {
  const token = document.getElementById("token").value.trim();
  if (!token) return {};
  return { "Authorization": "Bearer " + token, "X-API-Key": token };
}

async function fetchJson(path) {
  const resp = await fetch(path, { headers: authHeaders() });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { const j = await resp.json(); if (j && j.detail) detail = JSON.stringify(j.detail); } catch (e) {}
    throw new Error("HTTP " + resp.status + ": " + detail);
  }
  return resp.json();
}

function setStatus(text, isError) {
  const s = document.getElementById("status");
  s.textContent = text;
  s.className = isError ? "status error" : "status";
}

async function load() {
  const btn = document.getElementById("load");
  btn.disabled = true;
  setStatus("loading...", false);
  try {
    const ws = document.getElementById("ws").value.trim();
    const wsQ = ws ? ("?workspace_id=" + encodeURIComponent(ws)) : "";
    const tables = await fetchJson("/v1/dashboard/tables" + wsQ);

    renderSummary(tables.observability_summary);
    renderBenchmark(tables.benchmark_summary);
    renderByStrategy(tables.observability_summary ? tables.observability_summary.by_strategy : null);

    buildTable(document.getElementById("runs"), tables.runs, [
      { key: "run_id", label: "run_id" },
      { key: "workspace_id", label: "workspace" },
      { key: "session_id", label: "session" },
      { key: "status", label: "status" },
      { key: "task", label: "task" },
      { key: "started_at", label: "started_at" },
    ]);

    buildTable(document.getElementById("accesses"), tables.accesses, [
      { key: "access_id", label: "access_id" },
      { key: "retrieval_strategy", label: "strategy" },
      { key: "candidate_count", label: "candidates" },
      { key: "accepted_count", label: "accepted" },
      { key: "rejected_count", label: "rejected" },
      { key: "actual_tokens", label: "tokens" },
      { key: "latency_ms", label: "latency_ms" },
      { key: "created_at", label: "created_at" },
    ]);

    buildTable(document.getElementById("profile"), tables.profile_events, [
      { key: "phase", label: "phase" },
      { key: "operation", label: "operation" },
      { key: "latency_ms", label: "latency_ms" },
      { key: "candidate_count", label: "candidates" },
      { key: "accepted_count", label: "accepted" },
      { key: "rejected_count", label: "rejected" },
      { key: "error_code", label: "error" },
    ]);

    setStatus("loaded " + (tables.runs ? tables.runs.length : 0) + " runs, " +
      (tables.accesses ? tables.accesses.length : 0) + " accesses", false);
  } catch (err) {
    setStatus(String(err && err.message ? err.message : err), true);
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("load").addEventListener("click", load);
document.getElementById("ws").addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
document.getElementById("token").addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });
window.addEventListener("DOMContentLoaded", load);
</script>
</body>
</html>
"""


def render_dashboard_html() -> str:
    """Return the self-contained Dashboard UI HTML page."""
    return _DASHBOARD_HTML


__all__ = ["render_dashboard_html"]
