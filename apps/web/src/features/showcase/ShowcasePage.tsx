import { ArrowRight, BarChart3, Database, GitBranch, Network, Presentation } from "lucide-react";
import type { ReactElement } from "react";
import { showcaseFixture } from "../../fixtures/showcase";
import { StatusPill } from "../../components/ui/StatusPill";

export function ShowcasePage(): ReactElement {
  const runId = showcaseFixture.dashboard.runs[0]?.run_id ?? "run_showcase_bun_recovery";
  const accessId = showcaseFixture.dashboard.accesses[0]?.access_id ?? "acc_showcase_gate";

  return (
    <div className="showcase-layout">
      <section className="hero-band showcase-hero">
        <div>
          <StatusPill label="Fixture mode" tone="info" />
          <h1>Showcase Mode</h1>
          <div className="summary-meta" aria-label="Showcase fixture metadata">
            <span>{showcaseFixture.generated_from}</span>
            <span>{showcaseFixture.dashboard.runs.length} demo runs</span>
            <span>{showcaseFixture.dashboard.eval_cases.length} benchmark cases</span>
          </div>
        </div>
        <div className="benchmark-hero-icon" aria-hidden="true">
          <Presentation size={34} />
        </div>
      </section>

      <section className="showcase-flow" aria-label="Guided showcase walkthrough">
        <ShowcaseStep
          href={`/runs/${encodeURIComponent(runId)}`}
          icon={<GitBranch aria-hidden="true" size={22} />}
          title="Bun vs npm failure recovery"
          meta="Run Explorer"
          points={[
            "Timeline shows the project Bun constraint before the failed branch.",
            "State tree keeps failed and recovery branches visually separate.",
            "Profiler phases stay visible without changing runtime semantics.",
          ]}
        />
        <ShowcaseStep
          href={`/access/${encodeURIComponent(accessId)}`}
          icon={<Network aria-hidden="true" size={22} />}
          title="Gate replay and memory flow"
          meta="Access Replay"
          points={[
            "Accepted context is separated from rejected memories.",
            "Degraded memories are warning-only negative evidence.",
            "Replay drift and component scores are inspectable from one page.",
          ]}
        />
        <ShowcaseStep
          href="/benchmark"
          icon={<BarChart3 aria-hidden="true" size={22} />}
          title="Six-strategy benchmark lab"
          meta="Benchmark Lab"
          points={[
            "All returned cases render across the strategy matrix.",
            "Comparator-dependent token-bloat claims stay unavailable when inputs are missing.",
            "Compaction and retained negative lessons are shown separately.",
          ]}
        />
        <ShowcaseStep
          href="/memories"
          icon={<Database aria-hidden="true" size={22} />}
          title="Memory atlas and ops evidence"
          meta="Memory Atlas"
          points={[
            "Lifecycle, branch status, sensitivity, conflicts, and versions are visible.",
            "Version snapshots are recursively redacted before display.",
            "Owner-only ops rows render read-only when returned by the fixture.",
          ]}
        />
      </section>

      <section className="panel screenshot-panel">
        <div className="panel-header">
          <div>
            <h2>Screenshot workflow</h2>
          </div>
          <StatusPill label="No secrets in fixture" tone="good" />
        </div>
        <div className="showcase-command-grid">
          <code>npm exec --yes --package bun -- bun run web:dev</code>
          <code>MEMTRACE_WEB_SCREENSHOT_URL=http://127.0.0.1:5173 npm exec --yes --package playwright -- node apps/web/scripts/capture-showcase-screenshots.mjs</code>
        </div>
      </section>
    </div>
  );
}

interface ShowcaseStepProps {
  href: string;
  icon: ReactElement;
  meta: string;
  points: string[];
  title: string;
}

function ShowcaseStep({ href, icon, meta, points, title }: ShowcaseStepProps): ReactElement {
  return (
    <article className="showcase-step">
      <div className="showcase-step-icon">{icon}</div>
      <div>
        <span className="timeline-eyebrow">{meta}</span>
        <h2>{title}</h2>
        <ul>
          {points.map((point) => <li key={point}>{point}</li>)}
        </ul>
        <a className="command-button primary compact" href={href}>
          Open
          <ArrowRight aria-hidden="true" size={16} />
        </a>
      </div>
    </article>
  );
}
