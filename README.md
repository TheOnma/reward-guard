# RewardGuard — a robustness verifier for LLM-as-a-Judge

> Your reward model is fooled by a colon. RewardGuard isn't.

RewardGuard is an **agentic verifier** that decides whether a candidate answer deserves a passing reward — and *refuses to be fooled* by the content-free "master-key" inputs that trivially game a naive LLM judge. It does this with **no fine-tuning**: a short pipeline of cheap LLM calls that decompose the reference into a rubric, check the candidate's substance against it, and run an adversarial false-positive gate.

## The user & the bottleneck

Frontier models are trained with reinforcement learning, and RL needs a **reward signal that can't be gamed**. The teams building those signals — AI labs, RL-environment engineers, eval companies — have a problem: **LLM-as-a-judge reward models are trivially fooled.** *One Token to Fool LLM-as-a-Judge* (arXiv:2507.08794) shows that feeding a judge just `":"` or `"Let's solve this step by step"` — with **no actual answer** — earns a *passing* reward 35–90% of the time across GPT-4o, Claude-4, and Qwen. In a real RLVR run the policy learned to exploit this and collapsed to sub-30-token garbage that still scored well. **When the verifier is broken, the training run is broken.**

RewardGuard defends against this at the verifier layer, as an agentic workflow rather than a trained reward model.

## How it works

Three steps, each a cheap LLM call (toggleable for ablation via `--steps`):

