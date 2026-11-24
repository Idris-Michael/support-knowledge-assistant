"""HTTP API and the operator console.

POST /v1/ask        answer with citations, or refuse (any role)
GET  /v1/answers    the answer log, newest first (sre only)
GET  /healthz       database reachable and index not empty
GET  /              Support Desk console

Callers authenticate with a bearer token mapped to a name and a role (API_TOKENS). The role decides
which documents retrieval may read; nothing in the request can widen it.
"""

# No `from __future__ import annotations` here: FastAPI must resolve the Caller/Db aliases defined
# inside create_app, and string annotations would turn them into query parameters.
import hmac
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from importlib import resources
from typing import Annotated, Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .agent import MAX_QUESTION_CHARS, AskResult, Assistant
from .config import Principal, Settings
from .db import Answer, Chunk, make_engine

log = structlog.get_logger()

CONSOLE_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
    "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class RateLimiter:
    """Sliding one-minute window per caller, in-process. Several replicas need the limit at the
    ingress or in a shared store instead."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = per_minute
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        t = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and t - q[0] >= 60:
                q.popleft()
            if len(q) >= self._limit:
                return False
            q.append(t)
            return True


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def result_json(r: AskResult, answer_id: str) -> dict[str, Any]:
    return {
        "id": answer_id,
        "outcome": r.outcome,
        "reason": r.reason,
        "answer": r.answer,
        "citations": [c.__dict__ for c in r.citations],
        "sources": [
            {
                "n": n,
                "section_id": h.section_id,
                "heading": h.heading,
                "url": h.url,
                "source": h.source,
                "used": n in r.relevant,
                "keyword_rank": h.keyword_rank,
                "vector_rank": h.vector_rank,
                "distance": round(h.distance, 4) if h.distance is not None else None,
            }
            for n, h in enumerate(r.retrieved, 1)
        ],
        "redactions": r.redactions,
        "latency_ms": r.latency_ms,
        "steps": [{k: v for k, v in s.items() if k in ("step", "ms", "model")} for s in r.steps],
    }


def create_app(settings: Settings, assistant: Assistant, engine: Engine | None = None) -> FastAPI:
    principals = settings.principals()
    if not principals:
        raise ValueError("API_TOKENS is empty: refusing to start an open API")
    engine = engine or make_engine(settings.database_url)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    app = FastAPI(title="support-knowledge-assistant", version="0.1.0")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    def caller(authorization: Annotated[str | None, Header()] = None) -> Principal:
        token = (authorization or "").removeprefix("Bearer ").strip()
        for known, who in principals.items():
            if token and hmac.compare_digest(token, known):
                return who
        raise HTTPException(401, "a valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})

    Caller = Annotated[Principal, Depends(caller)]

    def db() -> Any:
        with Session(engine) as s:
            yield s

    Db = Annotated[Session, Depends(db)]

    @app.get("/healthz")
    def healthz(s: Db) -> dict[str, Any]:
        try:
            chunks = s.execute(select(func.count()).select_from(Chunk)).scalar_one()
        except Exception as e:
            raise HTTPException(503, "database unavailable") from e
        if chunks == 0:
            raise HTTPException(503, "index is empty: run `ska index`")
        return {"status": "ok", "chunks": chunks}

    @app.get("/", response_class=HTMLResponse)
    def console() -> HTMLResponse:
        page = resources.files("support_knowledge_assistant").joinpath("static/console.html")
        return HTMLResponse(page.read_text("utf-8"), headers={"Content-Security-Policy": CONSOLE_CSP})

    @app.get("/v1/me")
    def me(who: Caller) -> dict[str, Any]:
        return {"name": who.name, "role": who.role, "groups": who.groups}

    @app.post("/v1/ask")
    def ask(body: AskIn, s: Db, who: Caller) -> dict[str, Any]:
        if not limiter.allow(who.name):
            raise HTTPException(429, "rate limit: try again in a minute", headers={"Retry-After": "60"})
        try:
            r = assistant.ask(body.question, who)
        except Exception as e:  # a model or database failure is logged and reported, never a stack trace
            log.error("ask_failed", principal=who.name, error=type(e).__name__, detail=str(e)[:300])
            raise HTTPException(502, "the assistant is unavailable; try again shortly") from e
        row = Answer(
            principal=who.name,
            role=who.role,
            question=r.question,  # redacted
            redactions=r.redactions,
            outcome=r.outcome,
            reason=r.reason,
            answer=r.answer if r.outcome == "answered" else None,
            cited=[c.section_id for c in r.citations],
            retrieved=[h.section_id for h in r.retrieved],
            latency_ms=r.latency_ms,
            models={s.get("step"): s.get("model") for s in r.steps if s.get("model")},
        )
        s.add(row)
        s.commit()
        log.info(
            "ask", principal=who.name, role=who.role, outcome=r.outcome, reason=r.reason, ms=r.latency_ms
        )
        return result_json(r, row.id)

    @app.get("/v1/answers")
    def answers(s: Db, who: Caller, limit: int = 50) -> list[dict[str, Any]]:
        if who.role != "sre":
            raise HTTPException(403, "the answer log is for SRE only")
        rows = s.scalars(select(Answer).order_by(Answer.created_at.desc()).limit(min(max(limit, 1), 200)))
        return [
            {
                "id": a.id,
                "at": a.created_at.isoformat(),
                "principal": a.principal,
                "role": a.role,
                "question": a.question,
                "outcome": a.outcome,
                "reason": a.reason,
                "cited": a.cited,
                "latency_ms": a.latency_ms,
            }
            for a in rows
        ]

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    from . import telemetry
    from .service import build_assistant

    settings = Settings()
    telemetry.setup(settings.service_name, settings.otel_exporter_otlp_endpoint)
    engine = make_engine(settings.database_url)
    app = create_app(settings, build_assistant(settings, engine), engine)
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    uvicorn.run(app, host="0.0.0.0", port=8080)  # noqa: S104 - inside the container
