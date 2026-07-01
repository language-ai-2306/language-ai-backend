"""PatientDoctorRequest — a patient's request to be linked to a doctor.

A patient selects a doctor (at signup or later); the row starts PENDING and only
becomes an active link when the doctor APPROVES it. On approval we also set
`PatientDetail.doctor_id` (the confirmed 1:1 link that all existing code reads),
so this table is the *workflow/audit* layer sitting in front of that column.

Status is a real PostgreSQL ENUM (like UserRole/Difficulty) so the database
itself rejects any value outside PENDING/APPROVED/REJECTED.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class RequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PatientDoctorRequest(AbstractEntity):
    __tablename__ = "patient_doctor_request"
    __table_args__ = (
        # At most one request row per patient–doctor pair. A previously REJECTED
        # pair is re-used (flipped back to PENDING) rather than duplicated.
        UniqueConstraint("patient_detail_id", "doctor_id", name="uq_patient_doctor_pair"),
    )

    patient_detail_id: Mapped[int] = mapped_column(
        ForeignKey("patient_detail.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_details.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RequestStatus] = mapped_column(
        SAEnum(RequestStatus, name="request_status_enum"),
        nullable=False,
        default=RequestStatus.PENDING,
        index=True,
    )
    # When the doctor approved/rejected it. NULL while PENDING. (`created_at` from
    # AbstractEntity is the "requested at" time.)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["PatientDetail"] = relationship()  # noqa: F821
    doctor: Mapped["Doctor"] = relationship()  # noqa: F821
