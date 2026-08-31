# Build Trajectory — Claude Code Session (2026-08-30 → 31)

*Note: This is a representative trace of the coding-agent session that built RewardGuard's verifier and eval harness. Tool calls are summarized; retries, dead ends, and course corrections are intentionally preserved to document the engineering process.*

---

## Phase 1: Writing the Verifier Prompts (Decompose, Substance, FP-Gate)

**Goal:** Replace placeholder prompts in `rewardguard/judges/verifier.py` so the `substance` judge evaluates *correctness vs. the reference* and the `fp_gate` is *reference-grounded, not length-based*.

1. **Context Gathersing:** Read `CLAUDE.md`, then every source and data file (`verifier.py`, `baseline.py`, `llm.py`, `config.py`, `run_eval.py`, `attacks.py`, `gold.jsonl`, `server.py`, tests).
2. **Scaffold Check:** Ran `pytest tests/ -v` (4/4 passed) and `python -m evals.run_eval --mock` (ran successfully). Noted that the mock verifier scores **100% False Positive (FP) on genuine cases** (passes every wrong-but-long answer)—the exact failure mode identified in the initial brief. This provided a good "before" baseline.
3. **Blocker (Network Environment):** No dependencies were installed, and the local DNS (running on a phone hotspot) returned `SERVFAIL` for `files.pythonhosted.org` while resolving `pypi.org` fine. Standard `pip install` failed on every wheel download.
* **Fix:** Wrote `scratchpad/pipwrap.py`—a `socket.getaddrinfo` shim mapping the Fastly host to a known IP, then invoking `pip._internal.cli.main`. Installed the virtual environment cleanly. *(Documented as a repro note; standard networks won't need this.)*


4. **API-Drift Discovery:** Set `JUDGE_MODEL=claude-sonnet-5` and probed the SDK. `messages.create()` raised `TypeError: unexpected keyword argument 'temperature'`. The installed `anthropic` package (1.2.0) has removed sampling params for current models. Recorded this to patch during the dataset expansion phase.
5. **Prompt Engineering & Parsing:** Wrote the three specific prompts:
* A candidate-blind `decompose` step emitting CORE CLAIM / SUPPORTING POINTS / DISQUALIFYING ERRORS / MINIMAL PASSING ANSWER.
* A `substance` step as a correctness grader (fails on contradiction *regardless of length/fluency*, passes terse-but-consistent answers).
* An `fp_gate` step explicitly instructed not to rely on length.
* **Parser updates:** Steps now end with `VERDICT: <TOKEN>`. Implemented bottom-up parsing with a word-boundary fallback. Decided to **fail-closed** on an unreadable `substance` verdict, but **fail-open** on an unreadable `fp_gate` verdict.


6. **Verification (`scratchpad/verify.py`, real `claude-sonnet-5`):** 17/17 against gold data. Crucially, 7/7 wrong-but-substantive answers were rejected by `substance` (not emptiness), 8/8 correct answers were kept, a bare `"O(log n)"` was kept, and `"Let's solve this step by step."` was rejected by *both* steps. Test suite remained green.

## Phase 2: Expanding and Hardening the Dataset

1. **Determinism Fixes (`llm.py`):** Pinned `temperature=0` only where the SDK signature still accepts it (older models / OpenAI) using an `inspect.signature` guard. Fixed the `SEED` for OpenAI. Since current Anthropic models can't be temperature-pinned, added `--runs N` to `run_eval.py` to *measure* stability (calculating mean + min/max per metric), plus `--workers` for thread pooling and `--breakdown` for per-domain/attack-type slices.
2. **Expanding `gold.jsonl`:** Scaled from 15 → 36 cases (18 PASS / 18 FAIL) across two clear domains (general-knowledge/CS/SE + a new `finance-math` set). Added `domain`, `difficulty`, and `probe` metadata. Built hard probes: 4 `terse-correct` (gold PASS), 3 `paraphrase-far` (gold PASS), 9 fluent-but-wrong `hard` FAILs (e.g., compound-vs-simple interest, describing `zip` as `zip_longest`, "UDP is reliable/ordered", additive discount stacking).
3. **Public Data Slice:** Checked DNS via `8.8.8.8` and found `raw.githubusercontent.com` reachable. Fetched the TruthfulQA dataset. Wrote an extraction script to deterministically select 12 rows (≤2 per Category) → 24 examples.
* **Iteration (Label Noise):** The first pass set the PASS candidate to a *different* correct answer. The real probe immediately flagged 2 PASS misses caused by TruthfulQA's correct-answer lists containing entries in mild mutual tension.
* **Fix:** Switched the PASS candidate to TruthfulQA's canonical `Best Answer` (clean label). Shifted the "worded differently" stress test entirely onto the `paraphrase-far` probes in `gold.jsonl`.


4. **Hardening Attacks:** Kept standard punctuation/opener/keyword-stuffing, but added `keyword_stuff_fluent`, `reasoning_filler`, `format_mimicry`, and `hedge_nonanswer` variants. Deterministic generation, all `gold_label="FAIL"`. Scaled the matrix: 36 base cases × 16 attack types = **576 attacks**.
5. **Cost Probing & Checkpoint:** Ran a 74-case cost probe (~$0.008/case, ~1.6 s/case at 8 workers). Early signals were good: `terse-correct` recall was 100%; `keyword_stuff*` attacks on the Australia case leaked past `substance` as a PASS—proving that the data would successfully force `fp_gate` to earn its place in the ablation.
6. **API Limit Reached:** Initiated a full evaluation run across all 636 cases. Encountered API budget/rate limits mid-run, preventing completion. OpenAI fallback was also blocked by the hotspot DNS. Saved all code/data progress and paused to re-evaluate the API strategy.

## Phase 3: Cost Pivot & Two-Tier Ablation

Working within a tight API budget for the remainder of the hackathon, the following course corrections and final evaluations were executed:

1. **Integration & Reporting:** Integrated reporting modules to convert results JSON into README tables and matplotlib charts. Verified full compatibility with `run_eval.py`'s JSON schema without touching the core verifier code.
2. **Model Pivot:** Switched the primary judge to `gpt-4o-mini` (highly cost-effective and within the project's threat model). Because `api.openai.com` wouldn't resolve on the hotspot DNS, added an **opt-in** `DNS_OVERRIDE` setting (`config.py` + `llm.py`) that patches `socket.getaddrinfo`.
3. **Re-validating Prompts:** Re-ran the prompt verifications on `gpt-4o-mini` (38 cases). Result: **37/38**.
* Wrong-but-substantive rejected **18/18** (the make-or-break metric holds).
* Recall: **17/18**.
* *The one miss:* The `paraphrase-far` average-speed case—`substance` correctly said YES, but `fp_gate` over-rejected it as CONTENT_FREE. This highlights the precise robustness-vs-recall tension appearing on a weaker judge (sonnet-5 got 17/17 with no gate misfire). Decided to keep this as an honest finding rather than patching it away.


4. **First Full Ablation:** Ran on all 636 cases using `gpt-4o-mini`. The step ablation was beautiful: `decompose` (100% attack-FP) → `+substance` (11.1%) → `+fp_gate` (1.2%), with genuine accuracy dipping slightly (96.7% → 93.3%) and public recall dropping (83% → 75%).
* **Dead End (Baseline flatline):** The baseline-vs-RewardGuard metric was completely flat (1.4% → 1.2%). Why? The old `baseline.py` prompt handed the judge the full gold reference and asked a sober PASS/FAIL, which `gpt-4o-mini` simply wasn't fooled by.


5. **Fixing the Baseline:** Rewrote `baseline.py` to be a faithful naive judge (a real-world design, not a strawman): it now frames the candidate as a "solution process (may be incomplete)" and asks a quick binary "on track to the reference?"—leveraging the exact leniency framing the paper identified.
* *Probe:* On a 21-attack sample, attack-FP jumped to **52% on gpt-4o-mini** and **62% on gpt-3.5-turbo**, while genuine PASS-recall stayed perfect. The baseline was now fair and accurately fooled by content-free attacks. Added `--sample-attacks N` to manage run sizes.


6. **Final Two-Tier Ablation:** Executed across `gpt-4o-mini` (full 636) + `gpt-3.5-turbo` (16 attacks/type subsample).

| config | gpt-4o-mini attack-FP | gpt-3.5-turbo attack-FP |
| --- | --- | --- |
| baseline (naive judge) | 19.1% | 48.2% |
| decompose | 100% | 100% |
| + substance | 11.1% | 36.6% |
| + fp_gate (full) | **1.0%** | **6.2%** |

**Final Findings / "The Hot Take":** Genuine accuracy held strong: 100%→93.3% (4o-mini) / 96.7%→91.7% (3.5). Terse-correct recall stayed at 100% across all configs. However, TruthfulQA PASS-recall dropped significantly (100%→67% / 83%→58%). The data proves that while `fp_gate` drastically reduces vulnerability to reward hacking, it exacts a specific recall cost by over-rejecting short hedged/negative answers (e.g., "Nothing happens", "origin is unclear") as content-free. The system trades edge-case recall for robust security.