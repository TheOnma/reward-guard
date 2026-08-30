"""Run baseline vs RewardGuard on the SAME cases and report false-positive rate + agreement.

Usage:
  python -m evals.run_eval --mock                 # no keys, canned behavior (see the shape)
  python -m evals.run_eval                        # real LLM (needs a key in .env)
  python -m evals.run_eval --judge baseline       # only the baseline
  python -m evals.run_eval --steps decompose substance   # ablate RewardGuard steps
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rewardguard.attacks import build_attacks, load_gold
from rewardguard.judges import baseline_judge, reward_guard_verify


def load_cases(gold_path: str, attacks_path: str | None) -> list[dict]:
    gold = load_gold(gold_path)
    cases = [{**g, "category": g.get("category", "genuine")} for g in gold]
    if attacks_path and Path(attacks_path).exists():
        attacks = [json.loads(l) for l in Path(attacks_path).read_text().splitlines() if l.strip()]
    else:
        attacks = build_attacks(gold)  # generate on the fly if not written to disk
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
    genuine = [r for r in rows if r["category"] == "genuine"]
    return {
        "fp_rate_attacks": rate(attacks),
        "fp_rate_genuine": rate(genuine),
        "accuracy_genuine": acc(genuine),
        "accuracy_overall": acc(rows),
        "n_attacks": len(attacks),
        "n_genuine": len(genuine),
    }


def evaluate(cases, which: str, *, mock: bool, steps) -> list[dict]:
    rows = []
    for c in cases:
        if which == "baseline":
            pred = baseline_judge(c["prompt"], c["reference"], c["candidate"], mock=mock)
        else:
            pred = reward_guard_verify(c["prompt"], c["reference"], c["candidate"], steps=tuple(steps), mock=mock).label
        rows.append({"gold_label": c["gold_label"], "pred": pred, "category": c["category"]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--attacks", default="data/attacks.jsonl")
    ap.add_argument("--judge", choices=["baseline", "rewardguard", "both"], default="both")
    ap.add_argument("--steps", nargs="+", default=["decompose", "substance", "fp_gate"])
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--out", default="evals/results/latest.json")
    args = ap.parse_args()

    cases = load_cases(args.gold, args.attacks)
    report = {"n_cases": len(cases), "mock": args.mock, "steps": args.steps, "results": {}}

    targets = ["baseline", "rewardguard"] if args.judge == "both" else [args.judge]
    for t in targets:
        rows = evaluate(cases, t, mock=args.mock, steps=args.steps)
        report["results"][t] = metrics(rows)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))

    print(f"\nRewardGuard evaluation  (cases={len(cases)}, mock={args.mock})")
    print("=" * 64)
    hdr = f"{'judge':<12}{'FP% attacks':>13}{'FP% genuine':>13}{'acc genuine':>13}"
    print(hdr)
    print("-" * 64)
    for t in targets:
        m = report["results"][t]
        print(f"{t:<12}{m['fp_rate_attacks']:>12}%{m['fp_rate_genuine']:>12}%{m['accuracy_genuine']:>12}%")
    print("=" * 64)
    if args.judge == "both":
        b = report["results"]["baseline"]["fp_rate_attacks"]
        g = report["results"]["rewardguard"]["fp_rate_attacks"]
        print(f"Master-key FP rate: baseline {b}%  ->  RewardGuard {g}%   (Δ {round(g - b, 1)} pts)")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
