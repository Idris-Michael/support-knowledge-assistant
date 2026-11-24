"""Hybrid retrieval: Postgres full-text search and pgvector cosine search, fused with Reciprocal Rank
Fusion, one chunk per section. The access filter is part of both SQL queries (ADR 3), so a chunk the
asker may not read is never a candidate, rather than being removed afterwards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

Mode = Literal["keyword", "vector", "hybrid"]
RRF_K = 60

# OR-query over the question's stemmed words, ranked with ts_rank normalised by document length.
# AND (plainto_tsquery) finds nothing for most ticket-length questions; see ADR 2.
KEYWORD_SQL = text(
    """
    WITH q AS (
      SELECT to_tsquery('simple', string_agg(quote_literal(lexeme), ' | ')) AS query
      FROM unnest(to_tsvector('english', :q))
    )
    SELECT c.id
    FROM chunks c, q
    WHERE q.query IS NOT NULL AND c.tsv @@ q.query AND c.acl && CAST(:groups AS varchar[])
    ORDER BY ts_rank(c.tsv, q.query, 1) DESC, c.id
    LIMIT :limit
    """
)

VECTOR_SQL = text(
    """
    SELECT c.id, c.embedding <=> CAST(:v AS vector) AS distance
    FROM chunks c
    WHERE c.acl && CAST(:groups AS varchar[])
    ORDER BY c.embedding <=> CAST(:v AS vector), c.id
    LIMIT :limit
    """
)

CHUNKS_SQL = text(
    "SELECT id, section_id, url, title, heading, text, acl, source FROM chunks WHERE id = ANY(:ids)"
)


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    section_id: str
    url: str
    title: str
    heading: str
    text: str
    acl: list[str]
    source: str
    score: float
    keyword_rank: int | None = None
    vector_rank: int | None = None
    distance: float | None = None

    def to_document(self) -> Document:
        return Document(
            page_content=self.text,
            metadata={k: v for k, v in self.__dict__.items() if k != "text"},
        )


def rrf(lists: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion over ranked id lists (best first)."""
    scores: dict[int, float] = {}
    for ranked in lists:
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def keyword_ids(conn: Connection, question: str, groups: list[str], limit: int) -> list[int]:
    return [r[0] for r in conn.execute(KEYWORD_SQL, {"q": question, "groups": groups, "limit": limit})]


def vector_ids(conn: Connection, vec: list[float], groups: list[str], limit: int) -> list[tuple[int, float]]:
    literal = "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
    # Exact ordering even with the access filter: without iterative scans an HNSW index can return
    # fewer than `limit` rows once the filter removes some (pgvector 0.8+).
    conn.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    rows = conn.execute(VECTOR_SQL, {"v": literal, "groups": groups, "limit": limit})
    return [(r[0], float(r[1])) for r in rows]


def search(
    engine: Engine,
    embeddings: Embeddings | None,
    question: str,
    groups: list[str],
    *,
    mode: Mode = "hybrid",
    k: int = 5,
    candidates: int = 30,
) -> list[Hit]:
    if not question.strip() or not groups:
        return []
    with engine.begin() as conn:
        kw = keyword_ids(conn, question, groups, candidates) if mode != "vector" else []
        vec: list[tuple[int, float]] = []
        if mode != "keyword":
            if embeddings is None:
                raise ValueError(f"{mode} search needs an embedding model")
            vec = vector_ids(conn, embeddings.embed_query(question), groups, candidates)
        fused = rrf([kw, [cid for cid, _ in vec]])
        rows = {r.id: r for r in conn.execute(CHUNKS_SQL, {"ids": [cid for cid, _ in fused]})}

    kw_rank = {cid: i + 1 for i, cid in enumerate(kw)}
    vec_rank = {cid: i + 1 for i, (cid, _) in enumerate(vec)}
    distance = dict(vec)
    hits: list[Hit] = []
    seen: set[str] = set()
    for cid, score in fused:
        r = rows.get(cid)
        if r is None or r.section_id in seen:  # one chunk per section: the best-ranked one
            continue
        if not set(r.acl) & set(groups):  # belt and braces; the SQL already filtered
            raise RuntimeError(f"access filter breached for chunk {cid}")
        seen.add(r.section_id)
        hits.append(
            Hit(
                chunk_id=cid,
                section_id=r.section_id,
                url=r.url,
                title=r.title,
                heading=r.heading,
                text=r.text,
                acl=list(r.acl),
                source=r.source,
                score=score,
                keyword_rank=kw_rank.get(cid),
                vector_rank=vec_rank.get(cid),
                distance=distance.get(cid),
            )
        )
        if len(hits) >= k:
            break
    return hits


class HybridRetriever(BaseRetriever):
    """LangChain retriever over `search`. One instance per request: `groups` is the asker's access."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    engine: Engine
    embeddings: Embeddings | None
    groups: list[str]
    mode: Mode = "hybrid"
    k: int = 5
    candidates: int = 30

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        hits = search(
            self.engine,
            self.embeddings,
            query,
            self.groups,
            mode=self.mode,
            k=self.k,
            candidates=self.candidates,
        )
        return [h.to_document() for h in hits]
