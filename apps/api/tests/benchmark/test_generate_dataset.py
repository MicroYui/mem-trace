"""Determinism + validity of the synthetic scale-benchmark dataset generator."""
from __future__ import annotations

from app.benchmark.dataset_bench import DatasetRecord
from app.benchmark.generate_dataset import TOPICS, generate


def test_generation_is_deterministic():
    assert generate(120) == generate(120)


def test_records_validate_against_schema():
    for record in generate(120):
        DatasetRecord.model_validate(record)  # raises on schema drift


def test_category_mix_matches_fixed_proportions():
    counts: dict[str, int] = {}
    for record in generate(200):
        cat = record["id"].rsplit("_", 1)[0]
        counts[cat] = counts.get(cat, 0) + 1
    # 20-slot cycle: 6 failed / 3 rolled_back / 2 multi / 3 superseded / 3 clean /
    # 3 valid_on_failed, ×10 for 200 records.
    assert counts == {
        "failed": 60, "rolled_back": 30, "multi": 20,
        "superseded": 30, "clean": 30, "valid_on_failed": 30,
    }


def test_valid_on_failed_puts_correct_fact_on_a_failed_branch():
    seen = False
    for record in generate(200):
        if not record["id"].startswith("valid_on_failed_"):
            continue
        seen = True
        correct_fact = record["facts"][0]
        # correct fact itself is on a failed branch, and there is no distractor
        assert correct_fact["branch_status"] == "failed"
        assert record["probes"][0]["distractor_markers"] == []
        assert correct_fact["value"] in correct_fact["content"]
    assert seen


def test_markers_are_substring_safe_and_well_placed():
    for record in generate(240):
        probe = record["probes"][0]
        contents = [f["content"].lower() for f in record["facts"]]
        joined = " ".join(contents)
        # recall marker present; every distractor marker present (leakable) ...
        for marker in probe["recall_markers"]:
            assert marker.lower() in joined
        # correct fact is the first fact; the recall marker must live there and
        # must NOT be produced by any distractor/noise fact alone (else recall
        # would be a false positive when the correct fact is gated out).
        correct_content = contents[0]
        for marker in probe["recall_markers"]:
            assert marker.lower() in correct_content
            for other in contents[1:]:
                assert marker.lower() not in other
        # distractor markers must NOT appear in the correct fact (else variant_2
        # would show a spurious leak even after gating the dead branch).
        for marker in probe["distractor_markers"]:
            assert marker.lower() in joined
            assert marker.lower() not in correct_content


def test_clean_records_have_no_distractor():
    for record in generate(200):
        if record["id"].startswith("clean_"):
            assert record["probes"][0]["distractor_markers"] == []


def test_topics_are_internally_substring_safe():
    for _subject, correct, wrong in TOPICS:
        assert correct not in wrong and wrong not in correct
