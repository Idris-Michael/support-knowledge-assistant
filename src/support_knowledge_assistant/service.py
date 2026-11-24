"""Wires settings to a ready Assistant: database, embeddings, retrieval mode and the two models."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from .agent import Assistant
from .config import Settings
from .db import make_engine
from .embeddings import make_embeddings
from .llm import make_chat
from .retrieve import Hit, search


def build_assistant(settings: Settings, engine: Engine | None = None) -> Assistant:
    engine = engine or make_engine(settings.database_url)
    embeddings = make_embeddings(settings) if settings.retrieve_mode != "keyword" else None

    def retrieve(question: str, groups: list[str]) -> list[Hit]:
        return search(
            engine,
            embeddings,
            question,
            groups,
            mode=settings.retrieve_mode,
            k=settings.retrieve_k,
            candidates=settings.retrieve_candidates,
        )

    return Assistant(
        retrieve, make_chat(settings, settings.grade_model), make_chat(settings, settings.answer_model)
    )
