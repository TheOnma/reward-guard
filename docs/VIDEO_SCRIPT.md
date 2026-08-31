# RewardGuard — 5-minute solution video script

Target: ≤5:00. Structure follows the micro1 brief: problem + baseline → one realistic execution → final comparison → changelog walk → the change that mattered most → one experiment removed. Record the demo page live; screen-record the terminal for the eval. Numbers below are the real measured results (judge = gpt-4o-mini unless noted; weak judge = gpt-3.5-turbo).

Timings are targets. `[SCREEN]` = what's shown, `[VO]` = what you say.

---

## 0:00–0:35 · The problem (hook first)

`[SCREEN]` The demo page (`web/index.html`), candidate box containing a single `:`.
`[VO]` "Frontier models are trained with reinforcement learning, and RL needs a reward signal that can't be gamed. The reward models we use are LLM judges — and they're trivially fooled. Watch." Click **Run**. `[SCREEN]` Baseline panel flips to **PASS (fooled)** in red.
`[VO]` "A colon. No answer at all, and the reward model passed it. A published paper — *One Token to Fool LLM-as-a-Judge* — shows this happens up to 35 to 90 percent of the time depending on the judge, and in a real training run the policy learned to exploit it and collapsed. When the verifier breaks, the training run breaks."

## 0:35–1:00 · Who has this problem

`[VO]` "Whoever builds the reward signal — AI labs, RL-environment engineers, eval companies. The bottleneck is verification: only a reliable judge separates a correct answer from a plausible-looking wrong one. That's what RewardGuard fixes — at the verifier layer, as an agentic workflow, with no fine-tuning."

## 1:00–1:45 · The solution, shown live

`[SCREEN]` Same page; the RewardGuard panel now streaming its steps.
`[VO]` "RewardGuard is three cheap LLM calls. **Decompose** reads only the question and the trusted reference — never the candidate — and extracts a rubric, so the answer under test can't bend it. **Substance** is a correctness check, not a text-presence check: is what the candidate actually claims right? **The false-positive gate** is reference-grounded, not length-based — it rejects answers that commit to nothing." `[SCREEN]` RewardGuard lands on **REJECT** with the streamed trace visible.
`[VO]` "Same colon — caught, with the reason."

`[SCREEN]` Type a real correct answer, Run. Both agree PASS. Then type a fluent *wrong* answer.
`[VO]` "And it's not just rejecting empty strings — here's a long, confident, wrong answer." `[SCREEN]` Baseline PASS, RewardGuard REJECT.
`[VO]` "The baseline is fooled by fluency. RewardGuard checks correctness against the reference."

## 1:45–2:45 · One realistic execution, end to end

`[SCREEN]` Terminal: `python -m evals.run_eval --runs 1 --breakdown`.
`[VO]` "Here's the real evaluation. Same cases for both judges: 36 hand-written pass/fail cases across two domains, 24 TruthfulQA cases — human-written truths and human-written plausible falsehoods — and 576 deterministic master-key attacks in seven flavors, from a bare colon to long reasoning-shaped filler that never commits to an answer."
`[SCREEN]` The comparison table; point at the FP-rate row.
`[VO]` "On gpt-4o-mini the baseline's false-positive rate on attacks is 19 percent. RewardGuard drops it to 1 percent. And it keeps the answers that matter" — `[SCREEN]` point at genuine slice — "recall on genuine correct answers stays at 93 percent, wrong answers are still caught, and the terse-but-correct probe — a bare `O(log n)` — is kept, not rejected, at 100 percent."

## 2:45–3:45 · The comparison + the change that mattered most

`[SCREEN]` The two-tier table / `fp_rate` chart from `report.py`.
`[VO]` "Now the finding. I ran the ablation on two judges — a stronger cheap model, gpt-4o-mini, and a weaker one, gpt-3.5-turbo — and watched what each pipeline step buys."
`[SCREEN]` Point across the rows.
`[VO]` "Decompose alone judges nothing — it just builds the rubric. Substance does most of the work. But the false-positive gate is decisive, and here's the key: on the stronger judge it removes another 10 points of attack-FP; on the weaker judge, 30. The weaker and cheaper the base judge, the more the gate earns its keep."
`[VO]` "That's the whole point, because at RL scale you can't afford a frontier model as your reward judge on millions of rollouts — cheap judges are the norm. So the robustness gate matters most exactly where it'll actually be deployed. The change that mattered most wasn't one component — it was testing across judge tiers, which is what revealed that."

## 3:45–4:25 · The hot take (measured) + what it costs

`[VO]` "This isn't free, and I measured the cost. The gate's price is recall — and *which* answers it drops is the tell. My hand-written terse-correct probes survive at 100 percent in every config. But short hedged or negative TruthfulQA answers — 'Nothing happens', 'the origin is unclear' — get rejected as content-free, so public-set recall falls to the high 50s, low 60s. A pure length heuristic would be worse: it would kill the terse-correct probes too. And on a genuinely weak judge, the gate still leaks about 44 percent of bare-punctuation attacks. RewardGuard sharply reduces the vulnerability — it doesn't erase it. That honesty is the lesson: robustness and recall trade off, and a reference-grounded gate buys the best of that trade, not a free lunch."

## 4:25–4:45 · One experiment I removed

`[VO]` "One thing I cut: my first TruthfulQA build used a *different* correct answer as the passing candidate. It introduced label noise — some correct-answer lists hold entries in mild tension, so a valid answer read as contradicting the reference. I switched to the canonical Best Answer and moved the 'worded differently but correct' stress into dedicated paraphrase probes. A verifier eval is only as clean as its labels."

## 4:45–5:00 · Reproducibility + close

`[SCREEN]` Terminal: `pytest`, `python -m evals.run_eval --mock`, then `python -m evals.report`.
`[VO]` "Everything reproduces from a clean environment: mocked tests with no keys, deterministic attacks, public and synthetic data documented in DATA.md, cost logged per run — the whole two-tier ablation cost under a dollar. Baseline and advanced share the same cases, every number traces to a committed results file. RewardGuard: a reward model that isn't fooled by a colon — and an honest map of when the extra robustness is worth paying for. Thanks for watching."

---

### Shot list / prep
- Pre-load the demo page and rehearse the three candidates (colon → correct → fluent-wrong). **Smoke-test it first with the new provider/baseline.**
- Have `results/*.json` and the `report.py` chart ready before recording — do NOT run the paid eval live.
- Keep the terminal font large; trim long waits in the edit.
- All numbers above are the measured results; double-check them against your final committed `results/` before recording.
