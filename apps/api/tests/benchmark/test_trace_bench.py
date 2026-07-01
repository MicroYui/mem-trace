"""Tree-trace benchmark: determinism + the core isolation contract."""
from __future__ import annotations

import pytest

from app.benchmark.trace_bench import generate_scenarios, run_trace_bench
from app.runtime.models import RetrievalStrategy


def test_scenario_generation_is_deterministic():
    a = generate_scenarios(6, 5)
    b = generate_scenarios(6, 5)
    assert [(s.scenario_id, [(g.subject, g.correct, tuple(g.wrong_attempts)) for g in s.subgoals]) for s in a] == \
           [(s.scenario_id, [(g.subject, g.correct, tuple(g.wrong_attempts)) for g in s.subgoals]) for s in b]


def test_scenarios_contain_dead_branches_and_clean_subgoals():
    scenarios = generate_scenarios(6, 6)
    fail_counts = {len(g.wrong_attempts) for s in scenarios for g in s.subgoals}
    # the 0/1/2 dead-branch cycle must all appear
    assert fail_counts == {0, 1, 2}


@pytest.mark.asyncio
async def test_memtrace_isolates_dead_branches_plain_vector_does_not():
    payload = await run_trace_bench(
        scenarios=4, subgoals=4, output_dir=None,
        strategies=[RetrievalStrategy.baseline_1, RetrievalStrategy.variant_2],
    )
    plain = payload["by_strategy"]["baseline_1"]
    memtrace = payload["by_strategy"]["variant_2"]
    # both recall the correct current fact (on the active/recovered path) ...
    assert plain["recall_rate"] == 1.0
    assert memtrace["recall_rate"] == 1.0
    # ... but only MemTrace isolates the dead-branch distractors.
    assert plain["contamination_rate"] > 0.0
    assert memtrace["contamination_rate"] == 0.0
    assert memtrace["clean_context_rate"] > plain["clean_context_rate"]
    assert payload["delta"]["contamination_reduction"] > 0.0
