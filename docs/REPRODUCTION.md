# Reproduction guide

Written for someone starting from a clean environment. Everything here is deterministic or explicitly seeded; public/synthetic data only (see [../DATA.md](../DATA.md)).

## 0. Requirements

- Python 3.11+
- An API key for the judge model. The committed numbers use **OpenAI** `gpt-4o-mini`
  (primary) and `gpt-3.5-turbo` (cheap tier); any Anthropic or OpenAI chat model works.
- No GPU. No fine-tuning. RewardGuard is prompt-orchestration only.

## 1. Setup

```bash
git clone <repo> && cd rewardguard
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # set JUDGE_PROVIDER=openai and JUDGE_MODEL=gpt-4o-mini, add OPENAI_API_KEY
```

> If your machine's DNS can't resolve `api.openai.com` / `files.pythonhosted.org` (e.g. some
> phone hotspots), set `DNS_OVERRIDE=api.openai.com=<ip>` in `.env` — opt-in, no-op otherwise.

## 2. Sanity check (no keys, no network)

```bash
pytest tests/ -v                 # mocked unit tests
python -m evals.run_eval --mock  # canned behavior, prints the comparison table shape
```

Expected: 5 tests pass; the mock table shows baseline ≈ 99% FP on attacks and RewardGuard
≈ 27% (illustrative — the mock verifier is a crude length/opener heuristic, not the real
prompts; it writes `evals/results/mock.json`, never the committed real results).

## 3. Build the data (deterministic)

```bash
python -m rewardguard.attacks --out data/attacks.jsonl   # 36 gold cases -> 576 attacks (7 types)
python -m evals.build_public                             # TruthfulQA slice -> evals/public.jsonl (24)
```

Both are fully deterministic (no randomness, no network for `attacks.py`). `evals/public.jsonl`
and the 12-row `data/truthfulqa_slice.csv` it derives from are committed; `data/attacks.jsonl`
is generated (gitignored) — run the first command once. A reviewer can skip `build_public`.

## 4. Primary judge: baseline vs RewardGuard + the step ablation

Same cases every time; the only variable is the pipeline. Primary judge is `gpt-4o-mini`
(all 636 cases: 60 genuine + 576 attacks).

```bash
# baseline + full RewardGuard, with per-domain / per-attack breakdown
python -m evals.run_eval --judge both --steps decompose substance fp_gate \
    --breakdown --workers 8 --out evals/results/res_4omini_full.json

# step ablation: one config per file
python -m evals.run_eval --judge rewardguard --steps decompose \
    --breakdown --workers 8 --out evals/results/res_4omini_decompose.json
python -m evals.run_eval --judge rewardguard --steps decompose substance \
    --breakdown --workers 8 --out evals/results/res_4omini_substance.json
```

Runtime ≈ 21 min, cost ≈ **$0.43** (`usage.est_cost_usd` in each JSON).

## 5. Cheap tier (the two-tier finding)

Repeat on `gpt-3.5-turbo`. `--sample-attacks 16` keeps 16 attacks per type (112 total, still
all 7 types) so the weaker/pricier model stays cheap; FP-rate is a rate, so it compares directly.

```bash
JUDGE_MODEL=gpt-3.5-turbo python -m evals.run_eval --judge both \
  --steps decompose substance fp_gate --breakdown --workers 8 --sample-attacks 16 \
  --out evals/results/res_35turbo_full.json
JUDGE_MODEL=gpt-3.5-turbo python -m evals.run_eval --judge rewardguard \
  --steps decompose --breakdown --workers 8 --sample-attacks 16 \
  --out evals/results/res_35turbo_decompose.json
JUDGE_MODEL=gpt-3.5-turbo python -m evals.run_eval --judge rewardguard \
  --steps decompose substance --breakdown --workers 8 --sample-attacks 16 \
  --out evals/results/res_35turbo_substance.json
```

Runtime ≈ 6 min, cost ≈ **$0.35**.

## 6. Build the tables + chart (no API)

```bash
python -m evals.report --files evals/results/res_4omini_*.json    # primary headline + ablation + chart
python -m evals.report --files evals/results/res_35turbo_*.json   # cheap-tier ablation
```

## 7. The demo

```bash
MOCK=1 python -m rewardguard.server                       # http://localhost:8000, no keys (canned trace)
JUDGE_MODEL=gpt-3.5-turbo python -m rewardguard.server    # live: the cheap-judge tier, reliably fooled
python -m rewardguard.server                              # live on whatever JUDGE_MODEL is set
```

The page defaults to an opener candidate (`"Let's solve this problem step by step."`). On
`gpt-3.5-turbo` the baseline rewards it every time (opener FP = 100%) and RewardGuard rejects
it — the intended contrast. On `gpt-4o-mini` the baseline resists master keys on most
questions (opener FP ≈ 31% in aggregate, noisy per call), so the split is less reliable live.

## Expected output & cost

- Each result JSON carries `usage` (calls, input/output tokens, `est_cost_usd`) and `runtime_sec`.
- RewardGuard makes up to 3 calls per judgment vs the baseline's 1 — budget accordingly.
- **Whole 6-run ablation (both tiers): ≈ $0.78, ≈ 26 min** at `gpt-4o-mini` + `gpt-3.5-turbo`.
- Headline (primary judge `gpt-4o-mini`): master-key attack-FP **19.1% → 1.0%**; genuine
  accuracy 100% → 93.3%; terse-but-correct recall 100% → 100%.
- Determinism: `temperature=0` + fixed `seed` are set where the SDK/model accept them (OpenAI
  chat models do; current Anthropic models drop the sampling params). Where they aren't
  available, stabilize by reporting the mean over `--runs N` with the min–max spread.

## Notes

- Baseline and advanced always run on the **same cases** — the only variable is the judging pipeline.
- Every reported number traces to a committed file under `evals/results/`.
- If TruthfulQA can't be fetched in your environment, see DATA.md §5 for the synthetic fallback.
