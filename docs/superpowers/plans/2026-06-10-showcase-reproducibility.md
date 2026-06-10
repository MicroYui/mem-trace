# Showcase Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible showcase package so a new reader can understand MemTrace, run deterministic demos, inspect generated reports, and verify the benchmark baseline locally.

**Architecture:** Keep the deterministic path database-free and reuse existing demo, benchmark, and observability report entrypoints. Add thin shell wrappers, README guidance, and smoke tests without introducing frontend, auth, or heavy infrastructure.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy/Alembic, PostgreSQL + pgvector via Docker Compose, pytest, POSIX shell.

---

## File Map

- Create `README.md`: public-facing architecture, quickstart, report guide, API guide, optional LLM bench instructions.
- Create `scripts/reproduce.sh`: deterministic report generation and benchmark acceptance assertion.
- Create `scripts/smoke.sh`: local smoke bundle that runs tests, reproduction script, and deterministic benchmark.
- Optionally create `docker-compose.api.yml`: API service layer for local HTTP exploration if implementation can keep it simple and correct.
- Create `apps/api/tests/integration/test_reproducibility.py`: regression tests for reproducible report generation and README drift.
- Modify `.gitignore`: add `.superpowers/`.
- Modify `.ai/PROJECT_STATE.md`: record showcase/reproducibility completion and latest verification.
- Modify `ROADMAP.md`: check/annotate showcase and reproducibility-related items.

---

### Task 1: Protect Local Brainstorm State

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add `.superpowers/` to `.gitignore`**

Add this block after the `reports/` ignore entry:

```gitignore
# Local brainstorming / visual companion state
.superpowers/
```

- [ ] **Step 2: Verify ignore behavior**

Run:

```bash
git status --short
```

Expected: `.superpowers/` no longer appears as an untracked path.

---

### Task 2: Add Deterministic Reproduction Script

**Files:**
- Create: `scripts/reproduce.sh`

- [ ] **Step 1: Create script directory if missing**

Run:

```bash
mkdir -p scripts
```

- [ ] **Step 2: Write `scripts/reproduce.sh`**

Create the file with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-reports}"

