from pydantic import BaseModel, field_validator


class AppConfigEntry(BaseModel):
    key: str
    value: str
    value_type: str
    description: str | None
    is_editable: bool

    model_config = {"from_attributes": True}


class AppConfigUpdate(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("value must not be blank")
        return v
