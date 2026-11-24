"""Schema: the chunk index (text, access list, embedding, full-text vector) and the answer log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Computed,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 768


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[str] = mapped_column(String(300), index=True)
    chunk_no: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    heading: Mapped[str] = mapped_column(String(600))
    text: Mapped[str] = mapped_column(Text)
    acl: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    source: Mapped[str] = mapped_column(String(64))
    # sha256 of (embedding model, heading, text): unchanged chunks keep their embedding on re-index.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', heading || ' ' || text)", persisted=True),
    )

    __table_args__ = (
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_acl", "acl", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Answer(Base):
    """One row per question asked through the API. Stores the redacted question only."""

    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    principal: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    question: Mapped[str] = mapped_column(Text)
    redactions: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    outcome: Mapped[str] = mapped_column(String(16), index=True)  # answered | refused | error
    reason: Mapped[str | None] = mapped_column(String(64))
    answer: Mapped[str | None] = mapped_column(Text)
    cited: Mapped[list[str]] = mapped_column(JSON, default=list)
    retrieved: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    models: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def make_engine(url: str) -> Engine:
    # connect_timeout: a database that is down should fail in seconds, not hang the request.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
