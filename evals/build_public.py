"""Normalize a small, deterministic slice of TruthfulQA into RewardGuard's eval schema.

Source: TruthfulQA (https://github.com/sylinrl/TruthfulQA), Apache-2.0.
`TruthfulQA.csv` columns: Type, Category, Question, Best Answer, Best Incorrect Answer,
Correct Answers, Incorrect Answers, Source.

Why TruthfulQA: every row ships a human-written correct answer *and* human-written
"plausible but false" answers -- exactly the hard case the substance step must handle.
We map:  reference <- Best Answer,  PASS candidate <- a *different* correct answer,
FAIL candidate <- Best Incorrect Answer.

Run:  python -m evals.build_public   (reads data/truthfulqa_slice.csv, writes evals/public.jsonl)
Deterministic: file order, <=2 rows per Category, first 12 rows that pass the length filter.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

SRC = Path("data/truthfulqa_slice.csv")
FULL = Path("data/truthfulqa_full.csv")  # optional: full download, used to (re)build the slice
OUT = Path("evals/public.jsonl")
N_ROWS = 12
MAX_PER_CATEGORY = 2


def _split(field: str) -> list[str]:
    return [s.strip() for s in field.split(";") if s.strip()]


def _passes_filter(row: dict) -> bool:
    ba, bia = row["Best Answer"].strip(), row["Best Incorrect Answer"].strip()
    if not (15 <= len(ba) <= 160 and 8 <= len(bia) <= 160):
        return False
    return any(c != ba and len(c) > 8 for c in _split(row["Correct Answers"]))


def select(rows: list[dict]) -> list[dict]:
    picked, per_cat = [], {}
    for row in rows:
        if not _passes_filter(row):
            continue
        cat = row["Category"]
        if per_cat.get(cat, 0) >= MAX_PER_CATEGORY:
            continue
        per_cat[cat] = per_cat.get(cat, 0) + 1
        picked.append(row)
        if len(picked) >= N_ROWS:
            break
    return picked


def normalize(row: dict) -> list[dict]:
    ba = row["Best Answer"].strip()
    qid = hashlib.sha1(row["Question"].encode()).hexdigest()[:8]
    src = f"TruthfulQA:{row['Category']}:{qid}"
    corrects = _split(row["Correct Answers"])
    # reference = the benchmark's full set of acceptable answers.
    reference = "; ".join([ba] + [c for c in corrects if c != ba][:3])
    # PASS candidate = the canonical Best Answer itself (guaranteed consistent with the
    # reference -- avoids label noise from TruthfulQA correct-answer lists whose entries are
    # sometimes in mild mutual tension). The "worded very differently" stress lives in
    # gold.jsonl's paraphrase-far probes instead.
    pass_cand = ba
    fail_cand = row["Best Incorrect Answer"].strip()
    base = {
        "prompt": row["Question"].strip(),
        "reference": reference,
        "category": "public",
        "domain": "public",
        "difficulty": "hard",
        "source": src,
        "tq_category": row["Category"],
    }
    return [
        {**base, "candidate": pass_cand, "gold_label": "PASS"},
        {**base, "candidate": fail_cand, "gold_label": "FAIL"},
    ]


def main() -> None:
    src = SRC if SRC.exists() else FULL
    if not src.exists():
        raise SystemExit(
            f"Neither {SRC} nor {FULL} found. Fetch TruthfulQA.csv from "
            "https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv"
        )
    rows = list(csv.DictReader(src.open()))
    picked = select(rows)

    # Vendor a lean, license-compliant copy of exactly the rows we use.
    with SRC.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(picked)

    records = [r for row in picked for r in normalize(row)]
    with OUT.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    print(f"Selected {len(picked)} TruthfulQA rows -> {len(records)} examples -> {OUT}")
    print(f"Vendored source rows -> {SRC}")


if __name__ == "__main__":
    main()
