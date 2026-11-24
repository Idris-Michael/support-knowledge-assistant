"""PII redaction for internal notes (at ingest) and for questions (before logging or sending them
to a model). Pattern based, on purpose: it is predictable and testable, and it catches the four kinds
of data that turn up in support tickets. It will not catch a name in free text; see ADR 4."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# UK numbers (+44 / 0 prefix) and other international numbers written with a leading +.
PHONE = re.compile(
    r"(?<![\w+])(?:\+44\s?|0)\d(?:[\s-]?\d){8,9}\b|(?<![\w+])\+(?!44)\d{1,3}(?:[\s-]?\d){6,12}\b"
)
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
# Any two letters, not only the prefixes HMRC issues: a redactor should over-match, and HMRC's own
# example number (QQ 12 34 56 C) is exactly what people paste into tickets.
NI_NUMBER = re.compile(r"\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE)


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: dict[str, int]


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def redact(text: str) -> Redaction:
    counts = {"email": 0, "phone": 0, "card": 0, "ni_number": 0}

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            counts["card"] += 1
            return "[CARD]"
        return m.group(0)

    def sub(pattern: re.Pattern[str], label: str, kind: str, s: str) -> str:
        def repl(_: re.Match[str]) -> str:
            counts[kind] += 1
            return label

        return pattern.sub(repl, s)

    out = sub(EMAIL, "[EMAIL]", "email", text)
    out = CARD.sub(card, out)  # before phones: a card number also looks like a long phone number
    out = sub(NI_NUMBER, "[NI_NUMBER]", "ni_number", out)
    out = sub(PHONE, "[PHONE]", "phone", out)
    return Redaction(out, {k: v for k, v in counts.items() if v})
