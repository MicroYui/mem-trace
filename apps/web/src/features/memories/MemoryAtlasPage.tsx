import { Database, Filter, GitCompareArrows, History } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactElement } from "react";
import type { MemoryAtlasItemView, MemoryAtlasResult, MemoryAtlasView, MemoryConflictView } from "../../api/viewModels";
import { ErrorState } from "../../components/ui/ErrorState";
import { MetricCard } from "../../components/ui/MetricCard";
import { StatusPill } from "../../components/ui/StatusPill";

export interface MemoryAtlasPageProps {
  atlas: MemoryAtlasResult;
}

export function MemoryAtlasPage({ atlas }: MemoryAtlasPageProps): ReactElement {
  if (atlas.data === undefined) {
    return <ErrorState state={atlas.requestState} />;
  }
  return <MemoryAtlasPageContent view={atlas.data} />;
}

export interface MemoryAtlasPageContentProps {
  view: MemoryAtlasView;
}

export function MemoryAtlasPageContent({ view }: MemoryAtlasPageContentProps): ReactElement {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const [sensitivity, setSensitivity] = useState("all");
  const [branchStatus, setBranchStatus] = useState("all");

  const filteredMemories = useMemo(() => (
    view.memories.filter((memory) => (
      matchesQuery(memory, query)
      && (type === "all" || memory.type === type)
      && (status === "all" || memory.lifecycleStatus === status)
      && (sensitivity === "all" || memory.sensitivity === sensitivity)
      && (branchStatus === "all" || memory.branchStatus === branchStatus)
    ))
  ), [branchStatus, query, sensitivity, status, type, view.memories]);

  return (
    <div className="memory-layout">
      <section className="hero-band route-hero">
        <div>
          <StatusPill label={view.source === "fixture" ? "Fixture mode" : "Live mode"} tone="info" />
          <h1>Memory Atlas</h1>
          <div className="summary-meta" aria-label="Memory atlas totals">
            <span>{view.workspaceIds[0] ?? "No workspace"}</span>
            <span>{view.memories.length} memory rows</span>
            <span>{view.conflicts.length} conflicts</span>
          </div>
        </div>
        <div className="benchmark-hero-icon" aria-hidden="true">
          <Database size={34} />
        </div>
      </section>

      <section className="metric-strip route-metric-strip" aria-label="Memory atlas metrics">
        <MetricCard metric={view.summary.totalMemories} />
        <MetricCard metric={view.summary.activeMemories} />
        <MetricCard metric={view.summary.conflictCount} />
        <MetricCard metric={view.summary.secretOrRisky} />
      </section>

      <section className="panel memory-filter-panel" aria-label="Memory filters">
        <div className="panel-header">
          <div>
            <h2>Filters</h2>
          </div>
          <Filter aria-hidden="true" size={20} />
        </div>
        <div className="filter-grid">
          <input
            aria-label="Filter memories by key or summary"
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="key, summary, memory id"
            value={query}
          />
          <FilterSelect label="Type" onChange={setType} options={view.filters.types} value={type} />
          <FilterSelect label="Lifecycle" onChange={setStatus} options={view.filters.lifecycleStatuses} value={status} />
          <FilterSelect label="Sensitivity" onChange={setSensitivity} options={view.filters.sensitivities} value={sensitivity} />
          <FilterSelect label="Branch" onChange={setBranchStatus} options={view.filters.branchStatuses} value={branchStatus} />
        </div>
      </section>

      <div className="route-grid memory-grid">
        <section className="panel route-panel">
          <div className="panel-header">
            <div>
              <h2>Memory table</h2>
            </div>
            <StatusPill label={`${filteredMemories.length} visible`} tone="info" />
          </div>
          <div className="memory-table" role="table" aria-label="Memory rows">
            <div className="memory-table-row memory-table-head" role="row">
              <span role="columnheader">Key</span>
              <span role="columnheader">Type</span>
              <span role="columnheader">Lifecycle</span>
              <span role="columnheader">Branch</span>
              <span role="columnheader">Sensitivity</span>
            </div>
            {filteredMemories.map((memory) => (
              <MemoryTableRow key={memory.memoryId} memory={memory} />
            ))}
          </div>
        </section>

        <aside className="overview-side-column">
          {view.selectedMemory === null ? null : (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2>Version timeline</h2>
                </div>
                <History aria-hidden="true" size={20} />
              </div>
              <div className="compact-list">
                {view.selectedMemory.versions.length === 0 ? (
                  <p className="muted-inline">No versions returned for the selected memory.</p>
                ) : view.selectedMemory.versions.map((version) => (
                  <div className="compact-row" key={version.versionId}>
                    <div>
                      <span className="timeline-eyebrow">Version {version.versionNo}</span>
                      <h3>{version.changeReason}</h3>
                      <p>{version.snapshotPreview}</p>
                    </div>
                    <StatusPill label={version.createdAt} tone="neutral" />
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Conflict detail</h2>
              </div>
              <GitCompareArrows aria-hidden="true" size={20} />
            </div>
            <div className="compact-list">
              {view.conflicts.length === 0 ? (
                <p className="muted-inline">No memory conflicts returned.</p>
              ) : view.conflicts.map((conflict) => (
                <ConflictRow conflict={conflict} key={conflict.conflictId} />
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

interface FilterSelectProps {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}

function FilterSelect({ label, onChange, options, value }: FilterSelectProps): ReactElement {
  return (
    <label>
      <span>{label}</span>
      <select onChange={(event) => onChange(event.currentTarget.value)} value={value}>
        <option value="all">All</option>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function MemoryTableRow({ memory }: { memory: MemoryAtlasItemView }): ReactElement {
  return (
    <div className="memory-table-row" role="row">
      <div role="cell">
        <strong>{memory.displayKey.label}</strong>
        <small>{memory.memoryId}</small>
        <p>{memory.summary}</p>
        <p>Value: {memory.displayValue.preview}</p>
        <p>{memory.displayContent.preview}</p>
      </div>
      <span role="cell">{memory.type}</span>
      <span role="cell"><StatusPill label={memory.lifecycleStatus} tone={memory.statusTone} /></span>
      <span role="cell">{memory.branchStatus}</span>
      <span role="cell">
        <StatusPill label={memory.sensitivity} tone={memory.sensitivityTone} />
        <span className="risk-badge-list">
          {memory.riskBadges.map((badge) => <StatusPill key={badge.id} label={badge.label} tone={badge.tone} />)}
        </span>
      </span>
    </div>
  );
}

function ConflictRow({ conflict }: { conflict: MemoryConflictView }): ReactElement {
  return (
    <div className="compact-row">
      <div>
        <span className="timeline-eyebrow">{conflict.detectedBy}</span>
        <h3>{conflict.subjectKey.label}</h3>
        <p>{conflict.explanationPreview}</p>
        <div className="timeline-meta">
          {conflict.memoryIds.map((memoryId) => <span key={memoryId}>{memoryId}</span>)}
        </div>
      </div>
      <StatusPill label={conflict.status} tone={conflict.status === "open" ? "warning" : "good"} />
    </div>
  );
}

function matchesQuery(memory: MemoryAtlasItemView, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (normalized.length === 0) return true;
  return [
    memory.memoryId,
    memory.displayKey.label,
    memory.summary,
    memory.displayContent.preview,
    memory.type,
    memory.lifecycleStatus,
  ].some((value) => value.toLowerCase().includes(normalized));
}
