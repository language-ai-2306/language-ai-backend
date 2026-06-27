"""
Ailment and AilmentType.

  * Ailment      -> a speech condition, e.g. "stutter", "lisp".
  * AilmentType  -> a sub-category of an ailment, e.g. for "stutter":
                    "repetition", "prolongation", "block".

This is a one-to-many relationship: one Ailment has many AilmentTypes.
The link is made with a FOREIGN KEY (ailment_id on AilmentType pointing at
ailment.id). `relationship(...)` is the Python-side convenience that lets you
write `my_ailment.types` instead of running a manual query.
"""

from typing import List

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class Ailment(AbstractEntity):
    __tablename__ = "ailment"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # All the sub-types belonging to this ailment (filled in automatically).
    types: Mapped[List["AilmentType"]] = relationship(
        back_populates="ailment",
        cascade="all, delete-orphan",
    )


class AilmentType(AbstractEntity):
    __tablename__ = "ailment_type"

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # The foreign key column: stores which ailment.id this type belongs to.
    ailment_id: Mapped[int] = mapped_column(
        ForeignKey("ailment.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The parent ailment object (the Python side of the relationship).
    ailment: Mapped["Ailment"] = relationship(back_populates="types")
