from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from support_knowledge_assistant.db import Base

target_metadata = Base.metadata


def url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_URL"]


if context.is_offline_mode():
    context.configure(url=url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url()).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
