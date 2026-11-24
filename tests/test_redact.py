import pytest

from support_knowledge_assistant.redact import redact


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("email me at priya.shah@example.com please", "email"),
        ("call +44 7700 900461 today", "phone"),
        ("call 07700 900461 today", "phone"),
        ("office 020 7946 0958", "phone"),
        ("US line +1 415 555 0100", "phone"),
        ("card 4242 4242 4242 4242 on file", "card"),
        ("card 4242-4242-4242-4242", "card"),
        ("NI number QQ 12 34 56 C", "ni_number"),
    ],
)
def test_redacts_each_kind_of_personal_data(text: str, kind: str) -> None:
    r = redact(text)
    assert r.counts == {kind: 1}
    assert f"[{kind.upper()}]" in r.text


@pytest.mark.parametrize(
    "text",
    [
        "PostgreSQL 18.7 was released",
        "set statement_timeout to 300000 ms",
        "LSN 0/16B3748 and WAL segment 000000010000000000000001",
        "SQLSTATE 40P01 and 53300",
        "restore to 2026-11-20 14:04 UTC",
        "max_wal_size = 1GB, port 5432",
        "a card-like number that fails Luhn: 4242 4242 4242 4241",
    ],
)
def test_leaves_database_vocabulary_alone(text: str) -> None:
    """A support question is full of numbers; only personal data may be removed."""
    r = redact(text)
    assert r.text == text
    assert r.counts == {}


def test_keeps_spacing_around_redacted_phone() -> None:
    assert redact("on +44 7700 900461 if needed").text == "on [PHONE] if needed"