1. **decompose** — candidate-*blind*: from the question + trusted reference only, extract a rubric (CORE CLAIM / SUPPORTING POINTS / DISQUALIFYING ERRORS / MINIMAL PASSING ANSWER). Because it never sees the candidate, the rubric can't be bent by the answer under test.
2. **substance** — a *correctness* check, not a presence check: are the claims the candidate actually makes correct against the reference? Fails contradictions and disqualifying errors *however long or fluent*; passes terse, differently-worded, but correct answers. Fails **closed** (an unreadable verdict → FAIL).
3. **fp_gate** — the adversarial false-positive gate: reference-**grounded, not length-based**. Marks a candidate CONTENT_FREE only if it commits to no checkable answer to this question. A wrong-but-genuine answer passes this gate (correctness is step 2's job); `"O(log n)"` survives it. Fails **open** (an unreadable verdict → do *not* reject) to avoid over-rejection.

This is the self-verification + false-positive-gate pattern from the builder's prior projects (Alma Agent, Lexica), applied to reward-model robustness.

## Results

Judge = `gpt-4o-mini`. Same cases for both judges; only the pipeline changes. Full run:
**60 genuine cases** (36 hand-authored + 24 TruthfulQA) + **576 master-key attacks**, `--runs 1`.
Reproduce with `python -m evals.run_eval --judge both --breakdown` then `python -m evals.report`.
All numbers trace to `evals/results/res_4omini_*.json` / `res_35turbo_*.json`.

**Headline — same cases, both judges:**

| Metric | Baseline (naive LLM judge) | RewardGuard | Change |
|---|---|---|---|
| False-positive rate on master-key attacks | 19.1% | **1.0%** | **−18.1 pts** |
| Accuracy on genuine cases | 100.0% | 93.3% | −6.7 pts |
| FP-rate on genuine *wrong* answers (TruthfulQA + hard FAILs) | 0.0% | 0.0% | 0 |
| Terse-but-correct recall (probe: `"O(log n)"`, `"Canberra"`, …) | 100% | 100% | 0 |

**The two-tier finding (this is the story):** the false-positive gate's value scales *inversely*
with base-judge strength. `substance` alone catches most attacks on a capable judge; on a weaker,
cheaper judge it leaks and the `fp_gate` recovers the difference — and cheap judges are the norm
at RL scale.

| Config (steps) | `gpt-4o-mini` FP% attacks | `gpt-3.5-turbo` FP% attacks |
|---|---|---|
| baseline (naive judge) | 19.1% | 48.2% |
| `decompose` only | 100.0% | 100.0% |
| `+ substance` | 11.1% | 36.6% |
| `+ fp_gate` (full RewardGuard) | **1.0%** | **6.2%** |
| gate's marginal contribution | −10.1 pts | −30.4 pts |

`gpt-3.5-turbo` row is a deterministic 16-attacks/type subsample (112 attacks) for cost; FP-rate is
a rate, so it compares directly. Cost of the whole 6-run ablation: **≈ $0.78** (`gpt-4o-mini` full +
`gpt-3.5-turbo` subsampled), ~26 min wall.

## Improvement Changelog

| Stage | What & why | Evidence (`gpt-4o-mini` / `gpt-3.5-turbo`) | Decision / learning |
|---|---|---|---|
| Baseline | Naive judge: candidate framed as a *"solution process (may be incomplete)"*, quick binary "on track to the reference?" call — the leniency framing from arXiv:2507.08794 | attack-FP **19.1% / 48.2%**; genuine accuracy **100% / 96.7%** | Reproduces the master-key failure *while still scoring real answers correctly* — a fair baseline, not a strawman |
| +decompose | Candidate-blind rubric extraction (CORE CLAIM / DISQUALIFYING ERRORS / MINIMAL PASSING ANSWER) | attack-FP **100%**; genuine accuracy **50%** | Extraction only, no verdict — establishes the pipeline, catches nothing alone |
| +substance | Reference-grounded *correctness* check, fail-closed | attack-FP → **11.1% / 36.6%**; FP on genuine wrong answers **0% / 3.3%**; all 9 fluent-but-wrong hard FAILs caught | Catches wrong-*and*-fluent answers, not just empty strings. Residual leak: keyword-stuffing + bare punctuation |
| +fp_gate | Reference-grounded adversarial gate, fail-open | attack-FP → **1.0% / 6.2%**; genuine accuracy **93.3% / 91.7%**; TruthfulQA PASS-recall 100%→67% / 83%→58% | Closes the residual leak; costs ~7 pts genuine accuracy, concentrated on terse/hedged TruthfulQA "Best Answers" |
| Two-tier | Ran the full ablation on `gpt-4o-mini` *and* `gpt-3.5-turbo` | gate's marginal contribution: **−10 pts** vs **−30 pts** | **Main contribution:** the robustness gate's value rises as the base judge gets weaker/cheaper — i.e. exactly where reward models run in practice |

**Main failure mode & hot take.** A capable `substance` step subsumes most master-key defense on its
own; the dedicated `fp_gate` earns its keep as the base judge gets cheaper (−30 pts on `gpt-3.5-turbo`
vs −10 on `gpt-4o-mini`) and as cheap defense-in-depth. Its cost is **recall**, and the tell is *which*
answers it over-rejects: the hand-written terse-correct probes (`"O(log n)"`, `"Canberra"`, `"3.5"`)
survive at **100%** in every config, but short *hedged / negative* TruthfulQA answers ("Nothing
happens", "The precise origin is unclear") get rejected as content-free, dropping public PASS-recall to
**58–67%**. A pure length heuristic would be worse — it kills the terse-correct probes too — so the gate
*must* be reference-grounded; even then, robustness and recall trade off, and on a genuinely weak judge
(`gpt-3.5-turbo`) the gate still leaks ~44% of bare-punctuation attacks. RewardGuard sharply reduces the
vulnerability; it does not erase it when the underlying judge is poor.

## Quick start

```bash
cp .env.example .env          # add a key; committed numbers use JUDGE_PROVIDER=openai / JUDGE_MODEL=gpt-4o-mini
pip install -r requirements.txt

pytest tests/ -v              # mocked, no keys, no network
python -m evals.run_eval --mock           # canned behavior, no keys — see the shape

# real data prep (deterministic)
python -m rewardguard.attacks --out data/attacks.jsonl   # gold.jsonl -> 576 attacks
python -m evals.build_public                             # TruthfulQA slice -> public.jsonl

# real evaluation (needs a key) — baseline vs RewardGuard on the same cases
python -m evals.run_eval --judge both --breakdown --workers 8 --out evals/results/res_4omini_full.json

# the step ablation (one row per config)
python -m evals.run_eval --judge rewardguard --steps decompose           --breakdown --out evals/results/res_4omini_decompose.json
python -m evals.run_eval --judge rewardguard --steps decompose substance --breakdown --out evals/results/res_4omini_substance.json

python -m evals.report --files evals/results/res_4omini_*.json   # -> Markdown tables + evals/results/fp_rate.png
python -m rewardguard.server  # Judge-vs-Verifier demo at :8000  (MOCK=1 for no keys)
```

See **[DATA.md](DATA.md)** for dataset provenance and licensing, and
**[docs/REPRODUCTION.md](docs/REPRODUCTION.md)** for the full clean-environment guide
(both judge tiers, exact commands, runtime + cost).

## Architecture

```
rewardguard/
├── rewardguard/
│   ├── llm.py                 # provider-agnostic wrapper + USAGE token/cost tally
│   ├── attacks.py             # deterministic master-key generator (7 attack types)
│   ├── judges/
│   │   ├── baseline.py        # naive single-prompt judge (gets fooled)
│   │   └── verifier.py        # RewardGuard: decompose → substance → fp_gate (toggleable)
│   └── server.py              # FastAPI /judge + /verify_stream (SSE) for the demo
├── web/index.html             # Judge-vs-Verifier demo page
├── evals/
│   ├── gold.jsonl             # 36 hand-authored genuine cases (18 PASS / 18 FAIL)
│   ├── public.jsonl           # 24 TruthfulQA cases (12 PASS / 12 FAIL)
│   ├── build_public.py        # deterministic TruthfulQA normalizer
│   ├── run_eval.py            # baseline vs RewardGuard; --runs, --breakdown, cost tally
│   ├── report.py              # results JSON -> README table + bar chart (no API)
│   └── results/               # latest.json + ablation configs land here
├── data/attacks.jsonl         # 576 generated attacks
├── trajectories/              # agent + build-session traces (required deliverable)
└── tests/test_smoke.py        # mocked
```

## What existed before this hackathon (Rule 02 disclosure)

- **Built fresh this weekend:** the reward-verifier pipeline and its prompts (`judges/verifier.py`), the master-key attack harness (`attacks.py`, 7 attack types), the evaluation + ablation + cost logging (`evals/`), the TruthfulQA normalizer, and the demo.
- **Adapted from prior work:** the streaming-UI plumbing (SSE) reimplements a *pattern* from the builder's project **Lexica** (not copied); the self-verification + false-positive-gate *approach* draws on **Lexica** and **Alma Agent**.
- **Coding agent used:** Claude Code. Trajectories in `/trajectories`.

## Data & safety policy

Public or synthetic data only (hand-authored cases + TruthfulQA under Apache-2.0). No credentials or private data. RewardGuard is an offline evaluation tool that trains nothing and takes no consequential actions — a human reads the report.
