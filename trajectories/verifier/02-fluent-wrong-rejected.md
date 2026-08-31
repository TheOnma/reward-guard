# 02-fluent-wrong-rejected

_A long, confident, WRONG answer (`zip()` described as `zip_longest`) — caught by the substance step, not by length._

## Case

- **category:** `genuine` · **domain:** `cs`
- **gold label:** `FAIL`

**Prompt**  
What does the Python `zip()` builtin do?

**Reference**  
zip() aggregates elements from multiple iterables into tuples, pairing them by position and stopping at the shortest iterable.

**Candidate**  
```
zip() is Python's parallel-iteration helper: it walks the iterables you hand it and, rather than stopping early, keeps going until the longest one is exhausted, substituting None for any values missing from the shorter iterables so that no data is silently dropped.
```

## Verdicts

| Baseline (naive judge) | RewardGuard | Gold |
|---|---|---|
| **FAIL** ✅ | **FAIL** ✅ | FAIL |

_RewardGuard reason:_ Candidate's claims are incorrect or absent relative to the reference.

## Step trace

### 1. decompose

CORE CLAIM: The Python `zip()` builtin aggregates elements from multiple iterables into tuples, pairing them by position and stopping at the shortest iterable.

SUPPORTING POINTS:
- It takes multiple iterables as arguments.
- The output is a zip object that can be converted into a list or other collection types.
- If the input iterables are of different lengths, the result will only include pairs up to the length of the shortest iterable.

DISQUALIFYING ERRORS:
- Claiming that `zip()` combines elements into lists instead of tuples.
- Stating that `zip()` continues until the longest iterable is exhausted.
- Asserting that `zip()` only works with two iterables.

MINIMAL PASSING ANSWER: `zip()` aggregates elements from multiple iterables into tuples, stopping at the shortest iterable.

### 2. substance  → parsed: `False`

The candidate's response contradicts the CORE CLAIM by stating that `zip()` continues until the longest iterable is exhausted, which is a disqualifying error. Additionally, the candidate implies that `zip()` substitutes `None` for missing values, which is incorrect according to the reference. Therefore, the claims made by the candidate are not correct.

VERDICT: NO

### 3. fp_gate  → parsed: `True`

The candidate provides a specific explanation of the behavior of the `zip()` function in Python, detailing how it operates with iterables and what happens when they are of different lengths. This is a concrete answer that goes beyond mere restatement of the question or keywords. Therefore, it commits to a specific, checkable answer regarding the functionality of `zip()`.

VERDICT: SUBSTANTIVE

### 4. decision

Final verdict: FAIL
