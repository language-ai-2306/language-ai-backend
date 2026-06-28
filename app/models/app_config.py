"""Runtime-configurable business rules stored in the database.

Every row is one named setting. Doctors can change values via the admin API
without a code deploy. The `value` column is always a string; callers cast it
using config_service.get_int() / get_bool() / get() as appropriate.

value_type acts as documentation and is used by the admin UI to render the
correct input widget. It does NOT enforce validation on the database side —
that happens in config_service.set_value().
"""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AbstractEntity


class AppConfig(AbstractEntity):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "int" | "float" | "bool" | "str"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
