"""Chunk index (pgvector + full-text) and the answer log.

Revision ID: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("section_id", sa.String(300), nullable=False),
        sa.Column("chunk_no", sa.Integer, nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("heading", sa.String(600), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("acl", ARRAY(sa.String(32)), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('english', heading || ' ' || text)", persisted=True),
        ),
        sa.CheckConstraint("cardinality(acl) > 0", name="ck_chunks_acl_not_empty"),
    )
    op.create_index("ix_chunks_section_id", "chunks", ["section_id"])
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index("ix_chunks_acl", "chunks", ["acl"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("principal", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("redactions", sa.JSON, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("answer", sa.Text),
        sa.Column("cited", sa.JSON, nullable=False),
        sa.Column("retrieved", sa.JSON, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("models", sa.JSON, nullable=False),
    )
    op.create_index("ix_answers_created_at", "answers", ["created_at"])
    op.create_index("ix_answers_outcome", "answers", ["outcome"])


def downgrade() -> None:
    op.drop_table("answers")
    op.drop_table("chunks")
