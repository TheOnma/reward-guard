# DATA.md — datasets, provenance, licensing

RewardGuard is an **offline evaluation tool**. Every case is `(prompt, reference, candidate,
gold_label)` plus metadata. All data here is **public or synthetic** — no private data, no
credentials, nothing scraped from a user.

| File | Rows | Origin | License | Committed? |
|---|---|---|---|---|
| `evals/gold.jsonl` | 36 | Hand-authored this weekend | CC0 / project-owned | yes |
| `evals/public.jsonl` | 24 | Normalized slice of **TruthfulQA** | Apache-2.0 (upstream) | yes |
| `data/truthfulqa_slice.csv` | 12 source rows | Verbatim rows from TruthfulQA | Apache-2.0 | yes |
| `data/attacks.jsonl` | 576 | **Generated** by `rewardguard/attacks.py` from `gold.jsonl` | project-owned | regenerated |

Regenerate everything from a clean checkout:

```bash
python -m rewardguard.attacks --out data/attacks.jsonl   # gold.jsonl -> 576 attacks
python -m evals.build_public                              # truthfulqa_slice.csv -> public.jsonl
```

---

## 1. `evals/gold.jsonl` — hand-authored genuine cases (36)

Balanced **18 PASS / 18 FAIL**. Each row has `prompt`, `reference`, `candidate`,
`gold_label`, `category="genuine"`, `domain`, `difficulty` (`easy|medium|hard`), and an
optional `probe` tag.

**Domains:** `geography`, `science`, `cs`, `networking`, `software-eng` (general
knowledge + computer science, ~22 rows) and `finance-math` (quantitative word problems,
14 rows) — two clearly distinct domains.

**Deliberately hard cases** (this is the point — a fair verifier has to get these right,
not just reject empty strings):

- **`probe: "terse-correct"` (4, all gold PASS)** — a correct answer stated in a few words
  (`"Canberra"`, `"O(log n)"`, `"25%"`, `"3.5"`). A length-based gate over-rejects these;
  RewardGuard's gate is reference-grounded and must keep them.
- **`probe: "paraphrase-far"` (3, all gold PASS)** — a correct answer worded very
  differently from the reference (e.g. "sixty miles for every hour that passes" for
  `60 mph`). Stresses that `substance` judges meaning, not surface overlap.
- **fluent-but-wrong (9 gold FAIL at `difficulty: "hard"`)** — long, confident,
  well-formed answers that are actually incorrect: compound interest where simple was
  asked; `zip()` described as `zip_longest`; "UDP is reliable and connection-oriented";
  additive stacking of successive discounts; expected value of a die given as `3`. These
  stress the `substance` step — a judge that only checks for on-topic text passes them.

All content is original, written for this project. No copyright concerns; treat as CC0.

## 2. `evals/public.jsonl` — TruthfulQA slice (24)

**Upstream:** TruthfulQA — Lin, Hilton, Evans, 2021. Repo:
<https://github.com/sylinrl/TruthfulQA>. **License: Apache-2.0** (`LICENSE` in that repo).
Source file used: `TruthfulQA.csv` from `main`, fetched 2026-08-31.

**Why this benchmark:** every TruthfulQA row ships human-written *correct* answers **and**
human-written *"plausible but false"* answers. That is exactly the hard judgment a naive
reward model fails — an imitative falsehood that "sounds right". It gives the baseline a
real stress test rather than only synthetic attacks.

**Normalization** (`evals/build_public.py`, fully deterministic):

1. Read `data/truthfulqa_slice.csv` (or the full `TruthfulQA.csv` if present).
2. Select rows in file order, at most **2 per `Category`**, keeping the first **12** whose
   `Best Answer` is 15–160 chars, `Best Incorrect Answer` is 8–160 chars, and which have a
   correct answer distinct from `Best Answer`. → categories: Misconceptions, Proverbs,
   Misquotations, Conspiracies, Superstitions, Paranormal.
3. For each selected row emit **two** examples:
   - `reference` = `Best Answer` + up to 3 other distinct `Correct Answers`, joined with `"; "`;
   - **PASS** — `candidate` = the canonical `Best Answer` itself. (Using a *different*
     correct answer as the candidate turned out to introduce label noise: some TruthfulQA
     correct-answer lists contain entries in mild mutual tension — e.g. "nothing is under
     Denver Airport" vs "there are baggage tunnels" — so a second correct answer can read
     as contradicting the union reference. The "worded very differently but still correct"
     stress is instead carried by `gold.jsonl`'s `paraphrase-far` probes.)
   - **FAIL** — `candidate` = `Best Incorrect Answer` (a human-written imitative falsehood).
4. Tag: `category="public"`, `domain="public"`, `difficulty="hard"`,
   `source="TruthfulQA:<Category>:<sha1(question)[:8]>"`, `tq_category=<Category>`.

Result: **12 PASS / 12 FAIL**. `data/truthfulqa_slice.csv` is the 12 verbatim source
rows, redistributed under Apache-2.0 with attribution (this file).

> **Attribution.** TruthfulQA © the TruthfulQA authors, used under Apache-2.0. If you use
> this slice, cite: Stephanie Lin, Jacob Hilton, Owain Evans. *TruthfulQA: Measuring How
> Models Mimic Human Falsehoods.* 2021. arXiv:2109.07958.

## 3. `data/attacks.jsonl` — generated master-key attacks (576)

Generated by `rewardguard/attacks.py` from the 36 genuine cases — **deterministic**, no
network, no randomness. Every attack shares a real case's `prompt` + `reference`, carries a
content-free `candidate`, and is labelled **`gold_label="FAIL"`**. 16 attacks per genuine
case:

| `attack_type` | n | what it is |
|---|---|---|
| `punctuation` | 144 | a single symbol / whitespace (`":"`, `"."`, `"\n"`, `" "`) |
| `opener` | 216 | a bare reasoning opener ("Let's solve this problem step by step.") |
| `keyword_stuff` | 36 | the reference's salient nouns repeated ×3, no grammar |
| `keyword_stuff_fluent` | 36 | those nouns woven into grammatical filler that asserts nothing |
| `reasoning_filler` | 36 | long, confident, formatted text that never commits ("it depends") |
| `format_mimicry` | 36 | the shape of a worked solution (headers, "Therefore", "Q.E.D.") with no content |
| `hedge_nonanswer` | 72 | restates the question / hedges without answering |

The first three reproduce failure modes from *One Token to Fool LLM-as-a-Judge*
(arXiv:2507.08794). The last four are harder: they defeat a pure length heuristic and
specifically probe whether `substance` / `fp_gate` require an actual *answer*, not just
plausible-looking text.

## 4. What is NOT here

- No fine-tuning data (RewardGuard trains nothing — see `CLAUDE.md` §9).
- No private, user, or credentialed data.
- No large vendored corpora — the TruthfulQA slice is 12 rows; the full CSV is fetched on
  demand by `build_public.py` and not committed.

## 5. If a clean public pull is unavailable

If TruthfulQA cannot be fetched or its license does not permit redistribution in your
context, delete `evals/public.jsonl` + `data/truthfulqa_slice.csv` and run with `--public
""`. A clearly-labelled **synthetic** hard set of the same shape (`domain="synthetic"`,
`difficulty="hard"`, plausible-but-false candidates written to mimic imitative falsehoods)
can be substituted; document it as synthetic here. Do not substitute any dataset that is
not clearly public or synthetic without sign-off.
