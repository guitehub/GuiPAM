"""Environnement Alembic (moteur sync : les migrations SQLite n'ont pas besoin d'async)."""

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401  (enregistre les tables dans SQLModel.metadata)

config = context.config
target_metadata = SQLModel.metadata


def get_url() -> str:
    override = config.get_main_option("sqlalchemy.url", "")
    if config.attributes.get("configured_url"):
        return config.attributes["configured_url"]
    db_path = os.environ.get("GUIPAM_DB_PATH")
    if db_path:
        return f"sqlite:///{db_path}"
    return override or "sqlite:///data/guipam.db"


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # requis pour ALTER TABLE sous SQLite
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
