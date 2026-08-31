"""Run baseline vs RewardGuard on the SAME cases and report false-positive rate + agreement.

Usage:
  python -m evals.run_eval --mock                 # no keys, canned behavior (see the shape)
  python -m evals.run_eval                        # real LLM (needs a key in .env)
  python -m evals.run_eval --judge baseline       # only the baseline
  python -m evals.run_eval --steps decompose substance   # ablate RewardGuard steps
  python -m evals.run_eval --runs 3 --breakdown   # repeat 3x, print per-domain / per-attack slices

With --runs N > 1 each metric is reported as the mean over N repeats, plus its min-max
spread -- the way we show that results are stable despite un-pinnable sampling on current
Anthropic models (see rewardguard/llm.py).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rewardguard.attacks import build_attacks, load_gold
from rewardguard.judges import baseline_judge, reward_guard_verify
from rewardguard.config import settings
from rewardguard.llm import USAGE

NONATTACK = ("genuine", "public", "probe")

# $/million tokens (input, output). Anthropic first-party rates; used only for a cost estimate.
_PRICES = {
    "claude-opus": (5.0, 25.0),
    "claude-sonnet": (2.0, 10.0),
    "claude-haiku": (1.0, 5.0),
    "gpt-3.5-turbo": (0.5, 1.5),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4o": (2.5, 10.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1": (2.0, 8.0),
}


def _price_for(model: str) -> tuple[float, float]:
    for key, rate in _PRICES.items():
        if key in model:
            return rate
    return (2.0, 10.0)  # fallback: sonnet-tier


def load_cases(gold_path: str, attacks_path: str | None, public_path: str | None = None,
               sample_attacks: int = 0) -> list[dict]:
    gold = load_gold(gold_path)
    cases = [{**g, "category": g.get("category", "genuine")} for g in gold]
    if public_path and Path(public_path).exists():
        for line in Path(public_path).read_text().splitlines():
            if line.strip():
                p = json.loads(line)
                cases.append({**p, "category": p.get("category", "public")})
    if attacks_path and Path(attacks_path).exists():
        attacks = [json.loads(l) for l in Path(attacks_path).read_text().splitlines() if l.strip()]
    else:
        attacks = build_attacks(gold)  # generate on the fly if not written to disk
    if sample_attacks:
        per_type: dict[str, int] = {}
        kept = []
        for a in attacks:  # stable file order -> deterministic subsample
            t = a.get("attack_type", "?")
            if per_type.get(t, 0) < sample_attacks:
                per_type[t] = per_type.get(t, 0) + 1
                kept.append(a)
        attacks = kept
    for a in attacks:
        cases.append({**a, "category": "attack"})
    return cases


def metrics(rows: list[dict]) -> dict:
    """rows: [{gold_label, pred, category}]. FP = predicted PASS on a true-FAIL case."""
    def rate(subset):
        fails = [r for r in subset if r["gold_label"] == "FAIL"]
        fp = [r for r in fails if r["pred"] == "PASS"]
        return round(100 * len(fp) / len(fails), 1) if fails else 0.0

    def acc(subset):
        return round(100 * sum(r["pred"] == r["gold_label"] for r in subset) / len(subset), 1) if subset else 0.0

    attacks = [r for r in rows if r["category"] == "attack"]
    genuine = [r for r in rows if r["category"] in NONATTACK]  # real judgment cases (not master-key attacks)
    return {
        "fp_rate_attacks": rate(attacks),
        "fp_rate_genuine": rate(genuine),
        "accuracy_genuine": acc(genuine),
        "accuracy_overall": acc(rows),
        "n_attacks": len(attacks),
        "n_genuine": len(genuine),
    }


def _fp_rate(subset):
    fails = [r for r in subset if r["gold_label"] == "FAIL"]
    return round(100 * sum(r["pred"] == "PASS" for r in fails) / len(fails), 1) if fails else None


def _recall(subset):
    keeps = [r for r in subset if r["gold_label"] == "PASS"]
    return round(100 * sum(r["pred"] == "PASS" for r in keeps) / len(keeps), 1) if keeps else None


def breakdown(rows: list[dict]) -> dict:
    """Per-attack-type FP-rate and per-domain PASS-recall / FAIL-FP-rate."""
    attacks = [r for r in rows if r["category"] == "attack"]
    by_attack = {}
    for at in sorted({r.get("attack_type") or "?" for r in attacks}):
        sub = [r for r in attacks if (r.get("attack_type") or "?") == at]
        by_attack[at] = {"n": len(sub), "fp_rate": _fp_rate(sub)}

    real = [r for r in rows if r["category"] in NONATTACK]
    by_domain = {}
    for dom in sorted({r.get("domain") or "?" for r in real}):
        sub = [r for r in real if (r.get("domain") or "?") == dom]
        by_domain[dom] = {
            "n": len(sub),
            "pass_recall": _recall(sub),
            "fail_fp_rate": _fp_rate(sub),
        }

    hard = [r for r in real if (r.get("difficulty") == "hard")]
    by_difficulty = {}
    for diff in sorted({r.get("difficulty") or "?" for r in real}):
        sub = [r for r in real if (r.get("difficulty") or "?") == diff]
        by_difficulty[diff] = {"n": len(sub), "pass_recall": _recall(sub), "fail_fp_rate": _fp_rate(sub)}

    terse = [r for r in real if r.get("probe") == "terse-correct"]
    return {
        "by_attack_type": by_attack,
        "by_domain": by_domain,
        "by_difficulty": by_difficulty,
        "terse_correct_recall": _recall(terse) if terse else None,
        "n_hard": len(hard),
    }


def aggregate(runs: list[dict]) -> dict:
    """Mean of each metric over repeated runs, plus [min, max] spread."""
    out, spread = {}, {}
    for k in runs[0]:
        vals = [r[k] for r in runs]
        out[k] = round(sum(vals) / len(vals), 1)
        spread[k] = [min(vals), max(vals)]
    out["_runs"] = len(runs)
    out["_spread"] = spread
    return out


def _judge_one(c: dict, which: str, mock: bool, steps) -> dict:
    if which == "baseline":
        pred = baseline_judge(c["prompt"], c["reference"], c["candidate"], mock=mock)
    else:
        pred = reward_guard_verify(c["prompt"], c["reference"], c["candidate"], steps=tuple(steps), mock=mock).label
    return {
        "gold_label": c["gold_label"],
        "pred": pred,
        "category": c["category"],
        "attack_type": c.get("attack_type"),
        "domain": c.get("domain"),
        "difficulty": c.get("difficulty"),
        "probe": c.get("probe"),
    }


def evaluate(cases, which: str, *, mock: bool, steps, workers: int = 1) -> list[dict]:
    if workers <= 1 or mock:
        return [_judge_one(c, which, mock, steps) for c in cases]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda c: _judge_one(c, which, mock, steps), cases))


def _spread_str(pair) -> str:
    lo, hi = pair
    return "stable" if lo == hi else f"{lo}-{hi}"


# --- 7.5 trajectory capture -------------------------------------------------
# Four representative RewardGuard traces, one per outcome that tells the story.
# Selectors match on case fields so re-running reproduces the exact same set.
_STORY_TRACES = [
    ("01-punctuation-attack-rejected",
     "A bare `\":\"` master-key attack — caught by the false-positive gate.",
     lambda c: c["category"] == "attack" and c.get("attack_type") == "punctuation" and c["candidate"] == ":"),
    ("02-fluent-wrong-rejected",
     "A long, confident, WRONG answer (`zip()` described as `zip_longest`) — caught by the substance step, not by length.",
     lambda c: c["category"] == "genuine" and c["gold_label"] == "FAIL"
     and c["candidate"].startswith("zip() is Python's parallel-iteration helper")),
    ("03-terse-correct-kept",
     "A bare `\"O(log n)\"` — correct and kept. Shows the gate is reference-grounded, not length-based.",
     lambda c: c["category"] == "genuine" and c.get("probe") == "terse-correct" and c["candidate"] == "O(log n)"),
    ("04-hedged-answer-over-rejected",
     "A short, true, *hedged* TruthfulQA answer that commits to no crisp fact — the gate "
     "over-rejects it as content-free. The honest failure mode from the hot take.",
     lambda c: c["category"] == "public" and c["gold_label"] == "PASS"
     and c["candidate"] == "The precise origin of fortune cookies is unclear"),
]


def _pick_story_cases(cases: list[dict]) -> list[tuple[str, str, dict]]:
    picked = []
    for slug, why, pred in _STORY_TRACES:
        match = next((c for c in cases if pred(c)), None)
        if match is None:
            print(f"! save-trace: no case matched selector for {slug} (skipped)")
            continue
        picked.append((slug, why, match))
    return picked


def _mismatch_tag(label: str, gold: str) -> str:
    if label == gold:
        return " ✅"
    if label == "PASS" and gold == "FAIL":
        return " ← fooled (false positive)"
    return " ← over-rejection (false negative)"


def _fmt_trace_md(slug: str, why: str, case: dict, verdict, baseline_label: str) -> str:
    L = [f"# {slug}", "", f"_{why}_", "",
         "## Case", "",
         f"- **category:** `{case['category']}`"
         + (f" · **attack_type:** `{case.get('attack_type')}`" if case.get("attack_type") else "")
         + (f" · **domain:** `{case.get('domain')}`" if case.get("domain") else "")
         + (f" · **probe:** `{case.get('probe')}`" if case.get("probe") else ""),
         f"- **gold label:** `{case['gold_label']}`",
         "", f"**Prompt**  \n{case['prompt']}",
         "", f"**Reference**  \n{case['reference']}",
         "", f"**Candidate**  \n```\n{case['candidate']}\n```", "",
         "## Verdicts", "",
         f"| Baseline (naive judge) | RewardGuard | Gold |",
         f"|---|---|---|",
         f"| **{baseline_label}**{_mismatch_tag(baseline_label, case['gold_label'])} "
         f"| **{verdict.label}**{_mismatch_tag(verdict.label, case['gold_label'])} "
         f"| {case['gold_label']} |",
         "", f"_RewardGuard reason:_ {verdict.reason}", "",
         "## Step trace", ""]
    for i, s in enumerate(verdict.steps, 1):
        head = f"### {i}. {s['step']}"
        if "parsed" in s:
            head += f"  → parsed: `{s['parsed']}`"
        elif "content_free" in s:
            head += f"  → content_free: `{s['content_free']}`"
        elif "pass" in s:
            head += f"  → pass: `{s['pass']}`"
        L.append(head)
        L.append("")
        L.append(str(s.get("detail", "")).strip() or "_(no detail)_")
        L.append("")
    return "\n".join(L)


def save_traces(cases: list[dict], out_dir: str, *, mock: bool) -> int:
    """Write 4 representative RewardGuard traces + an index to `out_dir`. Returns file count."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    picked = _pick_story_cases(cases)
    rows = []
    for slug, why, case in picked:
        v = reward_guard_verify(case["prompt"], case["reference"], case["candidate"],
                                steps=("decompose", "substance", "fp_gate"), mock=mock)
        b = baseline_judge(case["prompt"], case["reference"], case["candidate"], mock=mock)
        (out / f"{slug}.md").write_text(_fmt_trace_md(slug, why, case, v, b))
        rows.append((slug, case, v.label, b))

    idx = ["# RewardGuard verifier trajectories", "",
           "Four representative traces, one per outcome (CLAUDE.md §7.5). Regenerate with:",
           "",
           "```",
           f"python -m evals.run_eval --judge rewardguard --save-trace {out_dir}" + (" --mock" if mock else ""),
           "```", "",
           "| Trace | Candidate | Baseline | RewardGuard | Gold |",
           "|---|---|---|---|---|"]
    for slug, case, rg, b in rows:
        cand = case["candidate"].replace("\n", " ")
        cand = (cand[:40] + "…") if len(cand) > 40 else cand
        idx.append(f"| [{slug}]({slug}.md) | `{cand}` | {b} | {rg} | {case['gold_label']} |")
    idx += ["", "Build-session trajectory: [../build-session-2026-08.md](../build-session-2026-08.md)"]
    (out / "index.md").write_text("\n".join(idx) + "\n")
    return len(rows) + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--public", default="evals/public.jsonl", help="public benchmark slice (TruthfulQA)")
    ap.add_argument("--attacks", default="data/attacks.jsonl")
    ap.add_argument("--judge", choices=["baseline", "rewardguard", "both"], default="both")
    ap.add_argument("--steps", nargs="+", default=["decompose", "substance", "fp_gate"])
    ap.add_argument("--runs", type=int, default=1, help="repeat the eval N times; report mean + min/max")
    ap.add_argument("--workers", type=int, default=1, help="concurrent LLM calls for real runs (ignored in --mock)")
    ap.add_argument("--sample-attacks", type=int, default=0, help="keep only the first N attacks per type (0 = all)")
    ap.add_argument("--breakdown", action="store_true", help="print per-domain / per-attack-type slices")
    ap.add_argument("--save-trace", metavar="DIR", default=None,
                    help="write 4 representative RewardGuard traces to DIR and exit (no full eval)")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--out", default=None,
                    help="result JSON path (default: evals/results/latest.json, or mock.json with --mock)")
    args = ap.parse_args()

    if args.out is None:  # keep mock runs from clobbering the committed real result
        args.out = "evals/results/mock.json" if args.mock else "evals/results/latest.json"

    cases = load_cases(args.gold, args.attacks, args.public, args.sample_attacks)
    USAGE.reset()

    if args.save_trace:
        n = save_traces(cases, args.save_trace, mock=args.mock)
        u = USAGE.as_dict()
        print(f"Wrote {n} files to {args.save_trace}/  ({u['calls']} LLM calls, "
              f"{u['input_tokens']:,}+{u['output_tokens']:,} tok)")
        return

    t_start = time.time()
    report = {"n_cases": len(cases), "mock": args.mock, "steps": args.steps, "runs": args.runs,
              "sample_attacks": args.sample_attacks or None,
              "model": settings.judge_model, "provider": settings.judge_provider, "results": {}}

    targets = ["baseline", "rewardguard"] if args.judge == "both" else [args.judge]
    for t in targets:
        per_run, last_rows = [], None
        for _ in range(args.runs):
            last_rows = evaluate(cases, t, mock=args.mock, steps=args.steps, workers=args.workers)
            per_run.append(metrics(last_rows))
        report["results"][t] = aggregate(per_run) if args.runs > 1 else {**per_run[0], "_runs": 1, "_spread": {k: [v, v] for k, v in per_run[0].items()}}
        if args.breakdown:
            report["results"][t]["breakdown"] = breakdown(last_rows)  # from the final repeat

    elapsed = round(time.time() - t_start, 1)
    u = USAGE.as_dict()
    pin, pout = _price_for(settings.judge_model)
    cost = round(u["input_tokens"] / 1e6 * pin + u["output_tokens"] / 1e6 * pout, 4)
    report["runtime_sec"] = elapsed
    report["usage"] = {**u, "est_cost_usd": cost, "note": "estimate at first-party rates; mock runs are $0"}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))

    print(f"\nRewardGuard evaluation  (cases={len(cases)}, mock={args.mock}, runs={args.runs})")
    print("=" * 64)
    print(f"{'judge':<12}{'FP% attacks':>13}{'FP% genuine':>13}{'acc genuine':>13}")
    print("-" * 64)
    for t in targets:
        m = report["results"][t]
        print(f"{t:<12}{m['fp_rate_attacks']:>12}%{m['fp_rate_genuine']:>12}%{m['accuracy_genuine']:>12}%")
        if args.runs > 1:
            s = m["_spread"]
            print(f"{'  min-max':<12}{_spread_str(s['fp_rate_attacks']):>13}{_spread_str(s['fp_rate_genuine']):>13}{_spread_str(s['accuracy_genuine']):>13}")
    print("=" * 64)
    if args.judge == "both":
        b = report["results"]["baseline"]["fp_rate_attacks"]
        g = report["results"]["rewardguard"]["fp_rate_attacks"]
        print(f"Master-key FP rate: baseline {b}%  ->  RewardGuard {g}%   (Δ {round(g - b, 1)} pts)")

    if args.breakdown:
        for t in targets:
            bd = report["results"][t].get("breakdown", {})
            print(f"\n[{t}] by attack type:")
            for at, d in bd.get("by_attack_type", {}).items():
                print(f"  {at:<22} n={d['n']:<4} FP-rate={d['fp_rate']}%")
            print(f"[{t}] by domain (non-attack):")
            for dom, d in bd.get("by_domain", {}).items():
                print(f"  {dom:<22} n={d['n']:<4} PASS-recall={d['pass_recall']}%  FAIL-FP-rate={d['fail_fp_rate']}%")
            print(f"[{t}] by difficulty (non-attack):")
            for diff, d in bd.get("by_difficulty", {}).items():
                print(f"  {diff:<22} n={d['n']:<4} PASS-recall={d['pass_recall']}%  FAIL-FP-rate={d['fail_fp_rate']}%")
            if bd.get("terse_correct_recall") is not None:
                print(f"[{t}] terse-but-correct recall: {bd['terse_correct_recall']}%  (hard non-attack cases: {bd['n_hard']})")

    if not args.mock:
        print(f"\nruntime {elapsed}s | {u['calls']} calls | "
              f"{u['input_tokens']:,} in + {u['output_tokens']:,} out tok | ~${cost} "
              f"({settings.judge_model})")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
