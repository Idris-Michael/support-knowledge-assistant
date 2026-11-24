"""The answer graph, every branch, with scripted models: no database and no network."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from support_knowledge_assistant.agent import (
    REFUSAL,
    Assistant,
    check_citations,
    format_sources,
    parse_relevant,
)
from support_knowledge_assistant.config import Principal
from support_knowledge_assistant.retrieve import Hit

CUSTOMER = Principal(name="t", role="customer")


def hit(n: int, text: str = "VACUUM reclaims space.") -> Hit:
    return Hit(
        chunk_id=n,
        section_id=f"page#S{n}",
        url=f"https://example.test/page#S{n}",
        title="Page",
        heading=f"Page › Section {n}",
        text=text,
        acl=["public"],
        source="docs",
        score=1.0 / n,
    )


class Scripted(BaseChatModel):
    """Returns the scripted replies in order and records what it was sent."""

    replies: list[str]
    seen: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any
    ) -> ChatResult:
        self.seen.append(messages)
        text = self.replies.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def assistant(
    hits: list[Hit], grade: list[str], answers: list[str], seen_questions: list[str] | None = None
) -> Assistant:
    def retrieve(question: str, groups: list[str]) -> list[Hit]:
        if seen_questions is not None:
            seen_questions.append(question)
        assert groups == ["public"]
        return hits

    return Assistant(retrieve, Scripted(replies=grade, seen=[]), Scripted(replies=answers, seen=[]))


def test_answers_with_citations_mapped_to_sections() -> None:
    a = assistant(
        [hit(1), hit(2), hit(3)], ['{"relevant": [1, 3]}'], ["Run VACUUM [1]. Then check size [3]."]
    )
    r = a.ask("why is my table big?", CUSTOMER)
    assert r.outcome == "answered"
    assert r.answer == "Run VACUUM [1]. Then check size [3]."
    assert [(c.n, c.section_id) for c in r.citations] == [(1, "page#S1"), (3, "page#S3")]
    assert r.relevant == [1, 3]
    assert [s["step"] for s in r.steps] == ["guard", "retrieve", "grade", "answer", "check"]


def test_writer_only_sees_sources_the_grader_kept() -> None:
    a = assistant([hit(1, "kept text"), hit(2, "dropped text")], ['{"relevant": [1]}'], ["Kept [1]."])
    a.ask("q about kept text", CUSTOMER)
    sent = str(a.writer.seen[0][-1].content)  # type: ignore[attr-defined]
    assert "kept text" in sent and "dropped text" not in sent


def test_personal_data_is_redacted_before_retrieval_and_models() -> None:
    seen: list[str] = []
    a = assistant([hit(1)], ['{"relevant": [1]}'], ["Yes [1]."], seen)
    r = a.ask("I'm jo@example.com on 07700 900123, why is the table big?", CUSTOMER)
    assert seen == ["I'm [EMAIL] on [PHONE], why is the table big?"]
    assert r.redactions == {"email": 1, "phone": 1}
    assert "jo@example.com" not in str(a.grader.seen[0])  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("hits", "grade", "answers", "reason", "outcome"),
    [
        ([], [], [], "no_documents", "refused"),
        ([hit(1)], ['{"relevant": []}'], [], "nothing_relevant", "refused"),
        ([hit(1)], ["I think source one"], [], "grader_unreadable", "error"),
        ([hit(1)], ['{"relevant": [1]}'], ["NOT_IN_SOURCES"], "model_declined", "refused"),
        ([hit(1)], ['{"relevant": [1]}'], ["No citation here.", "Still none."], "uncited", "refused"),
        ([hit(1)], ['{"relevant": [1]}'], ["Wrong [2].", "Wrong again [5]."], "uncited", "refused"),
    ],
)
def test_every_refusal_uses_the_same_wording(
    hits: list[Hit], grade: list[str], answers: list[str], reason: str, outcome: str
) -> None:
    """A restricted question and an unanswerable one must look the same to the asker."""
    r = assistant(hits, grade, answers).ask("a question", CUSTOMER)
    assert (r.outcome, r.reason) == (outcome, reason)
    assert r.answer == REFUSAL
    assert r.citations == []


def test_bad_citation_gets_one_retry_with_feedback() -> None:
    a = assistant([hit(1), hit(2)], ['{"relevant": [1]}'], ["Uses [2].", "Uses [1]."])
    r = a.ask("q", CUSTOMER)
    assert r.outcome == "answered" and r.answer == "Uses [1]."
    retry_prompt = str(a.writer.seen[1][-1].content)  # type: ignore[attr-defined]
    assert "previous answer was rejected" in retry_prompt and "[2]" in retry_prompt


@pytest.mark.parametrize(
    ("question", "reason"), [("   ", "empty_question"), ("x" * 2001, "question_too_long")]
)
def test_guard_refuses_before_any_model_call(question: str, reason: str) -> None:
    a = assistant([hit(1)], [], [])
    r = a.ask(question, CUSTOMER)
    assert (r.outcome, r.reason) == ("refused", reason)
    assert a.grader.seen == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"relevant": [1, 2]}', [1, 2]),
        ('```json\n{"relevant": ["3", 1]}\n```', [1, 3]),
        ('{"relevant": [0, 2, 9]}', [2]),  # out-of-range numbers dropped
        ('{"relevant": []}', []),
        ("no json", None),
        ('{"relevant": "1"}', None),
        ("{broken", None),
        ("[1, 2]", None),
    ],
)
def test_parse_relevant(text: str, expected: list[int] | None) -> None:
    assert parse_relevant(text, available=5) == expected


def test_check_citations() -> None:
    assert check_citations("A [1]. B [2].", [1, 2]) is None
    assert "no citations" in (check_citations("A.", [1]) or "")
    assert "[3]" in (check_citations("A [3].", [1, 2]) or "")


def test_format_sources_truncates_long_text_and_filters() -> None:
    out = format_sources([hit(1, "x" * 5000), hit(2)], only=[1])
    assert out.count("<source") == 1 and out.endswith("…\n</source>")
