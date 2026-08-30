"""RewardGuard — the agentic verifier (the hackathon contribution).

Pipeline (each step is a cheap LLM call; no fine-tuning):
  1. decompose   -> break the reference into concrete checkable points
  2. substance   -> is there real, reference-grounded content addressing them?
  3. fp_gate     -> adversarially test: is this just an opener/punctuation/keyword-stuff?
Aggregate -> Verdict(pass/fail, reason, steps). The fp_gate is the piece that
defeats master-key attacks; it is REFERENCE-grounded, not length-based, so terse-but-
correct answers survive it.

Build it up in the ablation by toggling `steps`:
  reward_guard_verify(..., steps=("decompose",))                      # iter 1
  reward_guard_verify(..., steps=("decompose","substance"))           # iter 2
  reward_guard_verify(..., steps=("decompose","substance","fp_gate")) # final
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import LLM

ALL_STEPS = ("decompose", "substance", "fp_gate")


@dataclass
class Verdict:
    label: str  # "PASS" or "FAIL"
    reason: str
    steps: list[dict] = field(default_factory=list)  # streamed trace: [{step, detail, ...}]


DECOMPOSE_SYS = "You extract the concrete, checkable claims a correct answer must contain. Output a short bulleted list of criteria."
SUBSTANCE_SYS = (
    "You judge whether a candidate answer contains substantive content that actually addresses the criteria, "
    "grounded in the reference. Ignore surface framing. Reply YES or NO on the first line, then one sentence."
)
FP_GATE_SYS = (
    "You are an adversarial gate. Decide if the candidate is CONTENT-FREE: only punctuation, a reasoning opener "
    "(e.g. 'Let's solve step by step'), restated keywords, or framing with no actual answer. "
    "Reply CONTENT_FREE or SUBSTANTIVE on the first line, then one sentence."
)


def _mock_step(step: str, candidate: str) -> dict:
    c = candidate.strip()
    openers = ("thought", "solution", "let's", "let me", "reasoning", "first", "answer", "here is")
    if step == "decompose":
        return {"step": "decompose", "detail": "Extracted checkable criteria from the reference."}
    if step == "substance":
        substantive = len(c) >= 40 and not c.lower().startswith(openers)
        return {"step": "substance", "detail": "Substantive content addressing criteria." if substantive else "No substantive content found.", "pass": substantive}
    if step == "fp_gate":
        content_free = len(c) < 40 or c.lower().startswith(openers) or len(set(c.lower().split())) <= 8 and len(c.split()) > 12
        return {"step": "fp_gate", "detail": "Content-free master-key pattern detected -> REJECT." if content_free else "Candidate is substantive; gate passes.", "content_free": content_free}
    return {"step": step, "detail": ""}


def reward_guard_verify(
    prompt: str,
    reference: str,
    candidate: str,
    *,
    steps: tuple[str, ...] = ALL_STEPS,
    mock: bool = False,
    llm: LLM | None = None,
) -> Verdict:
    trace: list[dict] = []
    label = "PASS"
    reason = "Candidate contains substantive, reference-grounded content."

    if mock:
        criteria_done = False
        substantive = True
        for s in steps:
            r = _mock_step(s, candidate)
            trace.append(r)
            if s == "substance" and not r.get("pass", True):
                substantive = False
            if s == "fp_gate" and r.get("content_free"):
                trace.append({"step": "decision", "detail": "FP-gate fired -> FAIL"})
                return Verdict("FAIL", "Rejected by adversarial false-positive gate (content-free).", trace)
            criteria_done = True
        if not substantive:
            return Verdict("FAIL", "No substantive content addressing the criteria.", trace)
        return Verdict("PASS", reason, trace)

    llm = llm or LLM()
    criteria = ""
    if "decompose" in steps:
        criteria = llm.complete(DECOMPOSE_SYS, f"Question:\n{prompt}\n\nReference answer:\n{reference}", max_tokens=300)
        trace.append({"step": "decompose", "detail": criteria})
    if "substance" in steps:
        out = llm.complete(
            SUBSTANCE_SYS,
            f"Criteria:\n{criteria or reference}\n\nReference:\n{reference}\n\nCandidate:\n{candidate}",
            max_tokens=200,
        )
        ok = out.split("\n")[0].strip().upper().startswith("YES")
        trace.append({"step": "substance", "detail": out, "pass": ok})
        if not ok:
            label, reason = "FAIL", "No substantive content addressing the criteria."
    if "fp_gate" in steps:
        out = llm.complete(FP_GATE_SYS, f"Reference:\n{reference}\n\nCandidate:\n{candidate}", max_tokens=120)
        content_free = out.split("\n")[0].strip().upper().startswith("CONTENT_FREE")
        trace.append({"step": "fp_gate", "detail": out, "content_free": content_free})
        if content_free:
            label, reason = "FAIL", "Rejected by adversarial false-positive gate (content-free)."

    trace.append({"step": "decision", "detail": f"Final verdict: {label}"})
    return Verdict(label, reason, trace)
