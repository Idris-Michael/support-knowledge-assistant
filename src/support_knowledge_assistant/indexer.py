"""Sections → chunks → embeddings → Postgres. Re-indexing only embeds chunks whose text changed."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .corpus import Section
from .db import Chunk

CHUNK_CHARS = 1500  # ~375 tokens: small enough that one chunk is about one thing
OVERLAP_CHARS = 150
EMBED_BATCH = 64


@dataclass(frozen=True)
class ChunkRow:
    section: Section
    chunk_no: int
    text: str

    @property
    def embed_text(self) -> str:
        """What gets embedded: the heading path gives a short chunk its context ("max_wal_size" alone
        is ambiguous; "Write Ahead Log › Checkpoints › max_wal_size" is not)."""
        return f"{self.section.heading}\n\n{self.text}"

    def content_hash(self, model: str) -> str:
        return hashlib.sha256(f"{model}\n{self.embed_text}".encode()).hexdigest()


def chunk_sections(sections: Iterable[Section]) -> list[ChunkRow]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_CHARS,
        chunk_overlap=OVERLAP_CHARS,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    rows: list[ChunkRow] = []
    for s in sections:
        parts = [s.text] if len(s.text) <= CHUNK_CHARS else splitter.split_text(s.text)
        rows.extend(ChunkRow(s, i, p) for i, p in enumerate(parts))
    return rows


@dataclass(frozen=True)
class IndexStats:
    chunks: int
    embedded: int
    reused: int
    removed: int


def index(engine: Engine, embeddings: Embeddings, sections: list[Section], *, model: str) -> IndexStats:
    rows = chunk_sections(sections)
    with Session(engine) as db:
        existing = {c.content_hash: c.embedding for c in db.scalars(select(Chunk))}
        todo = [r for r in rows if r.content_hash(model) not in existing]
        vectors: dict[str, list[float]] = {}
        for start in range(0, len(todo), EMBED_BATCH):
            batch = todo[start : start + EMBED_BATCH]
            for row, vec in zip(
                batch,
                embeddings.embed_documents([r.embed_text for r in batch]),
                strict=True,
            ):
                vectors[row.content_hash(model)] = vec
        removed = len(set(existing) - {r.content_hash(model) for r in rows})
        # Replace in one transaction: readers see the old index or the new one, never half of each.
        db.execute(delete(Chunk))
        for r in rows:
            h = r.content_hash(model)
            db.add(
                Chunk(
                    section_id=r.section.id,
                    chunk_no=r.chunk_no,
                    url=r.section.url,
                    title=r.section.title,
                    heading=r.section.heading,
                    text=r.text,
                    acl=list(r.section.acl),
                    source=r.section.source,
                    content_hash=h,
                    embedding=vectors[h] if h in vectors else existing[h],
                )
            )
        db.commit()
    return IndexStats(
        chunks=len(rows),
        embedded=len(todo),
        reused=len(rows) - len(todo),
        removed=removed,
    )
