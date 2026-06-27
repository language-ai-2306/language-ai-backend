"""
Alembic environment.

This file is run by the `alembic` command. Its job is to:
  1. Know your database URL  -> taken from app settings (.env).
  2. Know what your tables SHOULD look like -> Base.metadata, after importing
     every model so they all register.
Then `alembic revision --autogenerate` compares (2) against the real DB and
writes the difference as a migration; `alembic upgrade head` applies it.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- make the app importable and pull in settings + models -----------------
from app.config.settings import settings
from app.db.base import Base
import app.models  # noqa: F401  -> importing the package registers ALL tables

# Alembic Config object (reads alembic.ini).
config = context.config

# Inject the real database URL from .env (never hard-code secrets here).
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what Alembic compares the live database against.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting (writes statements to stdout)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # also notice column TYPE changes, not just add/drop
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
