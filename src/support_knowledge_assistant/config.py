"""All configuration comes from the environment (or `.env`). API tokens have no default: with none
configured the API refuses to start rather than run open."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Role = Literal["customer", "support", "sre"]

# What each role may read. Enforced inside the SQL that fetches candidates (ADR 3), never after.
ROLE_GROUPS: dict[str, list[str]] = {
    "customer": ["public"],
    "support": ["public", "support"],
    "sre": ["public", "support", "sre"],
}


class Principal(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    role: Role

    @property
    def groups(self) -> list[str]:
        return ROLE_GROUPS[self.role]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ska:ska@127.0.0.1:5434/ska"

    # ollama: real embeddings. hash: word hashes for CI and smoke tests only (see embeddings.py).
    embed_provider: Literal["ollama", "hash"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768

    # claude-cli: `claude -p` on this machine. proxy: the same through `ska-llm-proxy` (for containers).
    # offline: a deterministic stand-in so tests and a fresh clone run with no model at all.
    llm_mode: Literal["claude-cli", "proxy", "offline"] = "claude-cli"
    llm_proxy_url: str = "http://host.docker.internal:8091"
    llm_proxy_token: SecretStr | None = None
    claude_cli_path: str | None = None
    grade_model: str = "claude-haiku-5-5"
    answer_model: str = "claude-sonnet-5-5"

    # vector measured best on the gold set (46/50 vs hybrid 44/50, keyword 41/50); see ADR 2.
    retrieve_mode: Literal["keyword", "vector", "hybrid"] = "vector"
    retrieve_k: int = Field(default=5, ge=1, le=20)
    retrieve_candidates: int = Field(default=30, ge=5, le=200)

    # JSON object: {"<token>": {"name": "...", "role": "customer|support|sre"}}
    api_tokens: SecretStr | None = None
    rate_limit_per_minute: int = Field(default=20, ge=1)

    otel_exporter_otlp_endpoint: str | None = None
    service_name: str = "support-knowledge-assistant"

    @field_validator("api_tokens")
    @classmethod
    def _tokens_parse(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None:
            parse_tokens(v.get_secret_value())
        return v

    def principals(self) -> dict[str, Principal]:
        return parse_tokens(self.api_tokens.get_secret_value()) if self.api_tokens else {}


def parse_tokens(raw: str) -> dict[str, Principal]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("API_TOKENS must be a JSON object of token -> principal")
    out: dict[str, Principal] = {}
    for token, who in data.items():
        if len(token) < 24:
            raise ValueError("every API token must be at least 24 characters")
        out[token] = Principal.model_validate(who)
    return out
