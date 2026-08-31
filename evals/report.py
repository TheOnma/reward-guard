"""Turn eval result JSON into a README-ready table + a bar chart. No API calls.

Reads result files written by run_eval.py (default: everything in evals/results/*.json),
prints Markdown tables you can paste into the README, and — if matplotlib is available —
saves a baseline-vs-RewardGuard bar chart to evals/results/fp_rate.png.

Usage:
  python -m evals.report                          # read evals/results/*.json
  python -m evals.report --results evals/results  # explicit dir
  python -m evals.report --files a.json b.json     # explicit files (e.g. ablation configs)
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path


def _load(files: list[str]) -> list[dict]:
    out = []
    for f in files:
        try:
            d = json.loads(Path(f).read_text())
            d["_file"] = f
            out.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"! skip {f}: {e}")
    return out


def _steps_label(steps) -> str:
    if not steps:
        return "baseline"
    return "+".join(steps)


def _get(res: dict, judge: str, key: str):
    j = res.get("results", {}).get(judge)
    return None if not j else j.get(key)


def headline_table(reports: list[dict]) -> str:
    """Baseline vs RewardGuard from the most complete report (both judges present)."""
    cand = [r for r in reports if "baseline" in r.get("results", {}) and "rewardguard" in r.get("results", {})]
    if not cand:
        return "_(no report contains both baseline and rewardguard — run `--judge both`)_"
    # prefer the full-pipeline run (all three steps)
    cand.sort(key=lambda r: len(r.get("steps", [])), reverse=True)
    r = cand[0]
    rows = [
        ("False-positive rate on master-key attacks", "fp_rate_attacks", True),
        ("FP-rate on genuine wrong answers", "fp_rate_genuine", True),
        ("Accuracy on genuine cases", "accuracy_genuine", False),
    ]
    out = [f"**Model:** `{r.get('model','?')}`  ·  **cases:** {r.get('n_cases','?')}  ·  **runs:** {r.get('runs','?')}",
           "", "| Metric | Baseline | RewardGuard | Δ |", "|---|---|---|---|"]
    for label, key, lower_better in rows:
        b, g = _get(r, "baseline", key), _get(r, "rewardguard", key)
        if b is None or g is None:
            continue
        delta = round(g - b, 1)
        arrow = "↓" if (lower_better and delta < 0) or (not lower_better and delta > 0) else ""
        out.append(f"| {label} | {b}% | {g}% | {delta:+} {arrow} |")
    return "\n".join(out)


def ablation_table(reports: list[dict]) -> str:
    """RewardGuard attack-FP-rate across step configs (one row per config found)."""
    rows = []
    for r in reports:
        fp_rg = _get(r, "rewardguard", "fp_rate_attacks")
        fp_base = _get(r, "baseline", "fp_rate_attacks")
        label = _steps_label(r.get("steps"))
        if fp_rg is not None:
            rows.append((label, r.get("model", "?"), fp_base, fp_rg))
    if not rows:
        return ""
    rows.sort(key=lambda t: len(t[0]))
    out = ["| Config (steps) | Model | Baseline FP% attacks | RewardGuard FP% attacks |",
           "|---|---|---|---|"]
    for label, model, fp_base, fp_rg in rows:
        out.append(f"| {label} | `{model}` | {fp_base if fp_base is not None else '—'}% | {fp_rg}% |")
    return "\n".join(out)


def cost_summary(reports: list[dict]) -> str:
    out = ["| File | Model | calls | ~cost (USD) | runtime (s) |", "|---|---|---|---|---|"]
    any_row = False
    for r in reports:
        u = r.get("usage")
        if not u:
            continue
        any_row = True
        out.append(f"| `{Path(r['_file']).name}` | `{r.get('model','?')}` | {u.get('calls','?')} | "
                   f"${u.get('est_cost_usd','?')} | {r.get('runtime_sec','?')} |")
    return "\n".join(out) if any_row else ""


def bar_chart(reports: list[dict], out_png: str) -> str | None:
    cand = [r for r in reports if "baseline" in r.get("results", {}) and "rewardguard" in r.get("results", {})]
    if not cand:
        return None
    cand.sort(key=lambda r: len(r.get("steps", [])), reverse=True)
    r = cand[0]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    metrics = ["fp_rate_attacks", "fp_rate_genuine", "accuracy_genuine"]
    labels = ["FP% attacks", "FP% wrong", "Acc. genuine"]
    base = [_get(r, "baseline", m) or 0 for m in metrics]
    rg = [_get(r, "rewardguard", m) or 0 for m in metrics]
    x = range(len(metrics))
    w = 0.38
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar([i - w / 2 for i in x], base, w, label="Baseline", color="#c8362f")
    ax.bar([i + w / 2 for i in x], rg, w, label="RewardGuard", color="#1f8a4c")
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_ylabel("%"); ax.set_ylim(0, 100)
    ax.set_title(f"Baseline vs RewardGuard  ({r.get('model','?')})")
    ax.legend(); ax.grid(axis="y", alpha=0.25)
    for i, (b, g) in enumerate(zip(base, rg)):
        ax.text(i - w / 2, b + 1, f"{b}", ha="center", fontsize=8)
        ax.text(i + w / 2, g + 1, f"{g}", ha="center", fontsize=8)
    fig.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150)
    return out_png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="evals/results", help="dir of result JSONs")
    ap.add_argument("--files", nargs="*", help="explicit result files (overrides --results)")
    ap.add_argument("--png", default="evals/results/fp_rate.png")
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(str(Path(args.results) / "*.json")))
    if not files:
        print(f"No result JSONs found in {args.results}. Run an eval first.")
        return
    reports = _load(files)

    print("\n## Headline\n")
    print(headline_table(reports))
    abl = ablation_table(reports)
    if abl:
        print("\n## Ablation (RewardGuard attack-FP by config)\n")
        print(abl)
    cost = cost_summary(reports)
    if cost:
        print("\n## Cost / runtime\n")
        print(cost)
    png = bar_chart(reports, args.png)
    print(f"\nChart: {png}" if png else "\n(no chart — install matplotlib for the bar chart)")


if __name__ == "__main__":
    main()
