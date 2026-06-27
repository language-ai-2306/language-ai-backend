"""
Doctor — extra professional details for a user who is a doctor.

A doctor is also a person who logs in, so we link Doctor to a User account
with a one-to-one foreign key (user_id). The fields below are the doctor-only
extras. (`user_id` was not in your original list, but without it there is no
way to know which login account a doctor row belongs to — so it is added here.)
"""

from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class Doctor(AbstractEntity):
    __tablename__ = "doctor"

    # One-to-one link to the login account. unique=True enforces "one doctor row
    # per user".
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    qualification: Mapped[str] = mapped_column(String(255), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional.
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # The image itself lives in S3; we store its URL (same idea as Avatar.link).
    photo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship()  # noqa: F821 (resolved at runtime)
