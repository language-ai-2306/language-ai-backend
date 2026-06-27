"""Avatar — a picture a patient can pick to represent themselves."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AbstractEntity


class Avatar(AbstractEntity):
    __tablename__ = "avatar"

    # URL/link to the image (the actual file lives in S3; we store its address).
    link: Mapped[str] = mapped_column(String(500), nullable=False)
