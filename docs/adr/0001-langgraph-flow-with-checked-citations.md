# 1. A LangGraph flow with a separate grader, and citations checked by code

Status: accepted

## Context
A support assistant that invents a setting or a default does more harm than one that says "I don't
know". The desk asked for three things: every fact traceable to a document, a plain refusal when the
documents do not cover the question, and no way to tell from a refusal whether restricted notes exist.

A single "retrieve, then answer" prompt leaves all three to the model's judgement.

## Decision
The answer is a LangGraph state machine with five nodes:

1. **guard**: redact personal data (ADR 4), reject empty or over-long questions. No model involved.
2. **retrieve**: sections the asker's role may read (ADR 3).
3. **grade**: a small model (Claude Haiku) returns `{"relevant": [n, ...]}`. None relevant → refuse.
   Unreadable JSON → `error`, not a guess.
4. **answer**: a larger model (Claude Sonnet) sees only the sources the grader kept, cites `[n]`
   after each fact, and replies `NOT_IN_SOURCES` if they do not answer the question.
5. **check**: code, not a model. At least one citation, and every citation must point at a source
   the grader kept. On failure the writer gets one retry with the reason; a second failure refuses.

Every refusal returns the same sentence. The reason (`nothing_relevant`, `model_declined`, `uncited`
and so on) goes to the log and the operator console, not into the wording.

## Consequences
- Two model calls per answered question: median 8.4 s end to end in the benchmark (in the console
  run shown in the README, grading took 2.4 s and writing 4.8 s). Off-topic questions stop at the
  grader: 2.5 to 5.4 s in the benchmark.
- The citation check catches a stray `[4]` or an answer with no sources; it cannot tell whether a
  cited sentence actually supports the claim. That is what the hand check measures
  (`bench/hand_check.md`: 0 wrong statements in 47 answers, 7 incomplete).
- In the benchmark the retry never fired: Sonnet always cited correctly first time. The branch is
  covered by tests with scripted models.
- Each node records its time and token use, so the console can show where the seconds went.
