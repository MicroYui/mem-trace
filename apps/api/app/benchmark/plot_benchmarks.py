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


def chart_trace_isolation(trace: dict, out: Path) -> None:
    """Tree-trace headline: full recall, contamination eliminated, ~3x clean context."""
    by = trace["by_strategy"]
    groups = [("Plain vector\n(baseline_1)", "baseline_1"), ("MemTrace\n(variant_2)", "variant_2")]
    metrics = [
        ("Recall of\ncorrect fact", "recall_rate", _BLUE),
        ("Contamination\n(dead-branch leak)", "contamination_rate", _RED),
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
    d = trace["delta"]
    ax.set_title(
        f"Real execution trees — {trace['scenarios']} runs × {trace['subgoals_per_scenario']} subgoals "
        f"({trace['probe_count']:,} probes)\n"
        f"MemTrace keeps full recall and removes {d['contamination_reduction']:.0%} contamination "
        f"→ +{d['clean_context_gain']:.0%} clean context",
        fontsize=10.5)
    ax.legend(frameon=False, fontsize=8.5, ncol=3, loc="upper center")
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def chart_trace_tokens(trace: dict, out: Path) -> None:
    """Long-horizon context cost: long_context bloats; MemTrace stays compact."""
    by = trace["by_strategy"]
    order = [s for s in ["long_context", "baseline_1", "variant_2"] if s in by]
    label = {"long_context": "long_context\n(dump all)", "baseline_1": "plain vector\n(baseline_1)",
             "variant_2": "MemTrace\n(variant_2)"}
    vals = [by[s]["avg_context_tokens"] for s in order]
    colors = [_RED if s == "long_context" else _AMBER if s == "baseline_1" else _GREEN for s in order]
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    bars = ax.bar([label[s] for s in order], vals, color=colors)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.01,
                f"{v:.0f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylabel("avg context tokens per retrieval")
    ratio = trace["delta"].get("context_token_ratio_vs_long_context")
    sub = f" — MemTrace is {ratio:.0%} of dump-all" if ratio else ""
    ax.set_title(f"Long-horizon context cost{sub}", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def chart_longmemeval(lme: dict, out: Path) -> None:
    """LongMemEval real-dataset accuracy: no-memory vs plain-vector vs MemTrace,
    overall and per question_type. The headline is the real scale (tens of thousands
    of real memories) and that memory transforms accuracy."""
    conds = [("no_memory", _GRAY), ("plain_vector", _AMBER), ("memtrace", _GREEN)]
    label = {"no_memory": "no memory", "plain_vector": "plain vector", "memtrace": "MemTrace"}
    types = list(lme.get("accuracy_by_type", {}).keys())
    groups = ["overall"] + types
    fig, ax = plt.subplots(figsize=(max(8.0, 1.2 * len(groups) + 3), 4.8))
    x = range(len(groups))
    w = 0.26
    for i, (cond, color) in enumerate(conds):
        vals = [lme["accuracy"].get(cond, 0.0)] + [lme["accuracy_by_type"][t].get(cond, 0.0) for t in types]
        bars = ax.bar([j + (i - 1) * w for j in x], vals, w, label=label[cond], color=color)
        _annotate(ax, bars, vals)
    ax.set_xticks(list(x))
    ax.set_xticklabels([g.replace("-", "-\n") for g in groups], fontsize=8)
    ax.set_ylim(0, 1.15)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_ylabel("answer accuracy (LLM-judged)")
    ax.set_title(
        f"LongMemEval — {lme['sample_size']} questions over {lme['total_memories']:,} real memories\n"
        f"real embeddings ({lme.get('embedding', 'openai')}) + real LLM answer & judge "
        f"({lme['endpoint']['model']})",
        fontsize=10.5)
    ax.legend(frameon=False, fontsize=9, ncol=3, loc="upper center")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def chart_longmemeval_precision(lme: dict, out: Path) -> None:
    """The MemTrace edge on LongMemEval: the relevance gate drops distractors, so
    MemTrace answers with fewer injected tokens + lower distractor rate and abstains
    correctly more often than plain vector."""
    abst = lme.get("abstention_accuracy", {})
    prec = lme.get("context_precision", {})
    pv, mt = prec.get("plain_vector", {}), prec.get("memtrace", {})
    panels = [
        ("abstention\naccuracy", abst.get("plain_vector", 0.0), abst.get("memtrace", 0.0), "{:.0%}", 1.15),
        ("distractor\nrate", pv.get("avg_distractor_rate", 0.0), mt.get("avg_distractor_rate", 0.0), "{:.0%}", 1.15),
    ]
    tok_pv, tok_mt = pv.get("avg_injected_tokens", 0.0), mt.get("avg_injected_tokens", 0.0)
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.4))
    for ax, (title, v_pv, v_mt, fmt, ymax) in zip(axes[:2], panels):
        bars = ax.bar(["plain\nvector", "MemTrace"], [v_pv, v_mt], color=[_AMBER, _GREEN])
        for b, v in zip(bars, [v_pv, v_mt]):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + ymax * 0.01, fmt.format(v),
                    ha="center", va="bottom", fontsize=10, fontweight="bold")
        ax.set_ylim(0, ymax)
        ax.set_title(title, fontsize=10)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.spines[["top", "right"]].set_visible(False)
    ax = axes[2]
    bars = ax.bar(["plain\nvector", "MemTrace"], [tok_pv, tok_mt], color=[_AMBER, _GREEN])
    for b, v in zip(bars, [tok_pv, tok_mt]):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(tok_pv, tok_mt, 1) * 0.01,
                f"{v:.0f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_title("avg injected tokens", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("LongMemEval — MemTrace's relevance gate: cleaner context, better abstention", fontsize=11)
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

    trace = _load(reports / "trace_bench_results.json")
    if trace is not None:
        chart_trace_isolation(trace, assets / "benchmark_trace_isolation.png")
        chart_trace_tokens(trace, assets / "benchmark_trace_tokens.png")

    bench16 = _load(reports / "benchmark_results.json")
    qa = _load(reports / "qa_bench_results.json")
    locomo = _load(reports / "locomo_bench_results.json")
    lme = _load(reports / "longmemeval_bench_results.json")
    if lme is not None and not lme.get("skipped"):
        chart_longmemeval(lme, assets / "benchmark_longmemeval.png")
        chart_longmemeval_precision(lme, assets / "benchmark_longmemeval_precision.png")
    checks = (bench16 or {}).get("acceptance", {}).get("checks", {})
    summary = {
        "scale": {
            "records": scale["record_count"],
            "probes": scale["probe_count"],
            "by_strategy": scale["by_strategy"],
            "delta": scale["delta"],
            "category_stats": cats,
        },
        "tree_trace": None if trace is None else {
            "scenarios": trace["scenarios"],
            "subgoals_per_scenario": trace["subgoals_per_scenario"],
            "probes": trace["probe_count"],
            "by_strategy": trace["by_strategy"],
            "delta": trace["delta"],
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
        "real_llm_longmemeval": None if (lme is None or lme.get("skipped")) else {
            "model": lme.get("endpoint", {}).get("model"),
            "embedding": lme.get("embedding"),
            "sample_size": lme.get("sample_size"),
            "total_memories": lme.get("total_memories"),
            "accuracy": lme.get("accuracy"),
            "accuracy_by_type": lme.get("accuracy_by_type"),
            "abstention_accuracy": lme.get("abstention_accuracy"),
            "context_precision": lme.get("context_precision"),
        },
    }
    (assets / "benchmark_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("wrote charts + benchmark_summary.json to", assets)
    print("delta:", json.dumps(scale["delta"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
