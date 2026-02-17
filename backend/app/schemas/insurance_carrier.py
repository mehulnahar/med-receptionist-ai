from pydantic import BaseModel, Field
from uuid import UUID


class InsuranceCarrierBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    stedi_payer_id: str | None = Field(None, max_length=50)
    is_active: bool = True


class InsuranceCarrierCreate(InsuranceCarrierBase):
    pass


class InsuranceCarrierUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    aliases: list[str] | None = None
    stedi_payer_id: str | None = Field(None, max_length=50)
    is_active: bool | None = None


class InsuranceCarrierResponse(InsuranceCarrierBase):
    id: UUID

    model_config = {"from_attributes": True}


class InsuranceCarrierListResponse(BaseModel):
    carriers: list[InsuranceCarrierResponse]
    total: int
