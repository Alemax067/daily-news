"""Alembic environment.

Uses sync sqlite driver (matching DATA_DIR / app.db) regardless of the runtime
async engine. Wires `target_metadata = Base.metadata` so autogenerate sees all
models. `render_as_batch=True` so SQLite ALTER TABLE works under the batch
operations API (DROP COLUMN / change type / etc.).
"""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `src.*` importable when running via `alembic` CLI from backend/.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DATA_DIR  # noqa: E402
from src.db import Base  # noqa: E402

# Import all model classes so Base.metadata is fully populated for autogenerate.
import src.db  # noqa: E402,F401

config = context.config

# Override sqlalchemy.url with the project's actual DB path (sync driver).
SYNC_DB_URL = f"sqlite:///{DATA_DIR / 'app.db'}"
config.set_main_option("sqlalchemy.url", SYNC_DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Tables managed by langgraph-checkpoint-sqlite (writes / checkpoints / etc.).
# They live in the same DB but their schema is owned by that library, so
# autogenerate must ignore them.
_EXTERNAL_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "writes",
}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTERNAL_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=SYNC_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
