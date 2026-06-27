"""
PatientDetail — extra details for a user who is a patient.

Like Doctor, a patient is also a login account, so we link to User via user_id.
(`user_id` was not in your original list but is required for the row to mean
anything — added here.)

  * doctor_id -> optional: the patient may not have an assigned doctor yet.
  * avatar_id -> the picture the patient picked.
"""

from typing import List, Optional

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity, Base

# A patient can have many ailments and an ailment applies to many patients
# (many-to-many). That link is stored in this plain association table — it has
# no extra fields of its own, so it does NOT inherit AbstractEntity; it is just
# two foreign keys. The unique pair prevents linking the same ailment twice.
patient_ailment = Table(
    "patient_ailment_assn",
    Base.metadata,
    Column(
        "patient_detail_id",
        ForeignKey("patient_detail.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "ailment_id",
        ForeignKey("ailment.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class PatientDetail(AbstractEntity):
    __tablename__ = "patient_detail"

    # One-to-one link to the login account.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Optional foreign key -> nullable=True. ondelete="SET NULL" means: if the
    # doctor is deleted, the patient is kept but their doctor_id becomes empty.
    doctor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("doctor_details.id", ondelete="SET NULL"),
        nullable=True,
    )

    avatar_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("avatar.id", ondelete="SET NULL"),
        nullable=True,
    )

    nickname: Mapped[str] = mapped_column(String(100), nullable=False)

    # Python-side conveniences for loading the related objects.
    user: Mapped["User"] = relationship()  # noqa: F821
    doctor: Mapped[Optional["Doctor"]] = relationship()  # noqa: F821
    avatar: Mapped[Optional["Avatar"]] = relationship()  # noqa: F821

    # The ailments this patient is practicing (many-to-many via patient_ailment).
    ailments: Mapped[List["Ailment"]] = relationship(  # noqa: F821
        secondary=patient_ailment
    )
