"""A small model gateway: `POST /v1/complete` → `claude -p` on the host. Containers call it with
LLM_MODE=proxy, so they can use the host's Claude login without holding it. Bearer-token protected;
only the configured grade and answer models can be requested."""

from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from .llm import ClaudeCliChat, LLMError


class CompleteIn(BaseModel):
    system: str = Field(max_length=20_000)
    prompt: str = Field(max_length=60_000)
    model: str


def create_app(make_model: Any, token: str, allowed: set[str]) -> FastAPI:
    if len(token) < 24:
        raise ValueError("LLM_PROXY_TOKEN must be at least 24 characters")
    app = FastAPI(title="ska-llm-proxy", version="0.1.0")

    @app.post("/v1/complete")
    def complete(body: CompleteIn, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        if not authorization or not hmac.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "token required")
        if body.model not in allowed:
            raise HTTPException(400, f"model not allowed: {body.model}")
        chat: BaseChatModel = make_model(body.model)
        try:
            reply = chat.invoke([SystemMessage(body.system), HumanMessage(body.prompt)])
        except LLMError as e:
            raise HTTPException(502, str(e)) from e
        usage: dict[str, Any] = dict(reply.usage_metadata or {})
        return {
            "text": str(reply.content),
            "model": body.model,
            "latency_ms": int(reply.response_metadata.get("latency_ms", 0)),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    return app


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    from .config import Settings

    settings = Settings()
    app = create_app(
        lambda model: ClaudeCliChat(model=model, binary=settings.claude_cli_path),
        os.environ.get("LLM_PROXY_TOKEN", ""),
        {settings.grade_model, settings.answer_model},
    )
    # 0.0.0.0 so containers can reach it through host.docker.internal; the token guards it.
    uvicorn.run(app, host=os.environ.get("LLM_PROXY_HOST", "0.0.0.0"), port=8091)  # noqa: S104
