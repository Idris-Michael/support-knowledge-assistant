# 4. Pattern-based redaction, at ingest and before the question goes anywhere

Status: accepted

## Context
Tickets arrive with email addresses, phone numbers, card numbers and the occasional National
Insurance number pasted in. Internal notes quote tickets. None of that should be embedded, sent to a
model or written to the answer log.

## Decision
`redact.py` replaces four kinds of data with labels (`[EMAIL]`, `[PHONE]`, `[CARD]`, `[NI_NUMBER]`):
- at **ingest**, in internal notes, so personal data never reaches the index;
- in the **guard** node, before retrieval, the models or the log see the question.

Card numbers must pass the Luhn check, so `4242 4242 4242 4241` and long LSNs or WAL file names stay.
Tests cover the database vocabulary that must survive: versions, durations, LSNs, SQLSTATE codes,
ports and dates.

The answer log stores only the redacted question, and the redaction counts.

## Consequences
- Names in free text are not caught ("this is Priya from accounts"). A model-based detector
  (for example Presidio with a spaCy model) is the upgrade; it costs a large dependency and latency.
- Over-matching is preferred to under-matching. The first version followed HMRC's rules for which
  letters an NI number may start with and so missed `QQ 12 34 56 C`, HMRC's own example number, in a
  test note; it was indexed unredacted until a test caught it. The pattern now accepts any two
  letters.
