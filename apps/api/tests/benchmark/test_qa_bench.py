"""Real-LLM Q&A bench must be opt-in: skip cleanly with no endpoint configured."""
from __future__ import annotations

import pytest

from app.benchmark import qa_bench
from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_qa_bench_skips_without_endpoint(monkeypatch):
    for var in ("MEMTRACE_LLM_API_KEY", "MEMTRACE_LLM_BENCH_ENDPOINTS",
                "MEMTRACE_LLM_BASE_URL", "MEMTRACE_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()

    payload = await qa_bench.run_qa_bench(output_dir="/tmp/qa_bench_skip")

    assert payload["skipped"] is True
    assert "No LLM endpoint configured" in payload["reason"]


def test_scenarios_are_well_formed():
    assert len(qa_bench.SCENARIOS) >= 4
    names = {s.name for s in qa_bench.SCENARIOS}
    assert {"project_preference", "stale_exclusion", "multi_fact_recall"} <= names
    for sc in qa_bench.SCENARIOS:
        assert sc.expected_markers, f"{sc.name} must declare expected markers"
        assert sc.question.strip()


@pytest.mark.asyncio
async def test_qa_bench_flow_scores_memory_improvement_with_mocked_llm(monkeypatch):
    """End-to-end harness flow (seed -> retrieve -> prompt -> score) with only the
    network chat call mocked: a context-using LLM answers correctly when the
    MemTrace context carries the expected fact and abstains otherwise, so the
    bench records the memory condition as correct and an improvement."""

    async def _fake_chat(client, endpoint, system, user):
        # Simulate an LLM that answers only from the provided context.
        ctx = user.lower()
        found = [m for m in ("bun", "pnpm", "postgres", "v2") if m in ctx]
        if not found:
            return "I do not have that information."
        return "based on the project memory the answer includes: " + ", ".join(found)

    monkeypatch.setattr(qa_bench, "_resolve_endpoints",
                        lambda: [{"name": "mock", "api_key": "k", "base_url": "http://x/v1", "model": "m"}])
    monkeypatch.setattr(qa_bench, "_chat", _fake_chat)

    payload = await qa_bench.run_qa_bench(output_dir="/tmp/qa_bench_mock")

    assert payload["skipped"] is False
    by_name = {r["scenario"]: r for r in payload["scenarios"]}
    # With memory the context-using LLM answers correctly; without memory it abstains.
    assert by_name["project_preference"]["memory_correct"] is True
    assert by_name["project_preference"]["nomemory_correct"] is False
    assert by_name["project_preference"]["memory_improves"] is True
    assert payload["memory_improvement_count"] >= 3