if [[ "$OUT_DIR" = /* || "$OUT_DIR" == *".."* ]]; then
  echo "error: output directory must be a relative path without '..'" >&2
  exit 2
fi

echo "==> Generating MemTrace demo report"
uv run python -m app.demo.run_demo --out "$OUT_DIR"

echo "==> Running deterministic benchmark"
uv run python -m app.benchmark.runner --output-dir "$OUT_DIR"

echo "==> Generating observability report fixture"
uv run python -m app.observability.reports --output-dir "$OUT_DIR"

echo "==> Checking benchmark acceptance"
uv run python - "$OUT_DIR/benchmark_results.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
passed = payload.get("acceptance", {}).get("passed") is True
if not passed:
    raise SystemExit(f"benchmark acceptance failed in {path}")
checks = payload.get("acceptance", {}).get("checks", {})
print(f"acceptance.passed=true ({sum(1 for ok in checks.values() if ok)}/{len(checks)} checks true)")
PY

cat <<EOF

MemTrace reproducibility baseline generated under: $OUT_DIR

Read these files next:
  - $OUT_DIR/demo_report.md
  - $OUT_DIR/benchmark_report.md
  - $OUT_DIR/benchmark_results.json
  - $OUT_DIR/observability_report.md
  - $OUT_DIR/observability_report.html

EOF
```

- [ ] **Step 3: Make the script executable**

Run:

```bash
chmod +x scripts/reproduce.sh
```

- [ ] **Step 4: Run the script**

Run:

```bash
./scripts/reproduce.sh
```

Expected: command exits 0, prints `acceptance.passed=true`, and lists generated report files.

---

### Task 3: Add Smoke Script

**Files:**
- Create: `scripts/smoke.sh`

- [ ] **Step 1: Write `scripts/smoke.sh`**

Create the file with this content:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Running full pytest suite"
uv run pytest -q

echo "==> Running reproducibility baseline"
./scripts/reproduce.sh reports

echo "==> Re-running deterministic benchmark for explicit acceptance check"
uv run python -m app.benchmark.runner --output-dir reports

echo "smoke passed"
```

- [ ] **Step 2: Make the script executable**

Run:

```bash
chmod +x scripts/smoke.sh
```

Expected: no output if chmod succeeds.

---

### Task 4: Add Reproducibility Tests

**Files:**
- Create: `apps/api/tests/integration/__init__.py`
- Create: `apps/api/tests/integration/test_reproducibility.py`

- [ ] **Step 1: Create integration test package**

Create `apps/api/tests/integration/__init__.py` as an empty file.

- [ ] **Step 2: Write failing tests**

Create `apps/api/tests/integration/test_reproducibility.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.benchmark.runner import run_benchmark
from app.demo.run_demo import run_demo, _render_markdown as render_demo_markdown
from app.observability.reports import main as observability_reports_main


@pytest.mark.asyncio
async def test_demo_and_benchmark_reports_are_reproducible(tmp_path: Path) -> None:
    demo = await run_demo(use_sql=False)
    (tmp_path / "demo_report.json").write_text(
        json.dumps(demo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "demo_report.md").write_text(render_demo_markdown(demo), encoding="utf-8")

    benchmark = await run_benchmark(output_dir=tmp_path)

    assert demo["summary"]["contamination_eliminated"] is True
    assert benchmark["acceptance"]["passed"] is True
    assert (tmp_path / "demo_report.md").exists()
    assert (tmp_path / "demo_report.json").exists()
    assert (tmp_path / "benchmark_report.md").exists()
    assert (tmp_path / "benchmark_results.json").exists()


def test_observability_report_entrypoint_writes_expected_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path.cwd())
    output_dir = tmp_path / "reports"
    observability_reports_main(["--output-dir", str(output_dir)])

    assert (output_dir / "observability_report.json").exists()
    assert (output_dir / "observability_report.md").exists()
    assert (output_dir / "observability_report.html").exists()


def test_readme_documents_existing_reproducibility_entrypoints() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    required_snippets = [
        "./scripts/reproduce.sh",
        "uv run python -m app.demo.run_demo",
        "uv run python -m app.benchmark.runner",
        "uv run python -m app.observability.reports",
        "docker-compose.yml",
        "/v1/replay/access/{access_id}",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in readme]
    assert missing == []
```

- [ ] **Step 3: Run tests and observe expected failure before README exists**

Run:

```bash
uv run pytest apps/api/tests/integration/test_reproducibility.py -q
```

Expected before README creation: the README drift test fails with `FileNotFoundError` for `README.md`; report generation tests may pass.

---

### Task 5: Add README Showcase Documentation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Create `README.md` with these sections and exact command snippets:

```markdown
# MemTrace

MemTrace is a state-aware memory runtime and profiler for long-horizon LLM agents. It records agent traces, builds an execution state tree, writes structured memories, retrieves context with state awareness, gates unsafe or stale memories before prompt injection, and reports every retrieval decision.

## Why MemTrace

Vector memory alone can recall the wrong thing at the wrong time: a failed branch, another workspace's preference, stale endpoint guidance, or risky tool evidence. MemTrace treats memory as runtime infrastructure rather than a generic RAG store:

- **Trace first:** raw runs, steps, and events are persisted before memory extraction.
- **State-aware retrieval:** active execution paths influence candidate selection and scoring.
- **Admission gate:** failed/rolled-back, stale, superseded, cross-workspace, secret, and risky memories are rejected or degraded before context packing.
- **Replayable observability:** access logs, gate logs, profiler events, and replay APIs explain why a memory entered or missed the prompt.

## Architecture

```mermaid
flowchart TD
    Agent[Agent / demo loop] --> Runtime[MemoryRuntime facade]
    Runtime --> Trace[Trace Collector]
    Runtime --> State[Execution State Tree]
    Runtime --> Writer[Rule / LLM Write Pipeline]
    Runtime --> Retrieval[Retrieval Controller]
    Retrieval --> Gate[Admission Gate]
    Gate --> Packer[Context Packer]
    Runtime --> Profiler[Profiler]
    Trace --> PG[(PostgreSQL + pgvector)]
    State --> PG
    Writer --> PG
    Retrieval --> PG
    Profiler --> PG
    Runtime --> Reports[JSON / Markdown / HTML Reports]
```

## Quickstart: deterministic reproducibility baseline

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

Install dependencies and generate all deterministic showcase reports:

```bash
uv sync --extra dev
./scripts/reproduce.sh
```

The script runs these entrypoints:

```bash
uv run python -m app.demo.run_demo --out reports
uv run python -m app.benchmark.runner --output-dir reports
uv run python -m app.observability.reports --output-dir reports
```

Generated artifacts are ignored by git and can be regenerated at any time:

- `reports/demo_report.md`
- `reports/demo_report.json`
- `reports/benchmark_report.md`
- `reports/benchmark_results.json`
- `reports/observability_report.json`
- `reports/observability_report.md`
- `reports/observability_report.html`

The deterministic benchmark passes only when `reports/benchmark_results.json` contains `acceptance.passed=true`.

## What the demo proves

The canonical demo is Bun vs Node.js with failed-branch isolation:

1. The user states that the project uses Bun, not Node.js.
2. A failed branch tries `npm test` and is rolled back.
3. A recovery step asks how to run tests.
4. `baseline_1` recalls the failed `npm test` evidence and is contaminated.
5. `variant_2` uses state-aware retrieval plus the gate, rejects the rolled-back branch, and chooses `bun test`.

Run only the demo:

```bash
uv run python -m app.demo.run_demo --out reports
```

## Benchmark variants

Run only the deterministic benchmark:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Strategies:

- `baseline_0`: no memory.
- `baseline_1`: vector/lexical memory without state-aware isolation or admission gate.
- `variant_1`: state-aware retrieval.
- `variant_2`: state-aware retrieval plus admission gate.

The benchmark covers project preference, failed-branch isolation, workspace isolation, tool-call safety, explicit correction, completed-run reuse, stale rejection, and no-memory failure recovery.

## Observability and replay

Generate a static observability report fixture:

```bash
uv run python -m app.observability.reports --output-dir reports
```

The runtime also exposes observability APIs when served through FastAPI:

- `GET /health`
- `POST /v1/context/retrieve`
- `GET /v1/access/{access_id}`
- `GET /v1/replay/access/{access_id}`
- `GET /v1/replay/runs/{run_id}`
- `GET /v1/observability/summary`
- `POST /v1/observability/reports`
- `GET /v1/dashboard/tables`

## Optional PostgreSQL + API mode

The deterministic quickstart above does not require Docker. To explore the SQL-backed runtime, start pgvector PostgreSQL with `docker-compose.yml`:

```bash
docker-compose up -d
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Then check:

```bash
curl http://localhost:8000/health
```

The compose file uses `pgvector/pgvector:pg16` on host port `5433`. Existing PG15 volumes are not compatible with the PG16 image; switching images may require removing the old volume.

## Optional real LLM validation bench

The real LLM bench is manual and opt-in because it requires network access and a live OpenAI-compatible API key:

```bash
MEMTRACE_LLM_API_KEY=... \
MEMTRACE_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \
MEMTRACE_LLM_MODEL=deepseek-v4-pro-260425 \
uv run python -m app.benchmark.llm_bench --output-dir reports
```

It writes `reports/llm_bench_report.json` and `reports/llm_bench_report.md`.

## Local verification

Run the full local smoke bundle:

```bash
./scripts/smoke.sh
```

Or run the pieces directly:

```bash
uv run pytest -q
./scripts/reproduce.sh
uv run python -m app.benchmark.runner --output-dir reports
```

## Roadmap

The completed MVP, Phase 3-A observability work, and future priorities are tracked in `ROADMAP.md`. Current recommended next areas are context compaction, SDK/LangGraph integration, and expanded strategy benchmarks.
```

- [ ] **Step 2: Run README drift test**

Run:

```bash
uv run pytest apps/api/tests/integration/test_reproducibility.py::test_readme_documents_existing_reproducibility_entrypoints -q
```

Expected: PASS.

---

### Task 6: Fix Observability Entrypoint Test Compatibility If Needed

**Files:**
- Modify only if test reveals signature mismatch: `apps/api/app/observability/reports.py`

- [ ] **Step 1: Run integration tests**

Run:

```bash
uv run pytest apps/api/tests/integration/test_reproducibility.py -q
```

Expected: If `observability_reports_main` does not accept an argv list, the observability entrypoint test fails with a `TypeError`.

- [ ] **Step 2: Make `main` accept optional argv if needed**

If the test fails with that `TypeError`, change the function signature in `apps/api/app/observability/reports.py` from:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Write an empty MemTrace observability report fixture")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
```

to:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write an empty MemTrace observability report fixture")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args(argv)
```

Leave the existing `if __name__ == "__main__": main()` call unchanged.

- [ ] **Step 3: Re-run integration tests**

Run:

```bash
uv run pytest apps/api/tests/integration/test_reproducibility.py -q
```

Expected: PASS.

---

### Task 7: Optional API Compose Layer

**Files:**
- Create only if local Docker build is straightforward: `docker-compose.api.yml`
- Modify only if required for build context correctness: no source code files

- [ ] **Step 1: Prefer no API compose if it would require packaging changes**

Inspect whether an API service can run via bind-mounted source and `uv run uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000` without adding a Dockerfile. If not, skip this task and document API startup via local `uv run` in README only.

- [ ] **Step 2: If simple, create `docker-compose.api.yml`**

Use this content only if the local environment supports a suitable Python/uv image without extra project-specific Dockerfile work:

```yaml
services:
  api:
    image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
    working_dir: /workspace
    command: uv run uvicorn app.main:app --app-dir apps/api --host 0.0.0.0 --port 8000
    environment:
      MEMTRACE_DATABASE_URL: postgresql+asyncpg://memtrace:memtrace@postgres:5432/memtrace
    ports:
      - "8000:8000"
    volumes:
      - .:/workspace
    depends_on:
      postgres:
        condition: service_healthy
```

- [ ] **Step 3: If created, update README optional API mode**

Add this command next to the local uv command:

```bash
docker-compose -f docker-compose.yml -f docker-compose.api.yml up --build
```

---

### Task 8: Update Project Memory and Roadmap

**Files:**
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Update `.ai/PROJECT_STATE.md` current state**

At the top, update the current-state paragraph to mention that the showcase/reproducibility baseline is complete: README, deterministic reproduction script, smoke script, integration tests, and regenerated report baseline.

- [ ] **Step 2: Add implemented section**

Add a new section after the latest post-P3A sections:

```markdown
## Implemented (showcase assets + reproducibility baseline — 2026-06-10)

- **README showcase:** added a top-level README with positioning, Mermaid architecture diagram, deterministic quickstart, report guide, API/observability endpoints, PostgreSQL mode, optional real-LLM bench, and roadmap pointer.
- **Reproducibility scripts:** added `scripts/reproduce.sh` for database-free deterministic demo/benchmark/observability report generation and benchmark acceptance checking; added `scripts/smoke.sh` for full local smoke verification.
- **Regression coverage:** added integration tests that generate demo/benchmark reports into a temporary directory, assert benchmark `acceptance.passed=true`, verify observability report entrypoint output, and guard README command drift.
- **Local hygiene:** `.superpowers/` is ignored; generated `reports/` remain ignored and reproducible.
```

- [ ] **Step 3: Add latest verification section**

Add:

```markdown
## Latest Verification (2026-06-10 showcase/reproducibility)

- `uv run pytest apps/api/tests/integration/test_reproducibility.py -q` -> expected pass after implementation.
- `./scripts/reproduce.sh` -> expected pass with `acceptance.passed=true`.
- `uv run pytest -q` -> expected pass.
- `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true`.
```

Replace `expected pass` with observed results after running commands.

- [ ] **Step 4: Update `ROADMAP.md`**

In section 12, mark README and demo/report example artifacts as complete. In the recommended order section, mark item 3 showcase assets as complete and move the recommendation to Context Compaction.

---

### Task 9: Full Verification

**Files:**
- No edits unless verification reveals defects.

- [ ] **Step 1: Run integration tests**

Run:

```bash
uv run pytest apps/api/tests/integration/test_reproducibility.py -q
```

Expected: all integration tests pass.

- [ ] **Step 2: Run reproduction script**

Run:

```bash
./scripts/reproduce.sh
```

Expected: exits 0 and prints `acceptance.passed=true`.

- [ ] **Step 3: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: full suite passes.

- [ ] **Step 4: Run deterministic benchmark explicitly**

Run:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Expected: `reports/benchmark_results.json` contains `"passed": true` under `acceptance`.

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected tracked changes include README, scripts, tests, `.gitignore`, `.ai/PROJECT_STATE.md`, `ROADMAP.md`, and design/plan docs. Generated `reports/` and `.superpowers/` should not appear.

---

## Self-Review

- Spec coverage: README, deterministic reproduction, optional SQL/API guidance, tests, ignore hygiene, project-state sync, and roadmap sync are each mapped to tasks.
- Placeholder scan: no TBD/TODO placeholders remain in required implementation steps.
- Type consistency: Python tests use existing public functions `run_demo`, `run_benchmark`, and the observability report entrypoint; Task 6 covers the only likely signature adjustment.
- Scope check: frontend, hosted auth, heavy infra, and default real-LLM verification are explicitly excluded.
