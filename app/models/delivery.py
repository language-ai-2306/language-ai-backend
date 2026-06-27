"""
PhraseDelivery — one row every time a phrase is SHOWN to a user.

This is the table that powers the "no phrase repeats for 15 days" rule. To find
what a user may NOT be served, we look for rows here with this user_id whose
created_at (the time it was shown) is within the last 15 days.

We reuse AbstractEntity.created_at as the "shown at" timestamp, so there is no
separate time column to keep in sync.
"""

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AbstractEntity


class DeliveryContext(str, enum.Enum):
    """Why the phrase was shown — useful for analytics and debugging."""

    PROFICIENCY_TEST = "PROFICIENCY_TEST"
    GAME = "GAME"


class PhraseDelivery(AbstractEntity):
    __tablename__ = "phrase_delivery"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # we filter by user a lot, so index it
    )
    phrase_id: Mapped[int] = mapped_column(
        ForeignKey("disfluency_phrase.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context: Mapped[DeliveryContext] = mapped_column(
        SAEnum(DeliveryContext, name="delivery_context_enum"),
        nullable=False,
    )
