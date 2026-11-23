from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Annotated
from decimal import Decimal
import uuid


class Quotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partner_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0, le=1000, allow_inf_nan=False)
    unit_price: float = Field(ge=0, le=100000, allow_inf_nan=False)


class SalesLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=1000, max_digits=6, decimal_places=2, allow_inf_nan=False)
    unit_price: Decimal = Field(ge=0, le=100000, max_digits=8, decimal_places=2, allow_inf_nan=False)
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2, allow_inf_nan=False)
    tax_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=10)

    @field_validator("tax_ids")
    @classmethod
    def unique_taxes(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Không chọn lặp cùng một thuế trong một dòng.")
        return sorted(values)


class SalesQuotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partner_id: int = Field(gt=0)
    lines: list[SalesLine] = Field(min_length=1, max_length=20)


class SalesProposal(SalesQuotation):
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
