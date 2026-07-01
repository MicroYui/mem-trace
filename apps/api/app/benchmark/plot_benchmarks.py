"""Render committed benchmark charts (PNG) from the report JSONs (ROADMAP §7).

Reads the deterministic scale run (``dataset_bench_results.json``, 3k records ×
6 strategies), the 16-case correctness benchmark (``benchmark_results.json``),
and the optional real-LLM Q&A sample (``qa_bench_results.json``) and writes
presentation charts + a small traceable summary under ``docs/assets/``.

matplotlib is a chart-only dependency, not a runtime one, so this is meant to be
run on demand with an ephemeral install (no permanent dependency added):

    uv run --with matplotlib python -m app.benchmark.plot_benchmarks

Charts are deterministic given the same report inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Consistent palette: gray = no memory, red = leaks contamination, green = gated.
_GRAY, _RED, _AMBER, _GREEN, _BLUE = "#8a8f98", "#e5534b", "#e0a458", "#3fb950", "#4c8dff"
_STRATEGY_ORDER = ["baseline_0", "long_context", "baseline_1", "variant_1", "variant_2", "variant_3"]
_STRATEGY_LABEL = {
    "baseline_0": "baseline_0\n(no memory)",
    "long_context": "long_context\n(dump all)",
    "baseline_1": "baseline_1\n(plain vector)",
    "variant_1": "variant_1\n(no branch gate)",
    "variant_2": "variant_2\n(MemTrace)",
    "variant_3": "variant_3\n(MemTrace+reflect)",
}
_LEAKY = {"long_context", "baseline_1", "variant_1"}
_GATED = {"variant_2", "variant_3"}


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _annotate(ax, bars, values, fmt="{:.0%}"):
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                fmt.format(val), ha="center", va="bottom", fontsize=9, fontweight="bold")


def _category_stats(scale: dict) -> dict[str, dict[str, dict[str, float]]]:
    """Per-category recall + leakage for plain-vector vs MemTrace."""
    groups = {
        "dead_branch": {"failed", "rolled_back", "multi"},
        "superseded": {"superseded"},
        "valid_on_failed": {"valid_on_failed"},
        "clean": {"clean"},
    }
    out: dict[str, dict[str, dict[str, float]]] = {}
    for gname, prefixes in groups.items():
        tally = {s: {"recall": [0, 0], "leak": [0, 0]} for s in ("baseline_1", "variant_2")}
        for probe in scale["probes"]:
            cat = probe["record_id"].rsplit("_", 1)[0]
            if cat not in prefixes:
                continue
            for strat in ("baseline_1", "variant_2"):
                cell = probe["by_strategy"].get(strat)
                if not cell:
                    continue
                if cell.get("recall_scored"):
                    tally[strat]["recall"][1] += 1
                    tally[strat]["recall"][0] += int(cell.get("recall_hit", False))
                if cell.get("distractor_scored"):
                    tally[strat]["leak"][1] += 1
                    tally[strat]["leak"][0] += int(cell.get("distractor_leak", False))
        out[gname] = {
            s: {
                "recall": (t["recall"][0] / t["recall"][1] if t["recall"][1] else None),
                "leak": (t["leak"][0] / t["leak"][1] if t["leak"][1] else None),
            }
            for s, t in tally.items()
        }
    return out


def chart_contamination_by_strategy(scale: dict, out: Path) -> None:
    by = scale["by_strategy"]
    strategies = [s for s in _STRATEGY_ORDER if s in by]
    vals = [by[s]["distractor_leakage_rate"] for s in strategies]
    colors = [_GREEN if s in _GATED else _RED if s in _LEAKY else _GRAY for s in strategies]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    bars = ax.bar([_STRATEGY_LABEL[s] for s in strategies], vals, color=colors)
    _annotate(ax, bars, vals)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Failed-branch distractor leakage")
    ax.set_title(f"Contamination by retrieval strategy — {scale['record_count']:,} records\n"
                 "only the state-aware gate (variant_2/3) eliminates dead-branch leakage",
                 fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def chart_tradeoff(scale: dict, out: Path) -> None:
    """The headline: MemTrace trades some recall for zero contamination -> cleaner context."""
    by = scale["by_strategy"]
    groups = [("Plain vector\n(baseline_1)", "baseline_1"), ("MemTrace\n(variant_2)", "variant_2")]
    metrics = [
        ("Recall of\ncorrect fact", "recall_rate", _BLUE),
        ("Contamination\n(distractor leak)", "distractor_leakage_rate", _RED),
        ("Clean context\n(correct, no leak)", "clean_context_rate", _GREEN),
    ]
    x = range(len(groups))
    w = 0.26
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    for i, (label, key, color) in enumerate(metrics):
        vals = [by[g[1]][key] for g in groups]
        bars = ax.bar([j + (i - 1) * w for j in x], vals, w, label=label, color=color)
        _annotate(ax, bars, vals)
    ax.set_xticks(list(x))
    ax.set_xticklabels([g[0] for g in groups])
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("rate")
    d = scale["delta"]
    ax.set_title(
        f"The tradeoff — {scale['record_count']:,} records\n"
        f"MemTrace gives up {d['recall_cost']:.0%} recall to remove "
        f"{d['distractor_leakage_reduction']:.0%} contamination → +{d['clean_context_gain']:.0%} clean context",
        fontsize=11)
    ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="upper center")
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def chart_recall_cost_by_category(cats: dict, out: Path) -> None:
    """Where MemTrace's recall cost comes from: only 'valid fact on a failed branch'."""
    labels = {
        "dead_branch": "Dead-branch\ndistractor",
        "superseded": "Superseded\n(outdated)",
        "valid_on_failed": "Valid fact on\nfailed branch",
        "clean": "Clean\nrecall",
    }
    order = [c for c in ["dead_branch", "superseded", "valid_on_failed", "clean"] if c in cats]
    plain = [cats[c]["baseline_1"]["recall"] or 0.0 for c in order]
    memtrace = [cats[c]["variant_2"]["recall"] or 0.0 for c in order]
    x = range(len(order))
    w = 0.36
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    b1 = ax.bar([i - w / 2 for i in x], plain, w, label="Plain vector (baseline_1)", color=_RED)
    b2 = ax.bar([i + w / 2 for i in x], memtrace, w, label="MemTrace (variant_2)", color=_GREEN)
    _annotate(ax, b1, plain)
    _annotate(ax, b2, memtrace)
    ax.set_xticks(list(x))
    ax.set_xticklabels([labels[c] for c in order])
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("recall of the correct fact")
    ax.set_title("Where the recall cost comes from\n"
                 "MemTrace loses recall ONLY when a valid fact sits on a failed branch",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="center", bbox_to_anchor=(0.62, 0.42))
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render committed benchmark charts from report JSONs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--assets-dir", default="docs/assets")
    args = parser.parse_args()
    reports, assets = Path(args.reports_dir), Path(args.assets_dir)
    assets.mkdir(parents=True, exist_ok=True)

    scale = _load(reports / "dataset_bench_results.json")
    if scale is None:
        raise SystemExit("missing dataset_bench_results.json; run app.benchmark.dataset_bench first")
    cats = _category_stats(scale)
    chart_contamination_by_strategy(scale, assets / "benchmark_contamination_by_strategy.png")
    chart_tradeoff(scale, assets / "benchmark_tradeoff.png")
    chart_recall_cost_by_category(cats, assets / "benchmark_recall_cost_by_category.png")

    bench16 = _load(reports / "benchmark_results.json")
    qa = _load(reports / "qa_bench_results.json")
    locomo = _load(reports / "locomo_bench_results.json")
    checks = (bench16 or {}).get("acceptance", {}).get("checks", {})
    summary = {
        "scale": {
            "records": scale["record_count"],
            "probes": scale["probe_count"],
            "by_strategy": scale["by_strategy"],
            "delta": scale["delta"],
            "category_stats": cats,
        },
        "correctness_16_case": {
            "acceptance_passed": (bench16 or {}).get("acceptance", {}).get("passed"),
            "checks_passed": sum(1 for v in checks.values() if v),
            "checks_total": len(checks),
        },
        "real_llm_qa": None if qa is None else {
            "model": qa.get("endpoint", {}).get("model"),
            "passed": qa.get("passed"),
            "memory_improvement_count": qa.get("memory_improvement_count"),
            "scenario_count": len(qa.get("scenarios", [])),
        },
        "real_llm_locomo": None if (locomo is None or locomo.get("skipped")) else {
            "model": locomo.get("endpoint", {}).get("model"),
            "sample_size": locomo.get("sample_size"),
            "accuracy": locomo.get("accuracy"),
            "accuracy_by_category": locomo.get("accuracy_by_category"),
        },
    }
    (assets / "benchmark_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("wrote charts + benchmark_summary.json to", assets)
    print("delta:", json.dumps(scale["delta"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
