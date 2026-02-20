from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class InsuranceCarrierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    stedi_payer_id: str | None = Field(None, max_length=50)
    is_active: bool = True

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, v: list[str]) -> list[str]:
        for alias in v:
            if not alias or len(alias) > 255:
                raise ValueError("Each alias must be 1-255 characters")
        return v


class InsuranceCarrierCreate(InsuranceCarrierBase):
    pass


class InsuranceCarrierUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = Field(None, max_length=50)
    stedi_payer_id: str | None = Field(None, max_length=50)
    is_active: bool | None = None

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for alias in v:
                if not alias or len(alias) > 255:
                    raise ValueError("Each alias must be 1-255 characters")
        return v


class InsuranceCarrierResponse(InsuranceCarrierBase):
    id: UUID

    model_config = {"from_attributes": True}


class InsuranceCarrierListResponse(BaseModel):
    carriers: list[InsuranceCarrierResponse]
    total: int
