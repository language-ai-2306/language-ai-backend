"""Runtime configuration service — reads/writes the app_config table.

All values are stored as text in the DB. Use the typed helpers (get_int,
get_bool) to cast them on read. set_value() validates the cast before writing
so the DB never holds an un-parseable value.

Callers pass a DB session on every call — no application-level cache. The
app_config table is tiny (< 20 rows) so PostgreSQL caches it automatically.
A simple index on `key` keeps every lookup O(log n).
"""

from sqlalchemy.orm import Session

from app.models.app_config import AppConfig


def get(key: str, db: Session, default: str = "") -> str:
    """Return the raw string value for `key`, or `default` if not found."""
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    return row.value if row else default


def get_int(key: str, db: Session, default: int = 0) -> int:
    """Return `key` as an integer, falling back to `default` on any error."""
    raw = get(key, db, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def get_float(key: str, db: Session, default: float = 0.0) -> float:
    raw = get(key, db, str(default))
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def get_bool(key: str, db: Session, default: bool = False) -> bool:
    raw = get(key, db, str(default)).strip().lower()
    return raw in ("true", "1", "yes")


def set_value(key: str, value: str, db: Session) -> AppConfig:
    """Update a config entry's value. Raises KeyError / ValueError / PermissionError."""
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if not row:
        raise KeyError(f"Config key '{key}' not found")
    if not row.is_editable:
        raise PermissionError(f"Config key '{key}' is read-only")

    # Validate that the new value is parseable as the declared type before saving.
    _validate_type(key, value, row.value_type)

    row.value = value
    db.commit()
    db.refresh(row)
    return row


def _validate_type(key: str, value: str, value_type: str) -> None:
    try:
        if value_type == "int":
            int(value)
        elif value_type == "float":
            float(value)
        elif value_type == "bool":
            if value.strip().lower() not in ("true", "false", "1", "0", "yes", "no"):
                raise ValueError(f"'{value}' is not a valid boolean")
    except ValueError as exc:
        raise ValueError(
            f"Config key '{key}' expects type {value_type}, but '{value}' cannot be parsed: {exc}"
        ) from exc
