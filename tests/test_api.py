"""The HTTP API with a real Postgres answer log and a scripted assistant."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from support_knowledge_assistant import llm_proxy
from support_knowledge_assistant.agent import Assistant
from support_knowledge_assistant.api import RateLimiter, create_app
from support_knowledge_assistant.config import Settings
from support_knowledge_assistant.db import Answer, Chunk
from support_knowledge_assistant.llm import LLMError, OfflineChat
from support_knowledge_assistant.retrieve import Hit

TOKENS = {
    "c" * 24: {"name": "cust", "role": "customer"},
    "s" * 24: {"name": "agent", "role": "support"},
    "r" * 24: {"name": "oncall", "role": "sre"},
}
SRE = {"authorization": "Bearer " + "r" * 24}
CUST = {"authorization": "Bearer " + "c" * 24}


def hits_for(groups: list[str]) -> list[Hit]:
    out = [
        Hit(
            1,
            "vac#S",
            "https://docs/vac#S",
            "V",
            "Vacuum › Space",
            "VACUUM reclaims table space.",
            ["public"],
            "docs",
            0.03,
        )
    ]
    if "sre" in groups:
        out.append(
            Hit(
                2,
                "internal/x#y",
                "internal://x#y",
                "X",
                "Runbook",
                "table space runbook",
                ["sre"],
                "internal",
                0.02,
            )
        )
    return out


def make(engine: Engine, **overrides: object) -> TestClient:
    settings = Settings(api_tokens=json.dumps(TOKENS), llm_mode="offline", **overrides)  # type: ignore[arg-type]
    seen: list[list[str]] = []

    def retrieve(q: str, groups: list[str]) -> list[Hit]:
        seen.append(groups)
        return hits_for(groups)

    client = TestClient(create_app(settings, Assistant(retrieve, OfflineChat(), OfflineChat()), engine))
    client.seen_groups = seen  # type: ignore[attr-defined]
    return client


@pytest.mark.integration
def test_ask_answers_logs_redacted_question_and_uses_the_tokens_role(engine: Engine) -> None:
    c = make(engine)
    r = c.post(
        "/v1/ask",
        json={"question": "why does vacuum not shrink table space? mail jo@example.com"},
        headers=CUST,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "answered"
    assert body["citations"][0]["section_id"] == "vac#S"
    assert [s["section_id"] for s in body["sources"]] == ["vac#S"]
    assert body["redactions"] == {"email": 1}
    assert c.seen_groups == [["public"]]  # type: ignore[attr-defined]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    with Session(engine) as s:
        row = s.scalars(select(Answer)).one()
    assert row.principal == "cust" and row.role == "customer"
    assert "jo@example.com" not in row.question and "[EMAIL]" in row.question
    assert row.cited == ["vac#S"]


@pytest.mark.integration
def test_refusal_is_logged_without_answer_text(engine: Engine) -> None:
    c = make(engine)
    body = c.post("/v1/ask", json={"question": "zzz qqq"}, headers=CUST).json()
    assert body["outcome"] == "refused" and body["citations"] == []
    with Session(engine) as s:
        row = s.scalars(select(Answer)).one()
    assert row.outcome == "refused" and row.answer is None


@pytest.mark.integration
@pytest.mark.parametrize("headers", [{}, {"authorization": "Bearer wrong"}, {"authorization": "c" * 24}])
def test_ask_requires_a_known_token(engine: Engine, headers: dict[str, str]) -> None:
    r = make(engine).post("/v1/ask", json={"question": "vacuum"}, headers=headers)
    assert (
        r.status_code == 401 if headers.get("authorization", "").startswith("Bearer") or not headers else 401
    )


@pytest.mark.integration
def test_question_length_is_validated(engine: Engine) -> None:
    c = make(engine)
    assert c.post("/v1/ask", json={"question": ""}, headers=CUST).status_code == 422
    assert c.post("/v1/ask", json={"question": "x" * 2001}, headers=CUST).status_code == 422


@pytest.mark.integration
def test_rate_limit_per_caller(engine: Engine) -> None:
    c = make(engine, rate_limit_per_minute=2)
    codes = [
        c.post("/v1/ask", json={"question": "vacuum table space"}, headers=CUST).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    assert c.post("/v1/ask", json={"question": "vacuum table space"}, headers=SRE).status_code == 200


@pytest.mark.integration
def test_answer_log_is_sre_only(engine: Engine) -> None:
    c = make(engine)
    c.post("/v1/ask", json={"question": "vacuum table space"}, headers=CUST)
    assert c.get("/v1/answers", headers=CUST).status_code == 403
    log = c.get("/v1/answers", headers=SRE).json()
    assert len(log) == 1 and log[0]["principal"] == "cust"
    assert c.get("/v1/me", headers=SRE).json() == {
        "name": "oncall",
        "role": "sre",
        "groups": ["public", "support", "sre"],
    }


@pytest.mark.integration
def test_model_failure_is_a_502_not_a_stack_trace(engine: Engine) -> None:
    settings = Settings(api_tokens=json.dumps(TOKENS), llm_mode="offline")  # type: ignore[arg-type]

    def broken(q: str, groups: list[str]) -> list[Hit]:
        raise LLMError("claude-cli error: secret detail")

    c = TestClient(create_app(settings, Assistant(broken, OfflineChat(), OfflineChat()), engine))
    r = c.post("/v1/ask", json={"question": "vacuum"}, headers=CUST)
    assert r.status_code == 502 and "secret detail" not in r.text


@pytest.mark.integration
def test_health_and_console(engine: Engine) -> None:
    c = make(engine)
    assert c.get("/healthz").status_code == 503  # empty index
    with Session(engine) as s:
        s.add(
            Chunk(
                section_id="a#b",
                chunk_no=0,
                url="u",
                title="t",
                heading="h",
                text="x",
                acl=["public"],
                source="s",
                content_hash="h",
                embedding=[0.1] * 768,
            )
        )
        s.commit()
    assert c.get("/healthz").json() == {"status": "ok", "chunks": 1}
    assert c.get("/readyz").json() == {"status": "ready"}
    page = c.get("/")
    assert "Support Desk" in page.text and "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_api_refuses_to_start_without_tokens() -> None:
    with pytest.raises(ValueError, match="API_TOKENS"):
        create_app(Settings(), Assistant(lambda q, g: [], OfflineChat(), OfflineChat()))


@pytest.mark.parametrize(
    "raw",
    [
        '{"short": {"name": "a", "role": "sre"}}',
        '["not", "an", "object"]',
        json.dumps({"x" * 24: {"name": "a", "role": "admin"}}),
    ],
)
def test_bad_token_config_fails_at_start(raw: str) -> None:
    with pytest.raises(ValueError):
        Settings(api_tokens=raw)  # type: ignore[arg-type]


def test_rate_limiter_window() -> None:
    now = [0.0]
    rl = RateLimiter(2, clock=lambda: now[0])
    assert [rl.allow("a"), rl.allow("a"), rl.allow("a"), rl.allow("b")] == [True, True, False, True]
    now[0] = 60.0
    assert rl.allow("a")


def test_llm_proxy_checks_token_and_model() -> None:
    calls: list[str] = []

    def factory(model: str) -> OfflineChat:
        calls.append(model)
        return OfflineChat()

    c = TestClient(llm_proxy.create_app(factory, "p" * 24, {"claude-haiku-5-5"}))
    ok = {"system": "GRADE", "prompt": "<question>a b</question>", "model": "claude-haiku-5-5"}
    assert c.post("/v1/complete", json=ok).status_code == 401
    auth = {"authorization": "Bearer " + "p" * 24}
    assert c.post("/v1/complete", json={**ok, "model": "claude-opus-5-5"}, headers=auth).status_code == 400
    r = c.post("/v1/complete", json=ok, headers=auth)
    assert r.status_code == 200 and json.loads(r.json()["text"]) == {"relevant": []}
    assert calls == ["claude-haiku-5-5"]
    with pytest.raises(ValueError, match="24"):
        llm_proxy.create_app(factory, "short", set())
