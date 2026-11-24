"""Index and search against a real pgvector Postgres (testcontainers), with fake embeddings."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from support_knowledge_assistant.config import ROLE_GROUPS
from support_knowledge_assistant.corpus import Section
from support_knowledge_assistant.embeddings import HashEmbeddings
from support_knowledge_assistant.indexer import CHUNK_CHARS, chunk_sections, index
from support_knowledge_assistant.retrieve import HybridRetriever, rrf, search

pytestmark = pytest.mark.integration


EMB = HashEmbeddings()


def sec(sid: str, body: str, acl: list[str] | None = None) -> Section:
    return Section(
        id=sid, url=f"u://{sid}", title="T", heading=f"T › {sid}", text=body, acl=acl or ["public"]
    )


CORPUS = [
    sec("vacuum#SPACE", "VACUUM reclaims storage occupied by dead tuples; VACUUM FULL rewrites the table."),
    sec("wal#MAX-WAL-SIZE", "max_wal_size is a soft limit on WAL growth between automatic checkpoints."),
    sec("hba#FILE", "The pg_hba.conf file controls client authentication by host and database."),
    sec(
        "internal/plans#limits",
        "Standard plan connection limit is 200; pooler on port 6432.",
        ["support", "sre"],
    ),
    sec(
        "internal/breakglass#steps",
        "Break-glass superuser access: vault path ops/prod/pg-superuser.",
        ["sre"],
    ),
]


def test_customer_never_receives_restricted_chunks(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    for mode in ("keyword", "vector", "hybrid"):
        for q in ["break-glass superuser vault path", "plan connection limit pooler port", "vacuum"]:
            hits = search(engine, EMB, q, ROLE_GROUPS["customer"], mode=mode, k=10)
            assert all(h.acl == ["public"] for h in hits), (mode, q)
            support = search(engine, EMB, q, ROLE_GROUPS["support"], mode=mode, k=10)
            assert all("sre" not in h.acl or "support" in h.acl for h in support)
            assert "internal/breakglass#steps" not in {h.section_id for h in support}


def test_sre_can_reach_everything(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    hits = search(engine, EMB, "break-glass superuser vault", ROLE_GROUPS["sre"], mode="keyword", k=10)
    assert hits[0].section_id == "internal/breakglass#steps"
    assert hits[0].keyword_rank == 1 and hits[0].vector_rank is None


def test_keyword_search_matches_identifiers_and_ranks(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    hits = search(engine, EMB, "is max_wal_size a hard limit?", ["public"], mode="keyword")
    assert hits[0].section_id == "wal#MAX-WAL-SIZE"
    assert search(engine, None, "the and of", ["public"], mode="keyword") == []  # only stopwords


def test_vector_and_hybrid_return_one_chunk_per_section(engine: Engine) -> None:
    long = sec("big#S", ("Autovacuum settings explained in detail. " * 120).strip())
    index(engine, EMB, [*CORPUS, long], model="fake")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM chunks WHERE section_id = 'big#S'")).scalar_one() > 1
    for mode in ("vector", "hybrid"):
        hits = search(engine, EMB, "autovacuum settings", ["public"], mode=mode, k=10)
        ids = [h.section_id for h in hits]
        assert len(ids) == len(set(ids))
        assert all(h.distance is not None for h in hits if h.vector_rank)


def test_reindex_reuses_unchanged_embeddings(engine: Engine) -> None:
    first = index(engine, EMB, CORPUS, model="fake")
    assert (first.embedded, first.reused, first.removed) == (5, 0, 0)
    changed = [*CORPUS[:4], sec("internal/breakglass#steps", "Rewritten text.", ["sre"])]
    second = index(engine, EMB, changed, model="fake")
    assert (second.chunks, second.embedded, second.reused, second.removed) == (5, 1, 4, 1)
    assert index(engine, EMB, changed, model="other-model").embedded == 5  # new model, new vectors


def test_empty_question_or_no_groups_returns_nothing(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    assert search(engine, EMB, "  ", ["public"]) == []
    assert search(engine, EMB, "vacuum", []) == []
    with pytest.raises(ValueError, match="embedding model"):
        search(engine, None, "vacuum", ["public"], mode="vector")


def test_langchain_retriever_returns_documents(engine: Engine) -> None:
    index(engine, EMB, CORPUS, model="fake")
    docs = HybridRetriever(engine=engine, embeddings=EMB, groups=["public"], mode="keyword", k=2).invoke(
        "VACUUM FULL"
    )
    assert docs[0].metadata["section_id"] == "vacuum#SPACE"
    assert "VACUUM FULL" in docs[0].page_content
    assert "text" not in docs[0].metadata


def test_migration_rejects_chunk_without_acl(engine: Engine) -> None:
    with pytest.raises(Exception, match="ck_chunks_acl_not_empty"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO chunks (section_id, chunk_no, url, title, heading, text, acl, source, content_hash,"
                " embedding) VALUES ('x', 0, 'u', 't', 'h', 'body', '{}', 's', 'h', :v)"
            ),
            {"v": "[" + ",".join(["0"] * 768) + "]"},
        )


def test_rrf_fuses_and_breaks_ties_by_id() -> None:
    assert rrf([[1, 2, 3], [3, 1]])[:2] == [
        (1, pytest.approx(1 / 61 + 1 / 62)),
        (3, pytest.approx(1 / 63 + 1 / 61)),
    ]
    assert rrf([[2], [1]]) == [(1, pytest.approx(1 / 61)), (2, pytest.approx(1 / 61))]
    assert rrf([[], []]) == []


def test_long_sections_are_split_with_overlap() -> None:
    rows = chunk_sections([sec("big#S", "word " * 1000)])
    assert len(rows) > 1 and all(len(r.text) <= CHUNK_CHARS for r in rows)
    assert rows[0].embed_text.startswith("T › big#S\n\n")
