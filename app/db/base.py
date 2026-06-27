"""
Database foundation: the engine, the session, and the shared base classes.

Read this file top-to-bottom — it is the heart of the database layer.

  * `engine`          -> the live connection pool to PostgreSQL (on AWS RDS).
  * `SessionLocal`    -> a factory that hands out short-lived "sessions"
                         (a session = one unit of work / conversation with the DB).
  * `Base`            -> the root every model inherits from. SQLAlchemy uses it
                         to keep a registry of all your tables.
  * `AbstractEntity`  -> YOUR "abstract entity". It is NOT a table itself
                         (`__abstract__ = True`), but every real table inherits
                         its columns (id, guid, created_at, ...) automatically.
  * `get_db`          -> a helper FastAPI uses to give each request a session
                         and close it afterwards.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, create_engine, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config.settings import settings

# ---------------------------------------------------------------------------
# 1. The engine — the actual connection to PostgreSQL.
#    settings.database_url comes from your .env file (DATABASE_URL=...).
#    `pool_pre_ping=True` quietly checks a connection is still alive before
#    using it, which matters on RDS because idle connections can drop.
# ---------------------------------------------------------------------------
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,  # set True temporarily to print every SQL statement to the console
)

# ---------------------------------------------------------------------------
# 2. The session factory. Call SessionLocal() to start talking to the DB.
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# 3. The declarative base. Every model class inherits (directly or indirectly)
#    from this. It carries the metadata registry of all tables.
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 4. THE ABSTRACT ENTITY.
#    `__abstract__ = True` tells SQLAlchemy: "do not create a table for this
#    class". It only exists so other models can inherit its columns.
#    Define a shared column ONCE here and it appears in every table.
# ---------------------------------------------------------------------------
class AbstractEntity(Base):
    __abstract__ = True

    # Simple auto-incrementing integer primary key — fast, used for joins.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # A globally-unique id. Safe to expose in URLs/APIs (unlike the sequential
    # `id`, a GUID does not leak how many rows exist). Generated in Python.
    guid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        unique=True,
        nullable=False,
        index=True,
    )

    # Timestamps. `server_default=func.now()` means PostgreSQL itself stamps
    # the time on INSERT; `onupdate` re-stamps last_modified on every UPDATE.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Who created the row. Kept as a simple string (e.g. a user email or id)
    # so it works even before you wire up authentication. Nullable for now.
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# 5. FastAPI dependency. In an endpoint you write `db: Session = Depends(get_db)`
#    and you get a session that is automatically closed when the request ends.
# ---------------------------------------------------------------------------
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
