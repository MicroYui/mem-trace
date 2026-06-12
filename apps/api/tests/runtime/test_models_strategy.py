"""6-strategy enum coverage."""

from __future__ import annotations

from app.runtime.models import RetrievalStrategy


def test_retrieval_strategy_has_six_members():
    assert [s.value for s in RetrievalStrategy] == [
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    ]

    values = {s.value for s in RetrievalStrategy}
    assert values == {
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    }
