from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

from support_knowledge_assistant.db import make_engine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """A throwaway pgvector Postgres with the real migrations applied."""
    try:
        from testcontainers.community.postgres import PostgresContainer

        container = PostgresContainer("pgvector/pgvector:pg18", driver="psycopg")
        container.start()
    except Exception as e:  # Docker not available: integration tests are skipped, not failed
        pytest.skip(f"Docker unavailable: {e}")
    # testcontainers reports "localhost"; on Windows that tries IPv6 first and can hang for minutes.
    url = container.get_connection_url().replace("@localhost:", "@127.0.0.1:")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        container.stop()


@pytest.fixture
def engine(pg_url: str) -> Iterator[Engine]:
    eng = make_engine(pg_url)
    with eng.begin() as conn:
        conn.exec_driver_sql("TRUNCATE chunks, answers")
    yield eng
    eng.dispose()
