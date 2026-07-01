"""
Importing every model here does two jobs:

  1. Lets you write `from app.models import User, Ailment` conveniently.
  2. Ensures each model class actually runs (registers itself on Base.metadata)
     so Alembic can SEE it when generating migrations. If a model is never
     imported, Alembic acts as if its table does not exist.
"""

from app.models.ailment import Ailment, AilmentType
from app.models.app_config import AppConfig
from app.models.conversation import ConversationHistory
from app.models.avatar import Avatar
from app.models.delivery import DeliveryContext, PhraseDelivery
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.disfluency_occurrence import DisfluencyOccurrence
from app.models.doctor import Doctor
from app.models.patient import PatientDetail, patient_ailment
from app.models.patient_doctor_request import PatientDoctorRequest, RequestStatus
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_skill import PracticeSkill
from app.models.proficiency import ProficiencyTest, ProficiencyTestResponse
from app.models.user import User, UserRole

__all__ = [
    "AppConfig",
    "ConversationHistory",
    "Avatar",
    "Ailment",
    "AilmentType",
    "Difficulty",
    "DisfluencyPhrase",
    "DisfluencyOccurrence",
    "User",
    "UserRole",
    "Doctor",
    "PatientDetail",
    "patient_ailment",
    "PatientDoctorRequest",
    "RequestStatus",
    "PracticeAttempt",
    "PracticeSkill",
    "PhraseDelivery",
    "DeliveryContext",
    "ProficiencyTest",
    "ProficiencyTestResponse",
]
